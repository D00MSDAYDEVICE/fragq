# HTTPS and ports

FragQ runs behind [Caddy](https://caddyserver.com/), which obtains and renews certificates by itself. Choose the behaviour with `TLS_MODE` in `.env`.

| `TLS_MODE` | What happens |
|---|---|
| `auto` (default) | **Domain** → Let's Encrypt certificate. **Public IP** → Let's Encrypt IP-address certificate (6-day *shortlived* profile, renewed automatically). **Private IP or LAN name** → self-signed. If Let's Encrypt fails for any reason, FragQ falls back to self-signed and keeps retrying in the background. |
| `internal` | Always self-signed (Caddy's local certificate authority). Browsers warn once. |
| `custom` | Your own certificate: `certs/cert.pem` and `certs/key.pem` in the FragQ folder. |
| `off` | Plain HTTP on `HTTP_PORT`, for when another reverse proxy in front of FragQ already handles TLS. |

## Ports

`HTTP_PORT` and `HTTPS_PORT` can be any free ports, for example `8080` and `8443` on a machine that already runs a web server. HTTP requests are redirected to HTTPS on the right port. The URL then includes the port: `https://fragq.example.com:8443`.

!!! warning "Let's Encrypt needs port 80 or 443"
    Let's Encrypt validates through **public port 80 or 443**. If you use other ports, forward public 80 → `HTTP_PORT` or 443 → `HTTPS_PORT` on your router or firewall. Otherwise `auto` mode ends up with the self-signed fallback.

## Several names

`SITE_HOST` can list several names or addresses, comma separated, for example a public IP and a LAN IP:

```ini
SITE_HOST=203.0.113.10,192.168.1.50
```

Each gets its own certificate: Let's Encrypt for the public one, self-signed for the private one.

## Trust the self-signed certificate

With `internal`, or the self-signed fallback, browsers warn until you trust Caddy's root certificate. Copy it out of the container:

```bash
docker compose cp caddy:/data/caddy/pki/authorities/local/root.crt ./fragq-root.crt
```

Then install `fragq-root.crt` as a trusted root certificate on each PC: on Windows double-click it → **Install Certificate → Local Machine → Trusted Root Certification Authorities**; on macOS add it to the System keychain and set it to *Always Trust*.

## Behind another proxy

If FragQ sits behind an existing reverse proxy (nginx, Traefik, a Cloudflare tunnel) that already does TLS, set `TLS_MODE=off` and point the proxy at `http://<host>:<HTTP_PORT>`. Make sure the proxy itself is only reachable over HTTPS, and set `TRUSTED_PROXIES` to the proxy's address so Caddy trusts its forwarded headers (see the [.env reference](env.md#web-panel-and-https)). `PUBLIC_URL` stays the address people use, the proxy's `https://` one.
