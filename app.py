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
from urllib.parse import parse_qs, urlencode, urlsplit
import urllib.request

ROOT = Path(__file__).parent
MAX_BODY = 2_000_000
SESSION_SECONDS = 12 * 3600
REMEMBER_SECONDS = 30 * 24 * 3600

# FAA Aeronautical Information Services, Class Airspace (published every eight weeks).
AIRSPACE_URL = 'https://services6.arcgis.com/ssFJjBXIUyZDrSYZ/arcgis/rest/services/Class_Airspace/FeatureServer/0/query'
AIRSPACE_CELL = 2              # degrees; the map asks for 2x2 degree cells
AIRSPACE_TTL = 24 * 3600       # cache each cell for a day
AIRSPACE_CACHE_CELLS = 64
AIRSPACE_PAGE = 1000
AIRSPACE_MAX_PAGES = 4
AIRSPACE_MAX_BYTES = 8_000_000
AIRSPACE_CLASSES = ('B', 'C', 'D')


def parse_home_view(text):
    """HOME_VIEW='lat,lon,zoom' (e.g. '33.47,-82.50,10') -> [lat, lon, zoom], or None if unset.

    Kept in Render's settings rather than the repository, so the receiver's area
    is only sent to signed-in viewers."""
    text = (text or '').strip()
    if not text:
        return None
    try:
        lat, lon, zoom = (float(part) for part in text.split(','))
    except ValueError:
        raise RuntimeError('HOME_VIEW must be "latitude,longitude,zoom", e.g. 33.47,-82.50,10')
    if not (-90 <= lat <= 90 and -180 <= lon <= 180 and 3 <= zoom <= 16):
        raise RuntimeError('HOME_VIEW is out of range: latitude -90..90, longitude -180..180, zoom 3..16')
    return [round(lat, 4), round(lon, 4), round(zoom, 1)]


def fetch_json(url, timeout=15):
    request = urllib.request.Request(url, headers={'User-Agent': 'HomeAirspace/1.0', 'Accept': 'application/json'})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        body = response.read(AIRSPACE_MAX_BYTES + 1)
    if len(body) > AIRSPACE_MAX_BYTES:
        raise ValueError('Airspace response too large')
    return json.loads(body)


def parse_cell(text):
    """'32,-86' -> (32, -86): the south-west corner of a 2x2 degree cell."""
    try:
        lat, lon = (int(part) for part in text.split(','))
    except (ValueError, AttributeError):
        raise ValueError('Invalid cell')
    if lat % AIRSPACE_CELL or lon % AIRSPACE_CELL or not (-90 <= lat <= 90 - AIRSPACE_CELL) or not (-180 <= lon <= 180 - AIRSPACE_CELL):
        raise ValueError('Invalid cell')
    return lat, lon


def clean_ring(ring):
    points = []
    for point in ring if isinstance(ring, list) else []:
        if not (isinstance(point, list) and len(point) >= 2):
            return None
        lon, lat = point[0], point[1]
        if not all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) for v in (lon, lat)):
            return None
        if not (-180 <= lon <= 180 and -90 <= lat <= 90):
            return None
        points.append([round(lon, 5), round(lat, 5)])
    return points if len(points) >= 4 else None


