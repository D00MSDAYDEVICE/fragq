# FragQ

**FragQ** is a self-hosted Discord pickup-game bot with a web control panel. It is a fork of
[PUBobot2](https://github.com/Leshaka/PUBobot2) by Leshaka: same commands, queues, drafts,
ratings (TrueSkill / Glicko2 / flat), rank roles and map votes. The difference is that FragQ
includes its own web interface and ships as a Docker Compose stack.

**Documentation: <https://d00msdaydevice.github.io/fragq/>**

- **Web panel:** Discord login, then a server rail, a channel and queue tree, and a tabbed
  settings editor for every channel and queue variable. It is styled after Fragdex.
- **Import / export:** JSON `.cfg` files. These are compatible with configs exported from the
  original PUBobot2 web interface.
- **Live view:** shows filling queues and matches in progress for each channel and each server.
- **Leaderboard and match history:** browse them in the browser or download them as CSV.
- **Queue panel with buttons:** a Discord message with a **Join** button per queue and a **Leave**
  button. It updates live and moves below each new match message. Post it with `!panel`,
  `/channel panel`, or **Post queue panel** in the web interface; remove it with `!panel off`.
  Button replies are private, so the channel stays clean. `!add`, `++` and `/add` still work.
- **Moderator buttons on the panel:** two icon buttons next to **Leave**. 👤 (Add Player) opens a
  private picker (queue, then up to 25 members) and works even while the queue is paused. ⏸️ pauses
  the channel (Join, `!add`, `++` and `/add` stop working) and turns into a blue ▶️ that resumes it;
  the pause survives restarts and can also be toggled on the channel page in the web interface.
  Discord buttons can't show hover tooltips, so the panel footer explains the icons. The buttons are
  visible to everyone but only work for the channel's moderator and admin roles. Hide them with
  Channel settings > **Messages** > *Moderator buttons on queue panel*.
- **Steam integration (web interface > Settings):** turn on **Require Linked Steam IDs** and players
  without a link are asked for their Steam ID the first time they join: a pop-up form from Join or
  `/add`, or a **Link Steam** button for `!add` / `++`. After linking, the join goes through. They
  can also link or change it with `!steam <id or link>` or `/steam`. SteamID64s,
  `steamcommunity.com/profiles/...` and `/id/...` links, custom names, `STEAM_0:X:Y` and `[U:1:N]`
  all work. A Steam Web API key is optional: without one FragQ reads public Steam profiles, which is
  slower and rate limited. One Steam account can only be linked to one Discord member. Changing a
  linked account waits for a moderator's or admin's **Approve** on the Settings page. Links are
  stored in the database (`fragq_steam_links`), and the Settings page lists them with an **Unlink**
  button. Moderators can still add unlinked players.
- **Settings page:** **Auto-repost queue panels** moves panels that chat has buried back to the
  bottom every few minutes (5 by default). **Backup and restore** saves all FragQ settings (channels,
  queues, Steam links, web panel access) to one file and restores them on a fresh install.
- **Player avatars on the queue panel:** a row of profile pictures per queue, with empty slots for
  open places, right above the buttons; queues over 8 players get another row of 8. Linked players
  show their Steam avatar, others their Discord avatar. Pictures are cached in the data volume
  (`/data/avatars`).
- **New match-start message:** teams side by side with ranks and ratings, numbered maps, and the
  server list split into headings and copyable addresses. Players are pinged above the embed,
  because mentions inside an embed don't notify anyone. Channel settings > **Messages** switches
  back to the classic PUBobot2 layout.
- **One command deploy:** MariaDB, the bot and Caddy (automatic HTTPS) in Docker.

## Requirements

- Docker with the Compose plugin (Docker Desktop on Windows/macOS, Docker Engine on Linux).
- A Discord application with a bot. Create one at https://discord.com/developers/applications.
  - **Bot** tab: copy the token. Enable the **Presence**, **Server Members** and **Message
    Content** privileged gateway intents.
  - **OAuth2** tab: copy the client id and client secret. Add the redirect
    `https://<your-site>/auth/callback`.

## Install

Linux:

```bash
./deployfragq.sh
```

Windows (Docker Desktop):

```powershell
powershell -ExecutionPolicy Bypass -File .\deployfragq.ps1
```

The script asks for the Discord credentials and the domain or IP of the site. It generates the
database passwords and session secret, writes `.env`, and starts the stack. To configure by
hand instead, copy `.env.example` to `.env`, fill it in, and run `docker compose up -d --build`.

After that:

1. Open the site and sign in with Discord.
2. Use **Invite bot** to add the bot to your server.
3. Pick the server in the left rail, choose **Add channel**, then **Create queue**.

You can also type `!enable_pubobot` in a text channel, as with PUBobot2.

## Who can use the panel

| Who | Access |
| --- | --- |
| `DISCORD_OWNER_ID` | Every server the bot is on, plus the **Bot status** page (uptime, log) and the bot-wide **Settings** page (auto-repost, Require Linked Steam IDs, Steam API key, linked players, backup and restore) |
| Server owner / members with *Administrator* | The whole server: add or remove channels, all settings |
| Members with a channel's **Admin role** | Only the channels where they hold that role |
| Server admins, channel **Admin** and **Moderator** roles | The **Settings** page's Linked players panel, to approve Steam account changes of members of their servers |
| Members or roles given access on the **Users** page | What the grant allows, on the whole server or on chosen channels |

The **Users** page (top bar) lets server admins, and anyone given *Manage users*, give a Discord
member or role access to the web panel. Pick a preset (**Viewer**, **Moderator**, **Manager**,
**Admin**) or tick individual permissions:

| Permission | Allows |
| --- | --- |
| View *(always on)* | See the server, its channels and queues, Live tab, settings (read-only), config export |
| Stats | Leaderboard and Matches tabs, CSV downloads |
| Clear queues | Remove all players from a queue |
| Pause queues | Pause / resume a channel |
| Queue panel | Post, move down and remove the Discord queue panel |
| Edit channel settings | Change, reset and import channel settings |
| Edit queue settings | Change, reset and import queue settings |
| Create / delete queues | Create and delete queues |
| Manage channels | Enable / disable the bot on channels (whole-server grants only) |
| Manage users | Use the Users page, but only to hand out permissions they hold, within their own scope |

Members get the combination of every grant that applies to them (their own and their roles').
Grants are stored in the database (`fragq_web_access`). They only cover the web panel: Discord
commands keep using each channel's Moderator and Admin roles.

## Configuration (`.env`)

| Variable | Purpose |
| --- | --- |
| `DISCORD_BOT_TOKEN`, `DISCORD_CLIENT_ID`, `DISCORD_CLIENT_SECRET` | Discord application |
| `DISCORD_OWNER_ID` | Your user id. Gives full access everywhere. |
| `DISCORD_SLASH_SERVERS` | Register slash commands only on these server ids (faster to update while testing) |
| `SITE_HOST`, `PUBLIC_URL` | Address of the web panel. `PUBLIC_URL/auth/callback` must be listed as an OAuth2 redirect in the developer portal. |
| `HTTP_PORT`, `HTTPS_PORT`, `TLS_MODE`, `ACME_EMAIL`, `TRUSTED_PROXIES` | Caddy / HTTPS. Same options as Fragdex: `auto`, `internal`, `custom`, `off`. |
| `SESSION_SECRET`, `SESSION_DAYS` | Login cookies |
| `MYSQL_*` | The bundled MariaDB |
| `DB_URI` | Use an external MySQL/MariaDB instead, e.g. an existing PUBobot2 database |
| `BOT_STATUS`, `LOG_LEVEL` | Presence text and log verbosity |

After changing `.env`, run `docker compose up -d`.

## Moving from PUBobot2

FragQ uses PUBobot2's database schema unchanged. Pick one of these:

- **Point FragQ at the old database:** set `DB_URI=mysql://user:pass@host:3306/pubodb`.
- **Copy the data into the bundled MariaDB:**

  ```bash
  mysqldump -u pubobot -p pubodb > backups/pubodb.sql
  docker compose up -d db
  docker compose exec db sh -c 'mariadb -u root -p"$MARIADB_ROOT_PASSWORD" "$MARIADB_DATABASE" < /backups/pubodb.sql'
  docker compose up -d
  ```

Channel and queue configs exported from the old web interface (*import/export cfg*) can be
pasted into **Import / export > Import** on any channel or queue.

## Operations

```bash
docker compose logs -f app                       # bot + web log
docker compose restart app                       # restart the bot (queues/matches are saved and restored)
git pull && docker compose up -d --build         # update
docker compose exec db sh -c 'mariadb-dump -u root -p"$MARIADB_ROOT_PASSWORD" "$MARIADB_DATABASE"' > backups/fragq.sql   # backup
```

Persistent data:

| Location | Contents |
| --- | --- |
| `fragq_db_data` | The database: configs, ratings, matches, bot settings, Steam links and web panel access |
| `fragq_fragq_data` | Saved queue/match state, logs, the session key and cached player avatars |
| `fragq_caddy_data` | Certificates |

## Development

`app/dev/demo.py` runs the real bot and web modules against a fake Discord server, with seeded
channels, queues, players and matches. No bot token is needed:

```bash
cd app && pip install -r requirements.txt      # Python 3.13+: also pip install audioop-lts
DB_URI=sqlite://demo.db python dev/demo.py      # SQLite adapter: dev/demo only
# or against MariaDB: DB_URI=mysql://fragq:fragq@127.0.0.1:3307/fragq python dev/demo.py
# open http://127.0.0.1:8000/dev-login
# fake Discord channel view (press panel buttons / type commands as any member): /dev/discord
```

Layout:

```
app/
  FragQ.py          entry point (bot + web server in one asyncio loop)
  core/             config (env vars), database adapter, console/log, cfg factory
  bot/              PUBobot2 bot: queues, matches, ratings, commands
  webui/            aiohttp web server, Discord OAuth, JSON API, static front-end
  locales/          translations (compiled into the image)
caddy/entrypoint.sh builds the Caddyfile from .env
docs/, mkdocs.yml   the documentation site (published by .github/workflows/docs.yml)
```

The web panel runs in the bot's process. Every change goes through the same `Config.update()`
path as the `!set_qc` / `!set_queue` chat commands, so validation and live updates behave
exactly as in chat.

## Credits and license

FragQ is based on [PUBobot2](https://github.com/Leshaka/PUBobot2) © Leshaka, licensed under the
GNU GPL v3. If you enjoy the original bot, consider supporting it on
[Boosty](https://boosty.to/leshaka). FragQ is distributed under the same license; see
[LICENSE](LICENSE).
