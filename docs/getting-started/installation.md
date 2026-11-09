# Installation

FragQ runs in Docker. An interactive installer sets everything up: it asks for the Discord values and
the address of the web panel, generates the database passwords and session secret, writes the `.env`
settings file and starts the containers.

## Requirements

| | Linux | Windows |
|---|---|---|
| Docker | Docker Engine with the **Compose plugin** (`docker compose`) | **Docker Desktop**, running (WSL 2 backend recommended) |
| Ports | 80 and 443 free, or any other two ports you choose | same |
| Internet | The containers must reach Discord, PyPI (to build the image), Let's Encrypt and Steam | same |
| Resources | Modest: 1 CPU and 1 GB of RAM are plenty for a busy community | same |
| Discord | A Discord application with a bot; see [Discord application](discord-app.md) | same |

!!! tip "Domain or IP?"
    A domain name is nicest, but not required. With `TLS_MODE=auto` FragQ gets a Let's Encrypt
    certificate for a **bare public IP** too, and falls back to a self-signed certificate on a LAN. See
    [HTTPS and ports](../administration/https.md).

## Install with the installer

=== "Linux"

    ```bash
    git clone https://github.com/D00MSDAYDEVICE/fragq.git && cd fragq
    ./deployfragq.sh
    ```

=== "Windows"

    Start Docker Desktop first, then in PowerShell:

    ```powershell
    git clone https://github.com/D00MSDAYDEVICE/fragq.git; cd fragq
    powershell -ExecutionPolicy Bypass -File .\deployfragq.ps1
    ```

No git? Download the repository as a `.zip` from GitHub (**Code → Download ZIP**), extract it and run
the installer from that folder.

The installer asks:

| Question | Default | Notes |
|---|---|---|
| Bot token | none | From the **Bot** tab. Typed input is hidden. |
| Client id / Client secret | none | From the **OAuth2** tab. |
| Your Discord user id | empty | Optional, but without it nobody gets the owner-only **Bot status** and **Settings** pages. |
| Domain or IP | your LAN IP | What people type in the browser. Several, comma separated, are allowed. |
| HTTP port / HTTPS port | `80` / `443` | Any free ports work. |
| TLS mode | `auto` | `auto`, `internal`, `custom` or `off`. See [HTTPS and ports](../administration/https.md). |
| E-mail for Let's Encrypt | empty | Optional, only asked for `auto`. |
| Public address of the web interface | built from the above | For example `https://fragq.example.com` or `https://192.168.1.50:8443`. |

Then it writes `.env` (on Linux with permissions `600`), runs `docker compose up -d --build` and
prints the address:

```text
  FragQ is starting at:  https://fragq.example.com

  One more step in the Discord developer portal (OAuth2 tab > Redirects), add:
      https://fragq.example.com/auth/callback
```

Add that redirect in the developer portal, as described in
[Discord application](discord-app.md#oauth2-tab).

If `.env` already exists, the installer asks before overwriting it. Answer **N** to keep your settings
and just rebuild and restart, which is also how you [update](../administration/updating.md).

## Install by hand

```bash
cp .env.example .env      # then fill in the Discord values, SITE_HOST, PUBLIC_URL and the MYSQL_ passwords
docker compose up -d --build
```

Every setting is documented in `.env.example` and in the [.env reference](../administration/env.md).
`MYSQL_PASSWORD` and `MYSQL_ROOT_PASSWORD` must be set; Compose refuses to start without them.

## Check that it is running

```bash
docker compose ps            # db, app and caddy should be running (db "healthy")
docker compose logs -f app   # the bot: "FragQ v1.1.0 starting.", then the Discord connection
```

Open `PUBLIC_URL` in a browser. With a self-signed certificate your browser warns once; that is
expected on a LAN or without a public address.

## Uninstall

```bash
docker compose down        # stops and removes the containers; keeps your data
docker compose down -v     # also DELETES the database, the avatar cache and the certificates
```

!!! danger
    `docker compose down -v` and `docker volume prune` delete the database volume.
    [Make a backup](../administration/backup-restore.md) first.

Next: [First channel and queue](first-steps.md).
