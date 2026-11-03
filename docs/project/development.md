# Development

## Repository layout

```text
├── deployfragq.sh            Linux installer (writes .env, starts Docker)
├── deployfragq.ps1           Windows installer (Docker Desktop)
├── docker-compose.yml        MariaDB, the app and Caddy (TLS)
├── .env.example              all settings, documented
├── caddy/entrypoint.sh       builds the Caddyfile from TLS_MODE / SITE_HOST / ports
├── certs/                    your own cert.pem + key.pem for TLS_MODE=custom
├── backups/                  mounted into the database container as /backups
├── docs/  mkdocs.yml         this documentation site
├── app/
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── FragQ.py              entry point: the bot and the web server in one asyncio loop
│   ├── core/                 config (env vars), database adapter, console/log, cfg factory
│   ├── bot/                  the PUBobot2 bot: queues, matches, ratings, commands
│   │   ├── panel.py          the Discord queue panel and its buttons
│   │   ├── avatars.py        the avatar row image and its cache
│   │   ├── steam.py          Steam lookups, links and the join prompt
│   │   └── settings.py       bot-wide settings (Steam key, Require Linked Steam IDs)
│   ├── webui/                aiohttp web server, Discord OAuth, JSON API, static front-end
│   │   ├── access.py         web panel permissions (the Users page)
│   │   └── schema.py         bridges the bot's config variables and the web editor
│   ├── locales/              translations (compiled into the image)
│   └── dev/                  the demo (fake Discord) and the settings reference generator
└── .github/workflows/        the documentation site
```

The web panel runs in the bot's process. Every change goes through the same `Config.update()` path as
the `!set_channel_cfg` / `/channel set` chat commands, so validation and live updates behave exactly as
in chat.

## Run the demo

`app/dev/demo.py` runs the real bot and web modules against a fake Discord server, with seeded
channels, queues, players and matches. No bot token is needed:

```bash
cd app
pip install -r requirements.txt          # Python 3.13+: also pip install audioop-lts
DB_URI=sqlite://demo.db python dev/demo.py
```

| Address | What |
|---|---|
| <http://127.0.0.1:8000/dev-login> | Sign in to the web panel as the bot owner |
| `/dev-login?as=<name>` | Sign in as another fake member, to try limited access |
| <http://127.0.0.1:8000/dev/discord> | A fake Discord channel: press panel buttons and type commands as any member |

The SQLite adapter is for the demo only. To try against MariaDB instead:
`DB_URI=mysql://fragq:fragq@127.0.0.1:3307/fragq python dev/demo.py`.

## Build the image

```bash
docker compose build app
```

## Documentation

The site is built with [MkDocs](https://www.mkdocs.org/) and
[Material for MkDocs](https://squidfunk.github.io/mkdocs-material/), and published to GitHub Pages by
`.github/workflows/docs.yml` on every push to `main` that changes `docs/`, `mkdocs.yml` or
`CHANGELOG.md`.

```bash
pip install "mkdocs==1.6.1" "mkdocs-material==9.7.6"
mkdocs serve            # http://127.0.0.1:8000, reloads on save
mkdocs build --strict   # what the workflow runs; fails on broken links
```

`mkdocs serve` uses port 8000 like the demo; add `-a 127.0.0.1:8001` to run both.

The [Channel settings](../reference/channel-settings.md) and [Queue settings](../reference/queue-settings.md)
pages are generated from the bot's own variable definitions. After changing a setting's name,
description or default, start the demo and regenerate them:

```bash
cd app && python dev/gen_settings_docs.py
```

One-time setup for publishing: in the GitHub repository, **Settings → Pages → Build and deployment →
Source: GitHub Actions**.
