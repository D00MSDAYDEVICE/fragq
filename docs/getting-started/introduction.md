# What is FragQ?

FragQ is a Discord bot that runs **pickup games**: players add themselves to a queue, and when it is
full the bot turns them into a match. It handles everything between "who wants to play?" and "here is
the server":

1. **Queues.** Each enabled Discord channel has one or more queues, for example `4v4-pickup` and
   `duel`. Players join with a button, `!add`, `++` or `/add`, and leave with **Leave**, `!remove` or
   `--`. AFK and offline players can be removed automatically, and each player can set an expire timer.
2. **Check-in.** When a queue fills, the players confirm with `!ready` (or a reaction) within the
   check-in time. Anyone who doesn't is removed and the queue waits for replacements.
3. **Teams.** Captains draft players in turn, or FragQ balances the teams by rating, or picks them at
   random.
4. **Maps and server.** FragQ picks one or more maps (or runs a map vote), and posts the server
   address and password.
5. **Results.** On ranked queues captains report the result. FragQ updates the ratings, rank roles and
   leaderboard.

## How FragQ relates to PUBobot2

FragQ is a fork of [PUBobot2](https://github.com/Leshaka/PUBobot2) by Leshaka. The bot code, the
commands and the database schema are PUBobot2's, so existing PUBobot2 communities can switch without
losing anything; see [Moving from PUBobot2](../administration/pubobot2.md). What FragQ adds:

| Feature | Where to read more |
|---|---|
| Web panel with an editor for every channel and queue setting, light and dark theme | [Navigating the panel](../web-panel/overview.md) |
| Import / export of `.cfg` files, compatible with the old PUBobot2 web interface | [Import and export](../web-panel/import-export.md) |
| Live view of queues and matches, leaderboard and match history with CSV downloads | [Live, leaderboard and matches](../web-panel/live-and-stats.md) |
| Discord queue panel with Join / Leave buttons and player avatars | [The queue panel](../queue-panel/panel.md) |
| Moderator buttons: add a player, pause the queue | [Moderator buttons](../queue-panel/moderators.md) |
| A new match-start message with copyable server addresses | [Match start message](../queue-panel/match-message.md) |
| Steam account linking, optionally required before joining | [Linking Steam](../playing/steam.md), [Steam integration](../administration/steam.md) |
| Web panel access for members and roles, per server or per channel | [Web panel access](../administration/access.md) |
| Docker Compose deployment with MariaDB and automatic HTTPS | [Installation](installation.md) |

## How it runs

FragQ is a Docker Compose stack with three containers:

| Container | What it does |
|---|---|
| `db` | MariaDB: configs, ratings, matches, Steam links and web panel access |
| `app` | The bot and the web panel, in one Python process. Every change in the web panel goes through the same code as the chat commands, so validation and live updates behave the same. |
| `caddy` | Serves the web panel over HTTPS and gets the certificates itself |

You host it yourself, on a Linux server, a VPS or a Windows PC with Docker Desktop. Nothing is shared
with a central FragQ service.

Next: [Create the Discord application](discord-app.md).
