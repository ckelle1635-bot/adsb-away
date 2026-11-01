import io
import json
import time
import unittest
from unittest.mock import patch
from app import App, password_hash

PASSWORD = 'test-only-long-password-for-suite'
HASH = password_hash(PASSWORD)
TOKEN = 'test-only-upload-token-' + 'a' * 48


class SecurityTests(unittest.TestCase):
    def setUp(self):
        self.app = App({'PUBLIC_URL': 'https://example.test', 'VIEWER_PASSWORD_HASH': HASH, 'UPLOAD_TOKEN': TOKEN})

    def request(self, path, method='GET', body=b'', **headers):
        env = {'PATH_INFO': path, 'REQUEST_METHOD': method, 'wsgi.input': io.BytesIO(body), 'CONTENT_LENGTH': str(len(body))}
        env.update(headers)
        result = {}
        def start(status, response_headers):
            result.update(status=int(status.split()[0]), headers=dict(response_headers))
        result['body'] = b''.join(self.app(env, start))
        return result

    def snapshot(self, **changes):
        data = {'now': time.time(), 'aircraft': [{'hex': 'a12345', 'flight': '<script>alert(1)</script>', 'lat': 33, 'lon': -83, 'seen': 0, 'seen_pos': 0}]}
        data.update(changes)
        return json.dumps(data).encode()

    def ingest(self, body=None, token=TOKEN):
        return self.request('/api/ingest', 'POST', body if body is not None else self.snapshot(), HTTP_AUTHORIZATION='Bearer ' + token, CONTENT_TYPE='application/json')

    def test_no_public_feed_or_viewer(self):
        for path, status in [('/api/aircraft', 401), ('/', 303), ('/static/app.js', 303), ('/static/leaflet.js', 303)]:
            self.assertEqual(self.request(path)['status'], status)
        self.assertEqual(self.request('/api/aircraft', HTTP_AUTHORIZATION='Bearer ' + TOKEN)['status'], 401)
        # Only the sign-in page's assets are public.
        for path in ['/login', '/static/style.css', '/static/tvnav.js']:
            self.assertEqual(self.request(path)['status'], 200)

    def test_upload_requires_distinct_token(self):
        self.assertEqual(self.ingest(token='wrong')['status'], 401)
        self.assertEqual(self.ingest()['status'], 204)
        result = self.request('/api/aircraft', HTTP_COOKIE='session=' + self.app.signed_session())
        self.assertTrue(json.loads(result['body'])['online'])

    def test_csrf_and_login_cookie(self):
        body = ('password=' + PASSWORD).encode()
        for origin in ['', 'https://evil.test']:
            self.assertEqual(self.request('/login', 'POST', body, HTTP_ORIGIN=origin)['status'], 403)
        result = self.request('/login', 'POST', body, HTTP_ORIGIN='https://example.test')
        self.assertEqual(result['status'], 303)
        cookie = result['headers']['Set-Cookie']
        for flag in ['Secure', 'HttpOnly', 'SameSite=Strict', 'Max-Age=43200']:
            self.assertIn(flag, cookie)
        self.assertNotIn(PASSWORD.encode(), result['body'])

    def test_expired_forged_and_logged_out_sessions(self):
        expired = self.app.signed_session(time.time() - 1)
        valid = self.app.signed_session()
        for token in [expired, valid + 'f', 'malformed']:
            self.assertEqual(self.request('/api/aircraft', HTTP_COOKIE='session=' + token)['status'], 401)
        result = self.request('/logout', 'POST', HTTP_ORIGIN='https://example.test', HTTP_COOKIE='session=' + valid)
        self.assertEqual(result['status'], 303)
        self.assertEqual(self.request('/api/aircraft', HTTP_COOKIE='session=' + valid)['status'], 401)

    def test_password_guess_limit(self):
        with patch('app.check_password', return_value=False) as check:
            for _ in range(10):
                self.request('/login', 'POST', b'password=wrong', HTTP_ORIGIN='https://example.test')
            self.assertEqual(self.request('/login', 'POST', b'password=wrong', HTTP_ORIGIN='https://example.test')['status'], 429)
            self.assertEqual(check.call_count, 10)

    def test_stale_and_out_of_order_snapshots(self):
        self.assertEqual(self.ingest(self.snapshot(now=time.time() - 121))['status'], 400)
        self.assertEqual(self.ingest()['status'], 204)
        self.assertEqual(self.ingest(self.snapshot(now=time.time() - 5))['status'], 409)
        with patch('app.time.time', return_value=time.time() + 31):
            result = self.request('/api/aircraft', HTTP_COOKIE='session=' + self.app.signed_session())
        data = json.loads(result['body'])
        self.assertFalse(data['online'])
        self.assertEqual(data['aircraft'], [])

    def test_invalid_input_and_size_limits(self):
        for body in [b'[]', b'{', self.snapshot(now=True), self.snapshot(now=float('nan')), self.snapshot(aircraft=[None]), b'a' * 2_000_001]:
            self.assertEqual(self.ingest(body)['status'], 400)

    def test_source_age_not_just_upload_age(self):
        self.assertEqual(self.ingest(self.snapshot(now=time.time() - 60))['status'], 204)
        data = json.loads(self.request('/api/aircraft', HTTP_COOKIE='session=' + self.app.signed_session())['body'])
        self.assertFalse(data['online'])

    def test_no_path_traversal_or_public_receiver_metadata(self):
        self.assertEqual(self.request('/static/../app.py', HTTP_COOKIE='session=' + self.app.signed_session())['status'], 404)
        self.ingest(self.snapshot(receiver={'lat': 33, 'lon': -83}, secret='hidden'))
        data = self.request('/api/aircraft', HTTP_COOKIE='session=' + self.app.signed_session())
        self.assertNotIn(b'receiver', data['body'])
        self.assertNotIn(b'hidden', data['body'])
        self.assertEqual(data['headers']['Cache-Control'], 'no-store')

    def login(self, body):
        return self.request('/login', 'POST', body, HTTP_ORIGIN='https://example.test')

    def test_remember_device_lasts_thirty_days(self):
        cookie = self.login(('password=' + PASSWORD + '&remember=1').encode())['headers']['Set-Cookie']
        self.assertIn('Max-Age=2592000', cookie)
        token = cookie.split(';')[0].split('=', 1)[1]
        with patch('app.time.time', return_value=time.time() + 29 * 86400):
            self.assertEqual(self.request('/api/aircraft', HTTP_COOKIE='session=' + token)['status'], 200)
        with patch('app.time.time', return_value=time.time() + 31 * 86400):
            self.assertEqual(self.request('/api/aircraft', HTTP_COOKIE='session=' + token)['status'], 401)
        for body in ['password=' + PASSWORD, 'password=' + PASSWORD + '&remember=yes']:
            self.assertIn('Max-Age=43200', self.login(body.encode())['headers']['Set-Cookie'])
        self.assertIn('failed=1', self.login(b'password=wrong&remember=1')['headers']['Location'])

    def test_session_secret_survives_restart_but_not_password_change(self):
        secret = 's' * 40
        config = {'PUBLIC_URL': 'https://example.test', 'VIEWER_PASSWORD_HASH': HASH, 'UPLOAD_TOKEN': TOKEN, 'SESSION_SECRET': secret}
        token = App(config).signed_session()
        self.app = App(dict(config))
        self.assertEqual(self.request('/api/aircraft', HTTP_COOKIE='session=' + token)['status'], 200)
        self.app = App(dict(config, SESSION_SECRET='t' * 40))
        self.assertEqual(self.request('/api/aircraft', HTTP_COOKIE='session=' + token)['status'], 401)
        self.app = App(dict(config, VIEWER_PASSWORD_HASH=password_hash('another-long-password-for-tests')))
        self.assertEqual(self.request('/api/aircraft', HTTP_COOKIE='session=' + token)['status'], 401)
        with self.assertRaises(RuntimeError):
            App(dict(config, SESSION_SECRET='short'))

    def test_without_session_secret_restart_signs_out(self):
        token = self.app.signed_session()
        self.setUp()
        self.assertEqual(self.request('/api/aircraft', HTTP_COOKIE='session=' + token)['status'], 401)

    def test_production_requires_https_and_secrets(self):
        for config in [{}, {'PUBLIC_URL': 'http://example.test'}, {'PUBLIC_URL': 'https://example.test'}]:
            with self.assertRaises(RuntimeError):
                App(config)


if __name__ == '__main__':
    unittest.main()
