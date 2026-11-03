# Troubleshooting

Start with the logs. In the FragQ folder:

```bash
docker compose ps              # are db, app and caddy running?
docker compose logs -f app     # the bot and web panel
docker compose logs -f caddy   # HTTPS certificates
docker compose logs db         # the database
```

The bot owner also sees the recent log on the **Bot status** page.

## Build fails: `compile_locales.sh: line 2: $'\r': command not found`

The files were checked out with Windows line endings (CRLF), usually by git on Windows with
`core.autocrlf=true`, or by copying the folder from a Windows PC. Current versions of the Dockerfile
convert the files it needs, so update first. If shell scripts still fail, convert the checkout:

```bash
git config core.autocrlf false
git rm --cached -r . && git reset --hard
```

or, without git, `sed -i 's/\r$//' deployfragq.sh caddy/entrypoint.sh`.

## Build fails: `Temporary failure in name resolution` or `No matching distribution found`

`pip` inside the image build can't resolve `pypi.org`: containers on this host have no working DNS.
Give Docker real DNS servers in `/etc/docker/daemon.json`:

```json
{ "dns": ["1.1.1.1", "8.8.8.8"] }
```

then `sudo systemctl restart docker`. On Docker Desktop, add the same under **Settings → Docker
Engine**. Reloading a firewall after Docker started can also drop Docker's network rules; restarting
Docker fixes that.

## Sign in fails: *Invalid OAuth2 redirect_uri*

The redirect FragQ sends doesn't match one listed in the Discord developer portal. FragQ uses
`PUBLIC_URL` + `/auth/callback`. Check:

1. `PUBLIC_URL` in `.env` is exactly the address in your browser's address bar, including `https://`
   and the port (`https://192.168.1.50:4443`), without a trailing slash.
2. **OAuth2 → Redirects** in the developer portal has exactly `PUBLIC_URL/auth/callback`, saved.
3. After changing `.env`, run `docker compose up -d`.

## Sign in works, but no servers are shown

- The bot must be on the server: use **Invite bot**.
- You need access there: server owner, Discord *Administrator*, a channel's **Admin role**, or a grant
  on the [Users page](../administration/access.md).
- The **Server Members Intent** must be on, or the bot can't see your roles.
- Press **Refresh server list** in the rail after getting new access.

## The bot is online but ignores `!add`

- The channel must be enabled: **Add channel** in the web panel, or `!enable_pubobot`.
- The **Message Content Intent** must be on in the developer portal. Without it the bot can't read
  chat commands; slash commands and buttons still work.
- Check the channel's **Command prefix**.
- The queue may be [paused](../queue-panel/moderators.md#pause-queue); the bot then says so.

## Slash commands don't appear

Global slash commands can take up to an hour after the first start or an update. Set
`DISCORD_SLASH_SERVERS` to your server id and run `docker compose up -d` to register them there
instantly. Also check that the invite included the `applications.commands` scope; the **Invite bot**
link does.

## The queue panel doesn't update, or the buttons say *This interaction failed*

- The panel was posted by a different bot (for example an old test bot); post it again with `!panel`.
- The bot needs **Send Messages**, **Embed Links**, **Attach Files** and **Read Message History** in the
  channel; the avatar row is an attached image. The **Invite bot** link asks for all of them, but a
  channel's permission overrides can still take them away, and bots invited with an older link may not
  have Embed Links and Attach Files.
- If the panel message was deleted, FragQ stops updating it; post a new one.

## Changes in the web panel don't show up after an update

Reload the page. FragQ makes browsers fetch the new files after an update; a hard reload
(++ctrl+shift+r++) helps if a proxy in front of FragQ caches them.

## The browser warns about the certificate

FragQ is using a self-signed certificate. That is expected with `TLS_MODE=internal`, on a LAN, or when
Let's Encrypt failed. Check `docker compose logs caddy` for the reason; usually port 80/443 isn't
reachable from the internet, or the domain doesn't point at this server. See
[HTTPS and ports](../administration/https.md), including how to
[trust the self-signed certificate](../administration/https.md#trust-the-self-signed-certificate).

## Port already in use

`Bind for 0.0.0.0:80 failed: port is already allocated` means another program uses the port. Choose
other ports with `HTTP_PORT` and `HTTPS_PORT` in `.env` and run `docker compose up -d`. Update
`PUBLIC_URL` and the OAuth2 redirect to include the new port.

## Steam linking fails

- *Couldn't reach Steam*: the container can't reach the internet, or Steam is down. FragQ links the
  account anyway when it can't check it, and fetches the name and avatar later.
- *Steam rejected the Steam API key*: check or remove the key on the **Settings** page.
- *already linked to another Discord member*: the bot owner can **Unlink** it on the **Settings** page.

## `docker compose` refuses to start: *Set MYSQL_PASSWORD in .env*

`MYSQL_PASSWORD` and `MYSQL_ROOT_PASSWORD` are empty. Run the installer, or set them by hand before the
first start.
