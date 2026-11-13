import io
import json
import unittest

from app import App, parse_home_view, password_hash

BASE = {'PUBLIC_URL': 'https://example.test', 'VIEWER_PASSWORD_HASH': password_hash('test-only-long-password-for-suite'),
        'UPLOAD_TOKEN': 'test-only-upload-token-' + 'a' * 48}


def aircraft_json(app):
    env = {'PATH_INFO': '/api/aircraft', 'REQUEST_METHOD': 'GET', 'wsgi.input': io.BytesIO(b''),
           'CONTENT_LENGTH': '0', 'HTTP_COOKIE': 'session=' + app.signed_session()}
    return json.loads(b''.join(app(env, lambda status, headers: None)))


class HomeViewTests(unittest.TestCase):
    def test_parses_and_rounds(self):
        self.assertEqual(parse_home_view(' 33.470123, -82.500456 , 10 '), [33.4701, -82.5005, 10.0])
        self.assertIsNone(parse_home_view(''))
        self.assertIsNone(parse_home_view(None))

    def test_rejects_bad_values(self):
        for bad in ['33.4,-82.5', '33.4,-82.5,10,1', 'a,b,c', '95,0,10', '0,190,10', '33,-82,1', '33,-82,20', 'nan,0,10']:
            with self.assertRaises(RuntimeError, msg=bad):
                parse_home_view(bad)
        with self.assertRaises(RuntimeError):
            App(dict(BASE, HOME_VIEW='nowhere'))

    def test_sent_only_to_signed_in_viewers(self):
        app = App(dict(BASE, HOME_VIEW='33.47,-82.5,10'))
        self.assertEqual(aircraft_json(app)['home'], [33.47, -82.5, 10.0])
        self.assertIsNone(aircraft_json(App(BASE))['home'])
        env = {'PATH_INFO': '/api/aircraft', 'REQUEST_METHOD': 'GET', 'wsgi.input': io.BytesIO(b''), 'CONTENT_LENGTH': '0'}
        result = {}
        body = b''.join(app(env, lambda status, headers: result.update(status=status)))
        self.assertTrue(result['status'].startswith('401'))
        self.assertNotIn(b'33.47', body)


if __name__ == '__main__':
    unittest.main()
