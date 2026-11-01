#!/usr/bin/env python3
"""Outbound-only uploader; Python standard library, no pip dependencies."""
import json
import os
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None  # Never forward an upload credential to another URL.


def main():
    source = os.environ.get('FEED_URL', 'http://127.0.0.1:8080/data/aircraft.json')
    target = os.environ.get('APP_URL', '').rstrip('/')
    parts = urlsplit(target)
    if parts.scheme != 'https' or not parts.netloc or parts.path or parts.query or parts.fragment or parts.username:
        raise SystemExit('APP_URL must be an HTTPS origin, without a path')
    token = os.environ.get('UPLOAD_TOKEN', '')
    if len(token) < 40:
        raise SystemExit('Set UPLOAD_TOKEN to the credential generated for Render')
    opener = build_opener(NoRedirect())
    backoff = 5
    while True:
        try:
            with opener.open(source, timeout=10) as response:
                body = response.read(2_000_001)
            if len(body) > 2_000_000:
                raise ValueError('Snapshot too large')
            data = json.loads(body)
            if not isinstance(data, dict) or not isinstance(data.get('aircraft'), list):
                raise ValueError('Not an aircraft snapshot')
            if abs(time.time() - float(data.get('now', 0))) > 120:
                raise ValueError('Receiver data is stale; check Pi clock and decoder')
            request = Request(target + '/api/ingest', body, {'Content-Type': 'application/json', 'Authorization': 'Bearer ' + token}, method='POST')
            with opener.open(request, timeout=30) as response:
                response.read(1024)
            backoff = 5
        except HTTPError as error:
            print(f'HTTP {error.code}; upload unsuccessful; retrying in {backoff}s', flush=True)
            backoff = min(backoff * 2, 60)
        except (URLError, TimeoutError, OSError, ValueError, TypeError):
            # Do not log URLs, credentials, or aircraft payloads.
            print(f'Feed unavailable or invalid; retrying in {backoff}s', flush=True)
            backoff = min(backoff * 2, 60)
        time.sleep(backoff)


if __name__ == '__main__':
    main()
