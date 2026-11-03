import io
import json
import time
import unittest
from unittest.mock import patch

from app import App, AIRSPACE_TTL, clean_airspace, parse_cell, password_hash

HASH = password_hash('test-only-long-password-for-suite')
TOKEN = 'test-only-upload-token-' + 'a' * 48
SQUARE = [[[-84.5, 33.5], [-84.4, 33.5], [-84.4, 33.6], [-84.5, 33.6], [-84.5, 33.5]]]


def feature(cls='B', geometry=None, **props):
    base = {'OBJECTID': 7, 'CLASS': cls, 'NAME': 'ATLANTA CLASS B', 'IDENT': 'ATL', 'UPPER_VAL': 12500,
            'UPPER_CODE': 'MSL', 'LOWER_VAL': 2500, 'LOWER_CODE': 'MSL', 'CITY': 'not kept'}
    base.update(props)
    return {'type': 'Feature', 'id': base['OBJECTID'], 'properties': base,
            'geometry': geometry or {'type': 'Polygon', 'coordinates': SQUARE}}


class AirspaceTests(unittest.TestCase):
    def setUp(self):
        self.app = App({'PUBLIC_URL': 'https://example.test', 'VIEWER_PASSWORD_HASH': HASH, 'UPLOAD_TOKEN': TOKEN})
        self.calls = []
        self.pages = [{'type': 'FeatureCollection', 'features': [feature()]}]

        def fake_fetch(url, timeout=15):
            self.calls.append(url)
            return self.pages[min(len(self.calls) - 1, len(self.pages) - 1)]
        self.app.fetch_json = fake_fetch

    def get(self, query, signed_in=True):
        env = {'PATH_INFO': '/api/airspace', 'REQUEST_METHOD': 'GET', 'QUERY_STRING': query,
               'wsgi.input': io.BytesIO(b''), 'CONTENT_LENGTH': '0'}
        if signed_in:
            env['HTTP_COOKIE'] = 'session=' + self.app.signed_session()
        result = {}
        def start(status, headers):
            result.update(status=int(status.split()[0]), headers=dict(headers))
        result['body'] = b''.join(self.app(env, start))
        return result

    def test_requires_sign_in(self):
        self.assertEqual(self.get('cell=32,-86', signed_in=False)['status'], 401)
        self.assertEqual(self.calls, [])

    def test_rejects_bad_cells(self):
        for query in ['', 'cell=', 'cell=33,-86', 'cell=32,-85', 'cell=90,0', 'cell=0,180', 'cell=a,b', 'cell=1,2,3', 'cell=32.0,-86']:
            self.assertEqual(self.get(query)['status'], 400, query)
        self.assertEqual(self.calls, [])
        self.assertEqual(parse_cell('-90,-180'), (-90, -180))

    def test_returns_cleaned_class_bcd_only(self):
        self.pages = [{'type': 'FeatureCollection', 'features': [
            feature(),
            feature('E', OBJECTID=8),
            feature('C', OBJECTID=9, geometry={'type': 'Point', 'coordinates': [-84, 33]}),
            feature('D', OBJECTID=10, geometry={'type': 'Polygon', 'coordinates': [[[-84, 33], [float('nan'), 33], [-84, 34], [-84, 33]]]}),
            'junk']}]
        result = self.get('cell=32,-86')
        self.assertEqual(result['status'], 200)
        data = json.loads(result['body'])
        self.assertEqual(len(data['features']), 1)
        only = data['features'][0]
        self.assertEqual(only['id'], 7)
        self.assertEqual(only['geometry']['type'], 'MultiPolygon')
        self.assertEqual(only['properties'], {'class': 'B', 'name': 'ATLANTA CLASS B', 'ident': 'ATL', 'upper': 12500,
                                              'upper_code': 'MSL', 'lower': 2500, 'lower_code': 'MSL'})
        query = self.calls[0]
        self.assertIn('geometry=-86%2C32%2C-84%2C34', query)
        self.assertIn('f=geojson', query)

    def test_cached_for_a_day_then_refreshed(self):
        self.assertEqual(self.get('cell=32,-86')['status'], 200)
        self.assertEqual(self.get('cell=32,-86')['status'], 200)
        self.assertEqual(len(self.calls), 1)
        with patch('app.time.time', return_value=time.time() + AIRSPACE_TTL + 1):
            self.assertEqual(self.get('cell=32,-86')['status'], 200)
        self.assertEqual(len(self.calls), 2)

    def test_follows_pages(self):
        self.pages = [{'type': 'FeatureCollection', 'properties': {'exceededTransferLimit': True}, 'features': [feature()]},
                      {'type': 'FeatureCollection', 'features': [feature('D', OBJECTID=11)]}]
        data = json.loads(self.get('cell=32,-86')['body'])
        self.assertEqual([f['id'] for f in data['features']], [7, 11])
        self.assertIn('resultOffset=1000', self.calls[1])

    def test_faa_outage_is_a_502_and_not_cached(self):
        def broken(url, timeout=15):
            self.calls.append(url)
            raise OSError('timed out')
        self.app.fetch_json = broken
        self.assertEqual(self.get('cell=32,-86')['status'], 502)
        self.assertEqual(self.get('cell=32,-86')['status'], 502)
        self.assertEqual(len(self.calls), 2)
        self.app.fetch_json = lambda url, timeout=15: {'unexpected': True}
        self.assertEqual(self.get('cell=32,-86')['status'], 502)

    def test_overlay_script_is_private_and_chart_tiles_allowed(self):
        env = {'PATH_INFO': '/static/airspace.js', 'REQUEST_METHOD': 'GET', 'wsgi.input': io.BytesIO(b''), 'CONTENT_LENGTH': '0'}
        result = {}
        b''.join(self.app(env, lambda status, headers: result.update(status=int(status.split()[0]), headers=dict(headers))))
        self.assertEqual(result['status'], 303)
        self.assertIn('https://tiles.arcgis.com', result['headers']['Content-Security-Policy'])
        self.assertNotIn('arcgis', result['headers']['Content-Security-Policy'].split('connect-src')[1].split(';')[0])

    def test_clean_airspace_rejects_non_geojson(self):
        for bad in [None, [], {'features': 'x'}]:
            with self.assertRaises(ValueError):
                clean_airspace(bad)


if __name__ == '__main__':
    unittest.main()
