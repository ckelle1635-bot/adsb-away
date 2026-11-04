# Access-code front door for God's Eye View

God's Eye View brokers your API keys (OpenAI, Google and others) to anyone who can reach it, and its own documentation asks for a separate authentication proxy in front of any shared instance. This folder is that proxy: a small [Caddy](https://caddyserver.com) server that asks for an access code before passing anything to the app.

```
friend's browser ──HTTPS──▶ front door (public Render web service, this folder)
                              │  sign-in box: user "guest" + access code
                              ▼  Render private network only
                            God's Eye View (Render private service, no public address)
```

Friends see the browser's own sign-in box once per browser session. They type `guest` and the code. Nothing reaches the app until the code is right; the app never sees the code.

## Settings (Render environment variables)

| Service | Variable | Value |
| --- | --- | --- |
| Front door | `UPSTREAM` | The private service's internal address, e.g. `chucks-gev-private:4173` (Render shows it under the service's **Connect → Internal**). |
| Front door | `GATE_CODE` | The access code, at least 12 characters. |
| Front door | `GATE_USER` | Optional sign-in name; defaults to `guest`. |
| God's Eye View | `GEV_ALLOWED_HOSTS` | The front door's hostname, e.g. `chucks-gev.onrender.com`. The app rejects other Host names. |
| God's Eye View | `GEV_KEY_SETUP_TRUSTED_PEERS` | `none`, so no visitor can reach the key-entry panel. |
| God's Eye View | your API keys | As before. Provider Settings refuses proxied requests, so keys must be set here. |

The front door refuses to start if `UPSTREAM` or `GATE_CODE` is missing or the code is too short, so the app is never exposed by a half-finished setup. The Docker build also validates the Caddy configuration.

## Setting it up on Render

1. **Create the private app.** Dashboard → **New → Private Service** → **Public Git Repository** `https://github.com/bilawalsidhu/gods-eye-view`. Name `chucks-gev-private`, region **Virginia** (same as the front door), language **Docker**, the same instance type as the old service. Copy every environment variable from the old service, then add `GEV_ALLOWED_HOSTS` and `GEV_KEY_SETUP_TRUSTED_PEERS` from the table above. Create it and wait for **Live**.
2. **Create the front door.** New **Web Service** from this repository: root/build context `gatekeeper`, Dockerfile `gatekeeper/Dockerfile`, region **Virginia**, health check path `/gatekeeper-health`. Set `UPSTREAM` and `GATE_CODE`. The Free plan works (it sleeps when idle and takes a few seconds to wake); Starter keeps it awake.
3. **Test.** Open the front door's address: a sign-in box should appear. A wrong code must be refused; `guest` plus the right code shows the app.
4. **Delete the old public service** (Settings → Delete Web Service), otherwise its address stays open without a code.

## Day to day

- **Change the code:** edit `GATE_CODE` on the front door and save; Render restarts it in about a minute. Everyone needs the new code.
- **Remove someone's access:** change the code and send it to everyone else. There is one shared code, not per-person accounts.
- **Spending:** keep provider spending limits and billing alerts on. The code keeps strangers out; it does not cap what signed-in friends use.
- **Updates to God's Eye View:** the private service deploys from the original project. Use **Manual Deploy** on it to pick up their changes.
