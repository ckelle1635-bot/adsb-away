# Home Airspace

A personal, password-protected ADS-B map for your Raspberry Pi feed. The Pi uploads snapshots to Render over HTTPS. No inbound router port, VPN, database, or receiver administration proxy is required.

## Render deployment

Create a **Python web service**, one instance, from this repository.

- Build: `pip install -r requirements.txt`
- Start: `gunicorn 'app:create_app()' --bind 0.0.0.0:$PORT --workers 1 --threads 4 --timeout 30 --access-logfile /dev/null`
- Optional HTTP health check: `/healthz`
- `PUBLIC_URL`: the actual Render HTTPS origin, for example `https://your-service.onrender.com` (no trailing path)
- `VIEWER_PASSWORD_HASH`: generated below
- `UPLOAD_TOKEN`: generated below

Run `python configure.py` on a trusted computer. Choose a unique password of at least 20 characters and store it in a password manager. Copy the generated hash and upload token directly into Render's environment settings; do not commit or paste them into chat. Deploy after saving. Leave `LOCAL_DEV` unset in production.

Keep one Gunicorn worker and one Render instance: the latest snapshot, rate limiter, and session revocations are held in memory. Restarts clear the snapshot and sign everyone out. No aircraft history is retained. A free Render service may have cold starts and usage limits; continuous five-second uploads keep it active and consume runtime. Check your account's allowance; choose a paid plan if dependable continuous availability is needed.

## Install the uploader on the Pi

Copy `pi/uploader.py` and `pi/adsb-away.service` to the Pi, then run:

```sh
sudo install -d -m 755 /opt/adsb-away
sudo install -m 644 uploader.py /opt/adsb-away/uploader.py
sudo install -m 644 adsb-away.service /etc/systemd/system/adsb-away.service
sudo install -m 600 /dev/null /etc/adsb-away.env
sudo nano /etc/adsb-away.env
```

Enter these three lines in the root-only file (replace the two placeholders):

```ini
APP_URL=https://YOUR-SERVICE.onrender.com
UPLOAD_TOKEN=YOUR_UPLOAD_TOKEN_FROM_RENDER
FEED_URL=http://127.0.0.1:8080/data/aircraft.json
```

If the feeder does not listen on loopback, use `http://adsb-feeder.local:8080/data/aircraft.json`, the endpoint confirmed for your setup. Keep the Pi clock synchronized. Then:

```sh
sudo systemctl daemon-reload
sudo systemctl enable --now adsb-away
sudo systemctl status adsb-away
sudo journalctl -u adsb-away -n 20 --no-pager
```

Open the Render URL and sign in. Within a few seconds it should say **Receiver live**. On mobile, save the page to your home screen. To stop uploading: `sudo systemctl disable --now adsb-away`.

## Security and privacy

- TLS is required for the Render origin. Upload redirects are rejected, so credentials cannot be forwarded to another endpoint.
- The upload token authorizes writes only. It does not unlock the viewer. The viewer password cannot upload snapshots.
- Passwords use PBKDF2-SHA256 with 600,000 rounds and random salts. Sessions are HMAC signed, expire after 12 hours, and use Secure, HttpOnly, SameSite=Strict cookies. Logout revokes the session until expiry.
- Login accepts at most ten attempts across all clients per ten minutes, including successful attempts. This intentionally avoids trusting spoofable forwarding headers, but someone can temporarily prevent sign-in by exhausting the shared limit. Existing sessions keep working. For broader exposure, put managed identity/MFA and edge rate limiting in front of the app.
- Login and logout require the exact configured browser Origin. No cross-origin API access is enabled. Aircraft strings enter the DOM only through text nodes.
- Requests are size limited; snapshots must have recent timestamps. After 30 seconds without fresh source data, the app clears aircraft and marks the feed offline. Individual positions older than 60 seconds are omitted from the map.
- Only selected aircraft fields are retained. Receiver coordinates/settings and arbitrary metadata are dropped. The initial map center is a broad regional default, not a stored receiver position.
- Leaflet 1.9.4 is served locally with its license. The basemap uses OpenStreetMap tiles: the tile provider sees the viewer's IP address and requested map area, but does not receive aircraft JSON or app credentials. This is a personal low-volume viewer, not a bulk tile client.
- Rotate the upload token in Render and `/etc/adsb-away.env` if exposed. Restart the uploader after changing it. To change the viewer password, generate a new hash with `configure.py`, update Render, and deploy; a deploy invalidates existing sessions. Ignore the newly generated upload token if you intend to retain your current one.

## Verify

`python -m unittest discover -s tests -v`

Local tests cover auth boundaries, cookie flags, CSRF, expired/forged/revoked sessions, login throttling, stale/out-of-order data, input limits, and protected paths. The production server is Gunicorn; the Python development server is not for Internet deployment.

This viewer is for personal situational awareness, not flight navigation or separation.
