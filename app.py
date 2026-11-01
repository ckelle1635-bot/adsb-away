"""Single-process WSGI service. Run production with the supplied Gunicorn command."""
import hashlib
import hmac
import json
import math
import os
from pathlib import Path
import secrets
import threading
import time
from collections import deque
from http.cookies import SimpleCookie
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).parent
MAX_BODY = 2_000_000


def password_hash(password, salt=None):
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), 600_000).hex()
    return f'pbkdf2_sha256$600000${salt}${digest}'


def check_password(password, encoded):
    try:
        algorithm, rounds, salt, expected = encoded.split('$')
        if algorithm != 'pbkdf2_sha256' or int(rounds) != 600_000:
            return False
        return hmac.compare_digest(password_hash(password, salt), encoded)
    except (ValueError, TypeError):
        return False


def clean_feed(data, now):
    if not isinstance(data, dict) or not isinstance(data.get('aircraft'), list):
        raise ValueError('Expected aircraft JSON')
    stamp = data.get('now')
    if isinstance(stamp, bool) or not isinstance(stamp, (int, float)) or not math.isfinite(stamp) or abs(stamp - now) > 120:
        raise ValueError('Receiver timestamp must be within two minutes of server time')
    if len(data['aircraft']) > 5000:
        raise ValueError('Too many aircraft')
    rows = []
    strings = {'hex', 'flight', 'r', 't', 'desc', 'ownOp', 'emergency'}
    numbers = {'lat', 'lon', 'alt_baro', 'alt_geom', 'gs', 'track', 'baro_rate', 'seen', 'seen_pos', 'rssi'}
    for item in data['aircraft']:
        if not isinstance(item, dict):
            raise ValueError('Invalid aircraft')
        row = {k: v[:160].strip() for k, v in item.items() if k in strings and isinstance(v, str)}
        if not row.get('hex') or len(row['hex']) > 16:
            continue
        for key in numbers:
            value = item.get(key)
            if isinstance(value, (float, int)) and not isinstance(value, bool) and math.isfinite(value):
                row[key] = value
        if item.get('alt_baro') == 'ground':
            row['alt_baro'] = 'ground'
        if not (-90 <= row.get('lat', 999) <= 90 and -180 <= row.get('lon', 999) <= 180):
            row.pop('lat', None)
            row.pop('lon', None)
        rows.append(row)
    return {'now': stamp, 'aircraft': rows}


