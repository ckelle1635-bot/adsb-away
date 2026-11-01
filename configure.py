"""Generate deployment credentials locally. Never commit the output."""
import getpass
import secrets
from app import password_hash

if __name__ == '__main__':
    password = getpass.getpass('Choose viewer password (at least 20 characters): ')
    if len(password) < 20:
        raise SystemExit('Use a unique password with at least 20 characters.')
    if password != getpass.getpass('Confirm password: '):
        raise SystemExit('Passwords differ.')
    print('\nSet these in Render environment settings. Treat both as secrets.\n')
    print('VIEWER_PASSWORD_HASH=' + password_hash(password))
    print('UPLOAD_TOKEN=' + secrets.token_urlsafe(48))
