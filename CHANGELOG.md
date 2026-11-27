# Changelog

## 1.6.0 (2026-11-27)

### New

- **QueueGen** (new page next to Bot status, with a new **Manage events** permission). Schedule a match between
  two fixed teams on a date of your choice:
  - **Its own channels:** FragQ creates the event's text channel in an **Events** category, a voice channel per
    team and a Lobby (one per event, one shared by every event, or one you choose), and a queue only the roster
    can join. Everyone sees the channels and only the roster and admins type, or they're private. Event channels
    stay out of the channel list, and are deleted 24 hours after the event ends (or 3 or 7 days, or kept).
  - **Check-in:** at the start time (or with **Open check-in**) FragQ pings the roster with a message showing
    who checked in, and reminds the rest every 10 minutes. The match starts with the teams as set once everyone
    has; a short roster at the start time is flagged instead. A canceled match reopens check-in.
  - **The match:** a normal FragQ match with the teams' names, voice moves, series, game server results and
    Slipgate results, per event. Rated events keep their own ratings; unrated ones wait for a player to end the
    match. Admins swap players before or during the match; players can't sub themselves in.
  - **Discord event:** each public event gets a Discord scheduled event, *Somewhere Else* at the server's name,
    titled *◄Team1 vs Team2►*, with the rosters as its description, from the match's start until a day later by
    default, with one of four FragQ covers (Crosshair, Versus, Arena, Match day). It follows the event: edited
    with it, started at check-in, completed or canceled with it.
  - **Tournaments:** events in the same tournament share one rating history, with the tournament's rating
    system and starting rating; the page shows each tournament's leaderboard.
  - **Backups** include each server's QueueGen settings and tournaments; event channels are left out.
- **Quake Live plugin 1.6.0: `!queueverify`, `!sub` and `!whois`**, contributed by Kr3m (thanks!).
  - **`!queueverify`** (`!qv`) checks Red and Blue against the FragQ match the server is playing and fixes them:
    non-PUG players to spectator, PUG spectators switched in, and PUG players put on a colour only when their side
    is certain. `dry` only reports, `status` shows the key's queues and permissions. Discord accounts come from
    Fragdex, with FragQ's Steam links filling the gaps; every move is checked again on the game thread.
  - **`!sub` / `!unsub`** mark subs `!queueverify` never moves, or a sub who takes another player's place.
  - **`!whois`** shows a player's Steam and linked Discord accounts, by player id, Steam ID, Discord id or
    username, or name. Permission level 3 by default (`qlx_fragqWhoisLevel`).
  - New connector request **`POST /match`**: the current matches of the key's queues with each player's team,
    with the key's *Check linked players* permission. Unranked matches are listed for 2 hours after they start.

### Improvements

- The invite link also asks for **Speak** and **Create Events**, for QueueGen. A bot already on your server
  needs them added to its role, or a new invite.

## 1.5.0 (2026-11-24)

### New

- **Slipgate integration** (off by default). Add a Slipgate API key in the new **Slipgate** panel on the Settings
  page (**Save**, **Test**, **Remove**). Each queue gets a **Slipgate** tab (after Voice) with its **game type** and
  **ladder** (standard, or modified for PQL and instagib). With a tested key:
  - **Team balancing:** queues with **Pick teams** `matchmaking` and **Balance teams with Slipgate** on get even
    teams from Slipgate; the match message shows the fairness and each team's chance, or why FragQ balanced
    instead (unlinked player, Slipgate slow or unavailable).
  - **Rating limits:** a **minimum** and **maximum** Slipgate display rating per queue. Players outside the range
    are told why and can't join; unrated and provisional players are let in unless switched off. The panel shows
    the range (*🎯 1200–1800*).
  - **Starting ratings** (channel **Rating** tab): new players on ranked queues start from their place on the
    Slipgate ladder instead of the initial rating.
  - **`!slipgate`** / `/slipgate` shows a player's Slipgate ratings.
  - **Results:** Quake Live connectors can **Add Slipgate details to results**: once Slipgate has the match, the
    posted result gets a link to it, its highlights and its demos. A queue can opt out with **Disable Slipgate
    Results**.

  A match start never waits more than 2.5 seconds on Slipgate, rate limits are respected, and when Slipgate is
  unavailable FragQ carries on without it. No game server changes needed.
- **Pause per queue.** Each queue pauses on its own instead of the whole channel: its Join button greys out, `++`
  joins the open queues, and the panel turns amber only when every queue is paused. The Discord ⏸ button asks
  which queue (or all) when a channel has several. **Pause Queue**, **Refresh Panel** (was *Move panel down*) and
  **Remove panel** moved from the channel page to a row above each queue's settings tabs. Channels paused before
  the update have each of their queues paused.
