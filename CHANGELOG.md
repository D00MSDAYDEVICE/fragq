# Changelog

## 1.0.0 (2026-11-02)

First FragQ release. FragQ is a fork of [PUBobot2](https://github.com/Leshaka/PUBobot2) by Leshaka:
the same commands, queues, drafts, ratings, rank roles and map votes, using the same database.
On top of that it adds:

- **Web panel:** sign in with Discord, then use a server rail, a channel and queue tree, and a tabbed
  settings editor for every channel and queue variable. There's a light and a dark theme.
- **Import / export:** JSON `.cfg` files, compatible with configs exported from the original PUBobot2
  web interface.
- **Live view:** queues filling up and matches in progress, for each channel and each server.
- **Leaderboard and match history:** browse them in the panel or download them as CSV.
- **Queue panel:** a Discord message with **Join** and **Leave** buttons that updates live, shows a
  row of player avatars per queue, and moves below each new match message.
- **Moderator buttons:** **Add player** (works while paused) and **Pause queue** on the queue panel.
  The pause also works from the web panel and survives restarts.
- **Steam integration:** players can link a Steam account with `!steam`, `/steam` or a pop-up form.
  An optional **Require Linked Steam IDs** setting makes linking mandatory before joining. A Steam
  Web API key is optional. Changing a linked account needs a moderator's or admin's approval, with
  one-click **Approve** / **Reject** on the Settings page.
- **Settings page:** bot-wide settings, including **Auto-repost queue panels** (moves buried panels
  back to the bottom every few minutes, 5 by default), and a **Backup and restore** panel that saves
  all FragQ settings to one file and restores them on a fresh install.
- **New match-start message:** teams side by side with ranks and ratings, numbered maps, and copyable
  server addresses. The players are pinged above the embed. The classic layout is still available.
- **Game connectors (beta):** a **Connectors** page where game servers get keys (with expiry dates,
  allowed IPs, rate limits and permissions) to send match results. FragQ matches each result to the
  pickup match by the players' linked Steam accounts and posts the highlights and stats in the queue's
  channel. The format is the same for every game. Includes a minqlx / minqlxtended plugin for Quake
  Live with end-of-match stats, in-game `!link` (confirmed in a Discord direct message) and
  `!linkenforce` to keep unlinked players in spectator, and `!setdiscord` to give players who
  aren't on the Discord yet an invite link.
- **Web panel access:** a **Users** page to give Discord members or roles access to the panel, on
  the whole server or on chosen channels, with presets and individual permissions.
- **Docker Compose deployment:** MariaDB, the bot and Caddy with automatic HTTPS, plus interactive
  installers for Linux and Windows.
- The **Commands** link and `/commands` point to the command reference in the FragQ documentation.
- The **Invite bot** link also asks for **Embed Links** and **Attach Files**, which the queue panel and
  its avatar image need. Before, they only worked where `@everyone` allowed them.
- Fixed: moderator-only commands said "You must possess admin permissions" to moderators.
