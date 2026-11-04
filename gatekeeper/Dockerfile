# Access-code front door (Caddy). Built by Render from the gatekeeper/ folder.
# The 2.11 tag follows Caddy's patch releases, so a rebuild picks up security fixes.
FROM caddy:2.11-alpine

# The image's /usr/bin/caddy carries a file capability (to bind ports below 1024).
# Render refuses to run binaries with file capabilities ("Operation not permitted"),
# and we listen on $PORT (10000), so use a plain copy, which drops the capability.
# /usr/local/bin comes first in PATH, so "caddy" below resolves to this copy.
RUN install -m 755 /usr/bin/caddy /usr/local/bin/caddy

COPY Caddyfile /etc/caddy/Caddyfile
COPY start.sh /usr/local/bin/gatekeeper-start
# Fail the build if the Caddyfile is invalid (checked with throwaway values).
RUN chmod 755 /usr/local/bin/gatekeeper-start \
	&& GATE_HASH="$(caddy hash-password --plaintext build-check-only)" UPSTREAM=127.0.0.1:9 \
	   caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile

CMD ["/usr/local/bin/gatekeeper-start"]
