# Updating

Your data is not in the project folder: the database, the bot's saved state and the certificates live
in Docker volumes (`fragq_db_data`, `fragq_fragq_data`, `fragq_caddy_data`, `fragq_caddy_config`), and
your settings in `.env`. Updating replaces the program and keeps all of that.

The Compose project name is fixed to `fragq`, so the volumes keep their names even if you extract a new
release into a differently named folder.

## Update

=== "With git"

    ```bash
    cd fragq
    git pull
    docker compose pull db caddy && docker compose up -d --build
    ```

=== "From a .zip"

    Extract the new release over the old folder, or into a new folder and copy `.env`, `certs/` and
    `backups/` across. Then, in that folder:

    ```bash
    docker compose pull db caddy && docker compose up -d --build
    ```

=== "With the installer"

    Re-run `./deployfragq.sh` or `deployfragq.ps1` and answer **N** when asked whether to overwrite
    `.env`. It rebuilds and restarts with your existing settings.

Queues and matches in progress are saved when the bot stops and restored when it starts again, so
players stay in their queues. The bot and web panel are unavailable for the few seconds the restart
takes.

!!! danger "Never delete the volumes"
    `docker compose down -v` and `docker volume prune` (while FragQ is stopped) **delete the database**.
    A normal `docker compose down` is safe.

## Slash commands after an update

New or changed slash commands can take up to an hour to appear in Discord, unless
`DISCORD_SLASH_SERVERS` is set.

## Before a big update

Take a backup first. See [Backup and restore](backup-restore.md).
