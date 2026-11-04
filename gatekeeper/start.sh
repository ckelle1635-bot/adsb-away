#!/bin/sh
# Turns the plain access code from Render's settings into a bcrypt hash, then
# starts Caddy. Refuses to start if anything is missing, so the app is never
# reachable without the code.
set -eu

if [ -z "${UPSTREAM:-}" ]; then
	echo "gatekeeper: set UPSTREAM to the private service address, e.g. chucks-gev-private:4173" >&2
	exit 1
fi
GATE_CODE="${GATE_CODE:-}"
if [ "${#GATE_CODE}" -lt 12 ]; then
	echo "gatekeeper: set GATE_CODE to an access code of at least 12 characters" >&2
	exit 1
fi

GATE_HASH="$(/usr/local/bin/caddy hash-password --plaintext "$GATE_CODE")"
export GATE_HASH
unset GATE_CODE

exec /usr/local/bin/caddy run --config /etc/caddy/Caddyfile --adapter caddyfile