def clean_airspace(collection):
    """Keep only Class B/C/D polygons with the few fields the map shows."""
    if not isinstance(collection, dict) or not isinstance(collection.get('features'), list):
        raise ValueError('Expected GeoJSON features')
    features = []
    for item in collection['features']:
        if not isinstance(item, dict):
            continue
        props, geometry = item.get('properties') or {}, item.get('geometry') or {}
        if not isinstance(props, dict) or not isinstance(geometry, dict) or props.get('CLASS') not in AIRSPACE_CLASSES:
            continue
        kind, coords = geometry.get('type'), geometry.get('coordinates')
        polygons = [coords] if kind == 'Polygon' else coords if kind == 'MultiPolygon' else None
        if not isinstance(polygons, list):
            continue
        cleaned = []
        for polygon in polygons:
            rings = [clean_ring(ring) for ring in polygon] if isinstance(polygon, list) else [None]
            if rings and all(rings):
                cleaned.append(rings)
        if not cleaned:
            continue
        def value(key):
            v = props.get(key)
            return v if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) else None
        def text(key):
            v = props.get(key)
            return v[:80] if isinstance(v, str) else None
        oid = item.get('id', props.get('OBJECTID'))
        features.append({'type': 'Feature', 'id': oid if isinstance(oid, int) and not isinstance(oid, bool) else None,
                         'geometry': {'type': 'MultiPolygon', 'coordinates': cleaned},
                         'properties': {'class': props['CLASS'], 'name': text('NAME'), 'ident': text('IDENT'),
                                        'upper': value('UPPER_VAL'), 'upper_code': text('UPPER_CODE'),
                                        'lower': value('LOWER_VAL'), 'lower_code': text('LOWER_CODE')}})
    return {'type': 'FeatureCollection', 'features': features}


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
        self.home = parse_home_view(env.get('HOME_VIEW', ''))
        if len(self.upload_token) < 40:
            raise RuntimeError('UPLOAD_TOKEN must contain at least 40 random characters')
        secret = env.get('SESSION_SECRET', '')
        if secret:
            if len(secret) < 32:
                raise RuntimeError('SESSION_SECRET must contain at least 32 random characters')
            # Sessions survive restarts. Changing the password or the secret signs everyone out.
            self.key = hmac.new(secret.encode(), b'adsb-away session v1|' + self.password.encode(), hashlib.sha256).digest()
        else:
            # Without a configured secret, a restart invalidates all sessions.
            self.key = secrets.token_bytes(32)
        self.lock = threading.Lock()
        self.failures = deque(maxlen=10)
        self.revoked = {}
        self.feed = None
        self.received = 0
        self.airspace = {}
        self.fetch_json = fetch_json

    def airspace_cell(self, cell):
        """Class B/C/D airspace for one cell, fetched from the FAA and cached for a day."""
        now = time.time()
        with self.lock:
            cached = self.airspace.get(cell)
            if cached and now - cached[0] < AIRSPACE_TTL:
                return cached[1]
        lat, lon = cell
        base = {'where': "CLASS IN ('B','C','D')", 'geometry': f'{lon},{lat},{lon + AIRSPACE_CELL},{lat + AIRSPACE_CELL}',
                'geometryType': 'esriGeometryEnvelope', 'inSR': '4326', 'spatialRel': 'esriSpatialRelIntersects',
                'outFields': 'OBJECTID,CLASS,NAME,IDENT,UPPER_VAL,UPPER_CODE,LOWER_VAL,LOWER_CODE',
                'returnGeometry': 'true', 'outSR': '4326', 'geometryPrecision': '5', 'maxAllowableOffset': '0.0003',
                'orderByFields': 'OBJECTID', 'resultRecordCount': str(AIRSPACE_PAGE), 'f': 'geojson'}
        features, deadline = [], now + 25
        for page in range(AIRSPACE_MAX_PAGES):
            remaining = deadline - time.time()
            if remaining < 2:
                raise ValueError('FAA airspace service too slow')
            data = self.fetch_json(AIRSPACE_URL + '?' + urlencode(dict(base, resultOffset=str(page * AIRSPACE_PAGE))), timeout=min(15, remaining))
            features += clean_airspace(data)['features']
            more = data.get('exceededTransferLimit') or (data.get('properties') or {}).get('exceededTransferLimit')
            if not more:
                break
        body = json.dumps({'type': 'FeatureCollection', 'features': features}, separators=(',', ':')).encode()
        with self.lock:
            self.airspace[cell] = (now, body)
            while len(self.airspace) > AIRSPACE_CACHE_CELLS:
                del self.airspace[min(self.airspace, key=lambda k: self.airspace[k][0])]
        return body

    def signed_session(self, expires=None):
        value = f'{int(expires or time.time() + SESSION_SECONDS)}.{secrets.token_hex(16)}'
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
                       ('Referrer-Policy', 'strict-origin-when-cross-origin'), ('X-Frame-Options', 'DENY'),
                       ('Permissions-Policy', 'geolocation=(), camera=(), microphone=()'),
                       ('Content-Security-Policy', "default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: https://tile.openstreetmap.org https://tiles.arcgis.com; connect-src 'self'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'")]
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
                form, valid = {}, False
            if not valid:
                return reply('303 See Other', extra=[('Location', '/login?failed=1')])
            lifetime = REMEMBER_SECONDS if form.get('remember') == ['1'] else SESSION_SECONDS
            token = self.signed_session(time.time() + lifetime)
            return reply('303 See Other', extra=[('Location', '/'), ('Set-Cookie', f'session={token}; Path=/; Max-Age={lifetime}; HttpOnly; SameSite=Strict{secure}')])
        if method != 'GET':
            return reply('405 Method Not Allowed', 'Method not allowed')
        if path == '/login':
            return reply('200 OK', (ROOT / 'static/login.html').read_bytes(), 'text/html; charset=utf-8')
        if path == '/static/style.css':
            return reply('200 OK', (ROOT / 'static/style.css').read_bytes(), 'text/css')
        if path == '/static/tvnav.js':
            return reply('200 OK', (ROOT / 'static/tvnav.js').read_bytes(), 'application/javascript')
        if not self.session(environ):
            if path.startswith('/api/'):
                return reply('401 Unauthorized', 'Login required')
            return reply('303 See Other', extra=[('Location', '/login')])
        if path == '/api/airspace':
            try:
                cell = parse_cell(parse_qs(environ.get('QUERY_STRING', '')).get('cell', [''])[0])
            except ValueError:
                return reply('400 Bad Request', 'Invalid cell')
            try:
                body = self.airspace_cell(cell)
            except (OSError, ValueError, UnicodeError, RecursionError):
                return reply('502 Bad Gateway', 'FAA airspace data is unavailable right now')
            return reply('200 OK', body, 'application/json')
        if path == '/api/aircraft':
            with self.lock:
                age = time.time() - self.received if self.received else None
                source_age = time.time() - self.feed['now'] if self.feed else None
                online = age is not None and age < 30 and source_age < 30
                result = {'online': online, 'age': age, 'source_age': source_age,
                          'aircraft': self.feed['aircraft'] if online else [],
                          'now': self.feed['now'] if self.feed else None, 'home': self.home}
            return reply('200 OK', json.dumps(result), 'application/json')
        files = {'/': ('index.html', 'text/html; charset=utf-8'),
                 '/static/app.js': ('app.js', 'application/javascript'),
                 '/static/airspace.js': ('airspace.js', 'application/javascript'),
                 '/static/leaflet.js': ('leaflet.js', 'application/javascript'),
                 '/static/leaflet.css': ('leaflet.css', 'text/css')}
        if path in files:
            name, mime = files[path]
            return reply('200 OK', (ROOT / 'static' / name).read_bytes(), mime)
        return reply('404 Not Found', 'Not found')


def create_app():
    return App()

