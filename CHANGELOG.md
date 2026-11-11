# Changelog

## Unreleased

- **Duplicate channels and queues:** **Duplicate** at the top of a channel's or queue's **⋯** menu. A queue
  is copied on the same channel as `name(Copy)`. A channel asks for another text channel, like **Add
  channel**, and gets the same settings and a copy of every queue.

## 1.1.0 (2026-11-08)

- **Queue panel follows the players:** when someone joins a queue, FragQ posts the queue panel if the
  channel doesn't have one, or moves it to the bottom of the channel (like **Move panel down**) if
  messages have been posted since.
- **Auto-refresh panel per channel:** a switch at the top right of each channel's **Settings →
  General** tab re-posts a panel buried by chat every few minutes (5 to start with). It replaces the
  bot-wide **Auto-repost queue panels** setting on the Settings page; if that was on, every channel is
  switched on with the same interval. The channel setting is `panel_autorefresh` (minutes, not set = off).
- **Prove a Steam account:** the public `/verify` page lets a player sign in with Discord and then through
  Steam, which proves the account is theirs. Each link now records how it was made (claimed, confirmed
  from a game server, or proved with Steam), shown in **Linked players**. A proof replaces someone else's
  unproved claim on the account; changing to another account still needs a moderator. Needs `PUBLIC_URL`.
- **Read linked accounts:** a new connector permission, off by default, for `GET /steam/links`, which
  returns the Steam and Discord links of the server's members. A key with only this permission needs no queue.
- **Connectors page:** a **Fragdex** panel with its address and its own connectors. The rest are now under
  **Additional Connectors**, listed last.

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
