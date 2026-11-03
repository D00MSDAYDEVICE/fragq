#!/usr/bin/env bash
# Interactive first-time setup: writes .env and starts the containers.
set -euo pipefail
cd "$(dirname "$0")"

command -v docker >/dev/null || { echo "Docker is not installed."; exit 1; }
docker compose version >/dev/null 2>&1 || { echo "The Docker Compose plugin (docker compose) is required."; exit 1; }

start_stack() {
  mkdir -p certs backups
  docker compose up -d --build
}

if [ -f .env ]; then
  read -r -p ".env already exists. Overwrite it? [y/N] " yn
  [[ "$yn" =~ ^[Yy] ]] || { echo "Keeping existing .env. Starting..."; start_stack; exit 0; }
fi

ask() { # ask VAR "Prompt" default
  local __v; read -r -p "$2 [$3]: " __v; printf -v "$1" '%s' "${__v:-$3}"
}
ask_secret() { # ask_secret VAR "Prompt"  (input hidden, required)
  local __v=""
  while [ -z "$__v" ]; do read -r -s -p "$2: " __v; echo; done
  printf -v "$1" '%s' "$__v"
}
random() { LC_ALL=C tr -dc 'A-Za-z0-9' </dev/urandom | head -c "$1" || true; }

echo
echo "Discord application - create one at https://discord.com/developers/applications"
echo "  Bot tab:    copy the token and enable the Presence, Server Members and"
echo "              Message Content privileged intents."
echo "  OAuth2 tab: copy the client id and client secret."
ask_secret DISCORD_BOT_TOKEN "Bot token"
ask DISCORD_CLIENT_ID "Client id" ""
ask_secret DISCORD_CLIENT_SECRET "Client secret"
ask DISCORD_OWNER_ID "Your Discord user id (bot owner, optional)" ""

lan_ip="$(hostname -I 2>/dev/null | awk '{print $1}')"
echo
echo "How will people reach the web interface? Enter a domain name (fragq.example.com),"
echo "or your server's public IP if you don't have a domain."
echo "Your LAN IP looks like: ${lan_ip:-unknown}"
ask SITE_HOST "Domain or IP" "${lan_ip:-localhost}"
ask HTTP_PORT "HTTP port" "80"
ask HTTPS_PORT "HTTPS port" "443"
echo
echo "TLS modes: auto (Let's Encrypt with self-signed fallback), internal (self-signed),"
echo "           custom (your own ./certs/cert.pem + key.pem), off (plain HTTP)"
ask TLS_MODE "TLS mode" "auto"
ACME_EMAIL=""
if [ "$TLS_MODE" = "auto" ]; then ask ACME_EMAIL "E-mail for Let's Encrypt notices (optional)" ""; fi

first_host="${SITE_HOST%%,*}"
if [ "$TLS_MODE" = "off" ]; then
  PUBLIC_URL="http://${first_host}"; [ "$HTTP_PORT" = "80" ] || PUBLIC_URL="${PUBLIC_URL}:${HTTP_PORT}"
else
  PUBLIC_URL="https://${first_host}"; [ "$HTTPS_PORT" = "443" ] || PUBLIC_URL="${PUBLIC_URL}:${HTTPS_PORT}"
fi
ask PUBLIC_URL "Public address of the web interface" "$PUBLIC_URL"
PUBLIC_URL="${PUBLIC_URL%/}"

sed -e "s|^DISCORD_BOT_TOKEN=.*|DISCORD_BOT_TOKEN=${DISCORD_BOT_TOKEN}|" \
    -e "s|^DISCORD_CLIENT_ID=.*|DISCORD_CLIENT_ID=${DISCORD_CLIENT_ID}|" \
    -e "s|^DISCORD_CLIENT_SECRET=.*|DISCORD_CLIENT_SECRET=${DISCORD_CLIENT_SECRET}|" \
    -e "s|^DISCORD_OWNER_ID=.*|DISCORD_OWNER_ID=${DISCORD_OWNER_ID}|" \
    -e "s|^SITE_HOST=.*|SITE_HOST=${SITE_HOST}|" \
    -e "s|^PUBLIC_URL=.*|PUBLIC_URL=${PUBLIC_URL}|" \
    -e "s|^HTTP_PORT=.*|HTTP_PORT=${HTTP_PORT}|" \
    -e "s|^HTTPS_PORT=.*|HTTPS_PORT=${HTTPS_PORT}|" \
    -e "s|^TLS_MODE=.*|TLS_MODE=${TLS_MODE}|" \
    -e "s|^ACME_EMAIL=.*|ACME_EMAIL=${ACME_EMAIL}|" \
    -e "s|^SESSION_SECRET=.*|SESSION_SECRET=$(random 48)|" \
    -e "s|^MYSQL_PASSWORD=.*|MYSQL_PASSWORD=$(random 32)|" \
    -e "s|^MYSQL_ROOT_PASSWORD=.*|MYSQL_ROOT_PASSWORD=$(random 32)|" \
    .env.example > .env
chmod 600 .env

start_stack

cat <<EOF

  FragQ is starting at:  ${PUBLIC_URL}

  One more step in the Discord developer portal (OAuth2 tab > Redirects), add:
      ${PUBLIC_URL}/auth/callback

  Then invite the bot from the web interface and enable it on a channel.
  If the certificate is self-signed your browser will warn once.
  Logs:  docker compose logs -f app
EOF
