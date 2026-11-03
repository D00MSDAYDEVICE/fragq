# Moving from PUBobot2

FragQ uses PUBobot2's database schema unchanged and reads the same channel and queue configs, so a
PUBobot2 community can switch without losing ratings, matches or settings. FragQ adds its own tables
(`fragq_steam_links`, `fragq_web_access` and bot settings) next to PUBobot2's; it doesn't change the
existing ones.

!!! warning "One bot per database"
    Don't run PUBobot2 and FragQ against the same database at the same time. Stop PUBobot2 first.

## Option 1: point FragQ at the existing database

Set `DB_URI` in `.env` to the PUBobot2 database:

```ini
DB_URI=mysql://pubobot:password@192.168.1.20:3306/pubodb
```

The bundled MariaDB container still starts but isn't used. The database server must accept connections
from the Docker host.

## Option 2: copy the data into the bundled MariaDB

```bash
mysqldump -u pubobot -p pubodb > backups/pubodb.sql
docker compose up -d db
docker compose exec db sh -c 'mariadb -u root -p"$MARIADB_ROOT_PASSWORD" "$MARIADB_DATABASE" < /backups/pubodb.sql'
docker compose up -d
```

The `backups/` folder is mounted into the database container as `/backups`.

## Using your existing bot

To keep the same bot account, use its token, client id and secret in `.env`, and add FragQ's
`PUBLIC_URL/auth/callback` to the OAuth2 redirects. FragQ also reads PUBobot2's old variable names such
as `DC_BOT_TOKEN`; see [Legacy names](env.md#legacy-names).

## Configs from the old web interface

Channel and queue configs exported from PUBobot2's web interface (*import/export cfg*) can be pasted
into **Import / export → Import** on any channel or queue. See [Import and export](../web-panel/import-export.md).

## What's different for players

Nothing they have to learn: every PUBobot2 command still works. They get the
[queue panel](../queue-panel/panel.md) buttons, the new [match start message](../queue-panel/match-message.md)
(switch back with *Match start message* → `classic`) and, if you turn it on,
[Steam linking](../playing/steam.md).
