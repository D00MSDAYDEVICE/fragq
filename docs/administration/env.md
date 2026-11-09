# .env reference

FragQ is configured with the `.env` file in its folder. The installer writes it; `.env.example`
documents every setting. After changing it, run:

```bash
docker compose up -d
```

!!! warning "Keep `.env` private"
    It holds the bot token, the client secret and the database passwords. The Linux installer gives it
    permissions `600`.

## Discord

| Variable | Default | Purpose |
|---|---|---|
| `DISCORD_BOT_TOKEN` | required | The bot's token (developer portal → **Bot**) |
| `DISCORD_CLIENT_ID` | required | The application's client id (→ **OAuth2**), for the web login and the invite link |
| `DISCORD_CLIENT_SECRET` | required | The client secret (→ **OAuth2**), for the web login |
| `DISCORD_OWNER_ID` | empty | Your Discord user id: full access everywhere, plus **Bot status** and **Settings** |
| `DISCORD_SLASH_SERVERS` | empty | Register slash commands only on these server ids (comma separated). They appear instantly there; global commands can take up to an hour. |
| `DISCORD_INVITE_LINK` | built from the client id | Override the **Invite bot** link |
| `BOT_STATUS` | `pickup games` | Shown as the bot's *Watching …* status |
| `BOT_HELP` | a short text with the web panel address | What the bot answers to direct messages |
| `COMMANDS_URL` | the [Commands](../reference/commands.md) page of this documentation | Where the **Commands** link in the web panel and `/commands` point |

## Web panel and HTTPS

| Variable | Default | Purpose |
|---|---|---|
| `SITE_HOST` | empty (`localhost`) | Domain name(s) or IP address(es) of the web panel, comma separated |
| `PUBLIC_URL` | empty | The full address, such as `https://fragq.example.com` or `https://192.168.1.50:8443`. `PUBLIC_URL/auth/callback` must be a redirect in the developer portal. The [`/verify` page](steam.md#the-verify-page) needs it too. |
| `HTTP_PORT` / `HTTPS_PORT` | `80` / `443` | Ports published on the host |
| `TLS_MODE` | `auto` | `auto`, `internal`, `custom` or `off`; see [HTTPS and ports](https.md) |
| `ACME_EMAIL` | empty | E-mail for Let's Encrypt notices |
| `TRUSTED_PROXIES` | empty | With `TLS_MODE=off` behind another proxy: its IP or range, or `private_ranges` |
| `SESSION_SECRET` | generated | Signs login cookies. Empty: generated once and kept in the data volume. Changing it signs everybody out. |
| `SESSION_DAYS` | `7` | How long a login lasts |
| `OAUTH_REDIRECT_URL` | `PUBLIC_URL/auth/callback` | Only if the login redirect must differ from `PUBLIC_URL` |

## Database

| Variable | Default | Purpose |
|---|---|---|
| `MYSQL_DATABASE` / `MYSQL_USER` | `fragq` / `fragq` | The bundled MariaDB database and user |
| `MYSQL_PASSWORD` / `MYSQL_ROOT_PASSWORD` | required | Their passwords; the installer generates them. Set them before the first start: MariaDB only reads them when it creates the database. |
| `DB_URI` | empty | Use an external MySQL or MariaDB instead, such as an existing PUBobot2 database: `mysql://user:password@host:3306/pubodb`. See [Moving from PUBobot2](pubobot2.md). |

## Logging

| Variable | Default | Purpose |
|---|---|---|
| `LOG_LEVEL` | `INFO` | `CHAT`, `DEBUG`, `COMMANDS`, `INFO` or `ERRORS`, from most to least detail |

## Set by docker-compose.yml

These are set for you and normally left alone: `DATA_DIR=/data` (saved queue state, logs, the session
key and the avatar cache), `MYSQL_HOST=db`, `WEB_PORT=8000`.

## Legacy names

FragQ also reads PUBobot2's old names, so an existing PUBobot2 setup can be reused: `DC_BOT_TOKEN`,
`DC_CLIENT_ID`, `DC_CLIENT_SECRET`, `DC_OWNER_ID`, `DC_SLASH_SERVERS`, `DC_INVITE_LINK`, `WS_ROOT_URL`
(for `PUBLIC_URL`), `WS_OAUTH_REDIRECT_URL`, `STATUS`, `HELP`.