- **Server List.** A new channel tab for the channel's game servers (`IP:port`, with an optional label shown only in
  the web panel). Each queue can **designate** one of them next to its name; its address then leads the match's
  server information, above the queue's Server text.
- **Require linked Steam IDs per queue.** Now a queue setting (General) instead of one switch for the whole bot.
  Unlinked players adding to several queues join the ones that don't need a link and are asked to link for the rest.
  If the old switch was on, every queue has it on after the update.

### Improvements

- **Names under panel avatars** (queue Appearance setting): 6 avatars per row with each player's name below.
- **Series queues** show 🔁 *series of 3 games* on the panel before anyone adds, and moderators get an ⏹️ **End
  series** button with a private confirmation.
- **Settings page:** two columns of panels using the full screen width, Linked players across the bottom, and the
  Steam key badge at the top right.
- **More room:** pages that aren't about one server (Settings, Bot status, Users, Connectors) no longer show the
  empty channel column.
- **Classic match message:** each server line gets its own copyable code box.

### Fixes

- **Config imports** with an empty value for a required setting (such as `"series_length": null`) now use the
  default instead of refusing the whole import.
- **Table settings** checked only their first column; every column is checked now.

## 1.4.0 (2026-11-21)

- **Series.** A new queue setting, **Series length**, lets one pickup play several games on the game server
  before the queue opens again, on ranked and unranked queues. While a series is on, nobody can add to the
  queue (*"… is held: series game 2 of 3 (match #123)"*; the queue panel shows it 🔒 held). Each result the
  game server posts for the match counts one game, and its post says *Series game 2 of 3*. The series ends
  with the last game, `!endseries <queue>` or `/endseries` (moderators), **End series** in the web panel, the
  match being canceled, or no result for the match lifetime. Between games the players stay in their team
  voice channels (the game server's Lobby moves answer `in_series`); they go back to the Lobby at the end.
  A series survives a bot restart.
- **Hold players after start** (unranked queues). A new queue setting keeps an unranked match in progress
  for a while after it starts, so its players can't add again while they play. It ends with the game
  server's result, `/report` from one of its players, a moderator, or when the time is up. Nothing is rated.
- **Web panel header:** the bot's version is shown in green, without the bot's picture beside it, and the
  **Commands** link is now **Documentation**, to the documentation's home page. The documentation's home page has
  a new intro and a **Commands** button.
- **Quake Live plugin 1.4.0: voice moves at the countdown.** With `qlx_fragqVoice 1` the teams are moved as soon
  as the match countdown starts, instead of when the match starts; some minqlxtended builds never report the
  start, so players were never moved there. At the start the teams are sent again only if they changed, and team
  changes during the countdown are sent too. `qlx_fragqVoice` is read again at every countdown, so turning it on
  in warmup no longer waits for a map change.
- **Voice diagnostics in `!fragq`:** *Auto voice moves* (`qlx_fragqVoice`, the game server's own switch),
  *Last voice event* (what the last countdown, start, team change, match end or abort did, or why it sent
  nothing: voice off, not a team mode, only bots on the teams) and *Last voice request* now with the reason for
  anyone not moved (not in voice, not linked, in another voice channel …). Every event and request is also in
  the server log.
- **Quake Live plugin: `!fragq queue`.** Lists the key's queues with their channel and whether voice moves
  are on, marks the one `qlx_fragqQueue` picks, and names the Discord server's queues the key doesn't have, so a
  queue missing from the connector is easy to spot.
- **Quake Live plugin: what to do when no queue is set.** When FragQ can't tell which queue a voice request is
  for (several of the key's queues have voice moves on, and the players aren't in a FragQ match), the error in
  `!fragq` and `!voice` now says to set `qlx_fragqQueue` (or, for `!voice`, to add a queue name). `!fragq test`
  and `!fragq queue` warn when `qlx_fragqQueue` isn't set but several of the key's queues have voice moves on.
- **`!fragq` status, one setting per line:** address, key, results, last result, link required, Discord invite,
  queue, auto voice moves, last voice event and last voice request each get a line, with the option in cyan and its setting in white
  (on/yes green, off/no red).
- **`GET /status`** also returns `queue_list` (channel and voice moves of each of the key's queues) and
  `other_queues`.
- **Clearer error for a queue missing from the key:** a voice request naming a queue that exists on the Discord
  server but isn't ticked on the connector (such as a queue added or duplicated after the connector was made) now
  says so and points to the Connectors page, instead of only *no queue named …*.

## 1.3.4 (2026-11-21)

- **Quake Live plugin 1.3.0: `qlx_fragqQueue`.** Names the FragQ queue a server plays. It is sent with every voice
  request and match result, so servers that share a key with several queues always move players between their own
  queue's channels, and results are only matched to that queue. A queue typed after `!voice` takes precedence.
  `!fragq` shows it and `!fragq test` warns when the key has no queue of that name.
- **Queue names in any case, never ambiguous:** voice requests and results match queue names regardless of case
  (`!voice 5 blue ca`). A name two of the key's queues share, in different channels, is refused instead of
  picking one, and an unknown name lists the key's queues.
- **Docs:** one connector per game server, and how FragQ picks the queue for a voice move.

## 1.3.3 (2026-11-21)

- **Fragdex settings: Test no longer empties the form.** After a successful **Test** of settings that weren't saved
  yet, the address and key stayed in the fields, so **Save** saves what was tested instead of asking for both again.
- **Fragdex address with a path:** an address with `/api...` in it (such as `.../api` or a pasted `.../api/v1/status`)
  had `/api/v1` added a second time and failed with *HTTP 404*. FragQ now uses the site's address plus `/api/v1`.
  A 404 now names the address FragQ tried.

## 1.3.2 (2026-11-21)

- **Quake Live plugin 1.2.1: addresses with a path.** `!fragq url` and `qlx_fragqUrl` given an address with `/api...` in it
  (such as `https://fragq.example.com/api` or a pasted `.../api/connect/v1/status`) added the connector path a second
  time, and every request failed with *HTTP 401: Not logged in*. The extra path is now removed, also from an address
  saved earlier.
- **Clearer error for a wrong connector address:** a connector key sent to a web panel path outside the connector API
  now gets *HTTP 404: Wrong address* naming the path, instead of *Not logged in*.

## 1.3.1 (2026-11-19)

- **Quake Live plugin 1.2.0: `!voice`.** Admins move players by hand, for teams arranged in the game:
  `!voice teams`, `!voice lobby` or `!voice <player id> red|blue|lobby`, with an optional queue name. Works in
  warmup and with `qlx_fragqVoice 0`. The new cvar `qlx_voicemoveperm` sets who may use it (level 4 by default).
- **Aborted matches go back to the lobby:** `!abort` and abort votes restart the map without ending the match, so
  the plugin now also sends everyone to the lobby when that happens after a live match (`qlx_fragqVoice 1`).
- **One Flag CTF and Overload send teams:** the plugin's list of team modes had wrong names for One Flag CTF
  and was missing Overload, so voice moves never ran in those modes.
- **Docs:** match results need `zmq_stats_enable 1` on minqlxtended too, not only on minqlx.

## 1.3.0 (2026-11-19)

- **Voice moves (off by default):** each queue can name a Lobby and two team voice channels. When a match
  starts, players in the Lobby are moved into their team's channel, and back to the Lobby when it is reported
  or canceled. Nobody outside those channels is ever moved. Set it up under the queue's **Settings → Voice**.
  The invite link now asks for View Channels, Connect and Move Members; a bot invited earlier needs them added.
- **Move players in voice:** a new connector permission, off by default, for `POST /voice`. Game servers can
  move players for substitutes and team changes. Game teams go to the channel with their name in it (red to
  red), otherwise to where their players already are, otherwise at random.
- **Quake Live plugin 1.1.0:** `qlx_fragqVoice 1` sends the teams at match start and after team changes, and
  the lobby at match end.
- **`!rw` works:** `!rw <match id> <team>` or `!rw <match id> draw` reports a match as a moderator, like
  `/match report`. PUBobot2 documented it but never had the command.
- **Fragdex lookups (off by default):** the Settings page can connect to a Fragdex server with a Fragdex API key,
  with **Save** and **Test** buttons. Once the connection passes a test, **Lookup unknown IDs using Fragdex** can be
  turned on. Game servers' Steam IDs that nobody linked in FragQ are then looked up in Fragdex: posted results show
  those players' Discord names, and the linked-player check and voice moves find them. These are never saved as
  FragQ links, never count as verified and never affect ratings.
- **On/off switches show their state:** a setting that was off lit both OFF and ON. Now OFF is red when off and ON
  is green when on. The voice switches have a single OFF/ON choice like the other queue switches.

## 1.2.0 (2026-11-11)

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