class App:
    def __init__(self, config=None):
        env = os.environ if config is None else config
        self.public_url = env.get('PUBLIC_URL', '').rstrip('/')
        self.local = env.get('LOCAL_DEV') == '1'
        origin = urlsplit(self.public_url)
        if not origin.netloc or origin.path or origin.query or origin.fragment or origin.username or (origin.scheme != 'https' and not self.local):
            raise RuntimeError('PUBLIC_URL must be your HTTPS origin, without a path')
        self.password = env.get('VIEWER_PASSWORD_HASH', '')
        if not self.password.startswith('pbkdf2_sha256$600000$'):
            raise RuntimeError('Configure VIEWER_PASSWORD_HASH using configure.py')
        self.upload_token = env.get('UPLOAD_TOKEN', '')
        if len(self.upload_token) < 40:
            raise RuntimeError('UPLOAD_TOKEN must contain at least 40 random characters')
        # Restart invalidates all sessions. No persistent signing secret needed.
        self.key = secrets.token_bytes(32)
        self.lock = threading.Lock()
        self.failures = deque(maxlen=10)
        self.revoked = {}
        self.feed = None
        self.received = 0

    def signed_session(self, expires=None):
        value = f'{int(expires or time.time() + 12*3600)}.{secrets.token_hex(16)}'
        return value + '.' + hmac.new(self.key, value.encode(), hashlib.sha256).hexdigest()

    def session(self, environ):
        try:
            cookie = SimpleCookie(environ.get('HTTP_COOKIE', ''))
            token = cookie['session'].value
            expiry, nonce, signature = token.split('.')
            expected = hmac.new(self.key, f'{expiry}.{nonce}'.encode(), hashlib.sha256).hexdigest()
            with self.lock:
                valid = token not in self.revoked
            if valid and int(expiry) > time.time() and hmac.compare_digest(signature.encode(), expected.encode()):
                return token
        except (KeyError, ValueError):
            pass
        return None

    def __call__(self, environ, start_response):
        def reply(code, body=b'', content_type='text/plain; charset=utf-8', extra=()):
            if isinstance(body, str):
                body = body.encode()
            headers = [('Content-Type', content_type), ('Content-Length', str(len(body))),
                       ('Cache-Control', 'no-store'), ('X-Content-Type-Options', 'nosniff'),
                       ('Referrer-Policy', 'same-origin'), ('X-Frame-Options', 'DENY'),
                       ('Permissions-Policy', 'geolocation=(), camera=(), microphone=()'),
                       ('Content-Security-Policy', "default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: https://tile.openstreetmap.org; connect-src 'self'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'")]
            if not self.local:
                headers.append(('Strict-Transport-Security', 'max-age=31536000'))
            start_response(code, headers + list(extra))
            return [body]

        def read_body(limit):
            try:
                length = int(environ.get('CONTENT_LENGTH', '') or 0)
            except ValueError:
                raise ValueError('Invalid content length')
            if not 0 < length <= limit:
                raise ValueError('Missing or oversized body')
            body = environ['wsgi.input'].read(length)
            if len(body) != length:
                raise ValueError('Incomplete body')
            return body

        path, method = environ.get('PATH_INFO', '/'), environ.get('REQUEST_METHOD', 'GET')
        if path == '/healthz' and method == 'GET':
            return reply('200 OK', 'ok')
        if method == 'POST' and path == '/api/ingest':
            provided = environ.get('HTTP_AUTHORIZATION', '')
            if not hmac.compare_digest(provided.encode(), ('Bearer ' + self.upload_token).encode()):
                return reply('401 Unauthorized', 'Unauthorized')
            if environ.get('CONTENT_TYPE', '').split(';')[0] != 'application/json':
                return reply('415 Unsupported Media Type', 'Expected JSON')
            try:
                data = json.loads(read_body(MAX_BODY), parse_constant=lambda _: (_ for _ in ()).throw(ValueError('Invalid number')))
                now = time.time()
                feed = clean_feed(data, now)
                with self.lock:
                    if self.feed and feed['now'] < self.feed['now']:
                        return reply('409 Conflict', 'Out-of-order snapshot')
                    self.feed, self.received = feed, now
                return reply('204 No Content')
            except (ValueError, UnicodeError, RecursionError):
                return reply('400 Bad Request', 'Invalid, oversized, or stale aircraft snapshot')
        if method == 'POST' and path in {'/login', '/logout'}:
            if environ.get('HTTP_ORIGIN') != self.public_url:
                return reply('403 Forbidden', 'Invalid origin')
            secure = '' if self.local else '; Secure'
            if path == '/logout':
                token = self.session(environ)
                if token:
                    with self.lock:
                        self.revoked = {k: v for k, v in self.revoked.items() if v > time.time()}
                        self.revoked[token] = int(token.split('.')[0])
                return reply('303 See Other', extra=[('Location', '/login'), ('Set-Cookie', f'session=; Path=/; Max-Age=0; HttpOnly; SameSite=Strict{secure}')])
            with self.lock:
                now = time.time()
                while self.failures and self.failures[0] < now - 600:
                    self.failures.popleft()
                if len(self.failures) >= 10:
                    return reply('429 Too Many Requests', 'Too many attempts. Try again in ten minutes.', extra=[('Retry-After', '600')])
                # Reserve before the expensive password hash, limiting concurrent guesses too.
                self.failures.append(now)
            try:
                form = parse_qs(read_body(4096).decode())
                valid = check_password(form.get('password', [''])[0], self.password)
            except (ValueError, UnicodeError):
                valid = False
            if not valid:
                return reply('303 See Other', extra=[('Location', '/login?failed=1')])
            token = self.signed_session()
            return reply('303 See Other', extra=[('Location', '/'), ('Set-Cookie', f'session={token}; Path=/; Max-Age=43200; HttpOnly; SameSite=Strict{secure}')])
        if method != 'GET':
            return reply('405 Method Not Allowed', 'Method not allowed')
        if path == '/login':
            return reply('200 OK', (ROOT / 'static/login.html').read_bytes(), 'text/html; charset=utf-8')
        if path == '/static/style.css':
            return reply('200 OK', (ROOT / 'static/style.css').read_bytes(), 'text/css')
        if not self.session(environ):
            if path.startswith('/api/'):
                return reply('401 Unauthorized', 'Login required')
            return reply('303 See Other', extra=[('Location', '/login')])
        if path == '/api/aircraft':
            with self.lock:
                age = time.time() - self.received if self.received else None
                source_age = time.time() - self.feed['now'] if self.feed else None
                online = age is not None and age < 30 and source_age < 30
                result = {'online': online, 'age': age, 'source_age': source_age,
                          'aircraft': self.feed['aircraft'] if online else [],
                          'now': self.feed['now'] if self.feed else None}
            return reply('200 OK', json.dumps(result), 'application/json')
        files = {'/': ('index.html', 'text/html; charset=utf-8'),
                 '/static/app.js': ('app.js', 'application/javascript'),
                 '/static/leaflet.js': ('leaflet.js', 'application/javascript'),
                 '/static/leaflet.css': ('leaflet.css', 'text/css')}
        if path in files:
            name, mime = files[path]
            return reply('200 OK', (ROOT / 'static' / name).read_bytes(), mime)
        return reply('404 Not Found', 'Not found')


def create_app():
    return App()

