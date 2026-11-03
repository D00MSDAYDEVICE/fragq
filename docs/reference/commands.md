# Commands

FragQ has PUBobot2's commands, plus a few of its own (marked **FragQ**). Most work both as a chat
command and as a slash command. Chat commands start with the channel's prefix, `!` by default.

**Who** column: *everyone*; *Mod* = the channel's **Moderator role** or **Admin role**; *Admin* = the
**Admin role**. The server owner and members with Discord's *Administrator* permission count as both.

## Queues

| Chat | Slash | Who | What it does |
|---|---|---|---|
| `++`, `!add`, `!j` | `/add` | everyone | Join the default queues, or the named ones: `!add duel 4v4` |
| `+name` | | everyone | Join one queue: `+duel` |
| `--`, `!remove`, `!l` | `/remove` | everyone | Leave all queues, or the named ones |
| `-name` | | everyone | Leave one queue |
| `!who` | `/who` | everyone | Who is in each queue |
| `!queues` | `/queue list` | everyone | List the channel's queues |
| `!promote [queue]` | `/promote` | everyone | Ping the promotion role with how many players are needed |
| | `/subscribe`, `/unsubscribe` | everyone | Get or drop a queue's promotion role |
| `!expire [time]` | `/expire` | everyone | Show or set your expire timer for now: `!expire 1h` |
| | `/expire_default` | everyone | Show or set the timer you get each time you join |
| `!allow_offline`, `!ao` | `/allow_offline` | everyone | Stay in the queues while offline, until your next match |
| `!steam [id]`, `!link_steam`, `!steamid` | `/steam` | everyone | **FragQ** Link your Steam account, or show the linked one. Changing it needs a moderator's approval. See [Linking Steam](../playing/steam.md). |

Joining is refused while the channel is [paused](../queue-panel/moderators.md#pause-queue).

## Matches

| Chat | Slash | Who | What it does |
|---|---|---|---|
| `!ready`, `!r` | `/ready` | players | Confirm during the check-in |
| `!notready`, `!nr` | `/notready` | players | Drop out during the check-in |
| `!auto_ready [time]`, `!ar` | `/auto_ready` | everyone | Confirm your next check-in automatically |
| `!pick <player>`, `!p` | `/pick` | captains | Pick a player during the draft |
| `!capme` | `/capme` | captains | Give up the captain spot |
| `!capfor <team>` | `/capfor` | players | Become a team's captain |
| `!subme` | `/subme` | players | Ask for a substitute |
| `!subfor <player>` | `/subfor` | everyone | Take the place of a player who asked for a substitute |
| `!teams` | `/teams` | players | Show your match's teams |
| `!matches` | `/matches` | everyone | Matches in progress |
| `!report_loss`, `!rl` | `/report loss` | captains | Report that your team lost |
| `!report_draw`, `!rd` | `/report draw` | captains | Offer or accept a draw |
| `!report_cancel`, `!rc` | `/report abort` | captains | Offer or accept cancelling the match |
| `!lastgame`, `!lg` | `/lastgame` | everyone | The last match, of the channel, a queue or a player |
| | `/maps`, `/map` | everyone | A queue's maps, or a random one |
| | `/server` | everyone | A queue's server |
| | `/switch_dms` | everyone | Turn the match-start direct message on or off |
| | `/cointoss` | everyone | Toss a coin |

## Ratings and stats

| Chat | Slash | Who | What it does |
|---|---|---|---|
| `!rank [player]` | `/rank` | everyone | A rating profile |
| `!leaderboard`, `!lb` | `/leaderboard` | everyone | The rating leaderboard |
| | `/top` | everyone | Most active players over a day, week, month or year |
| | `/stats show` | everyone | Channel or player statistics |
| | `/nick` | everyone | Change your nickname and keep the rating prefix |
| | `/help`, `/commands` | everyone | Channel or queue help, and a link to this command list |

## Moderation

| Chat | Slash | Who | What it does |
|---|---|---|---|
| | `/queue add_player` | Mod | Add a player to a queue. The 👤 panel button does the same. |
| | `/queue remove_player` | Mod | Remove a player from the queues |
| | `/queue clear` | Mod | Remove all players from the queues |
| | `/queue start` | Mod | Start a queue that isn't full |
| | `/queue split` | Mod | Split a queue into several matches |
| `!cancel_match <id>` | | Mod | Cancel a match in progress |
| | `/match report` | Mod | Report a match result as a moderator |
| | `/match create` | Mod | Record a rated match by hand |
| | `/match sub_player` | Mod | Swap a player in a match |
| | `/match put` | Mod | Put a player in a team |
| | `/noadds list`, `/noadds add`, `/noadds remove` | Mod | Ban players from joining for a while, and lift the ban |
| | `/phrases add`, `/phrases clear` | Mod | Phrases the bot says when a player joins |
| | `/rating seed`, `/rating penality` | Mod | Set a player's rating, or subtract points |
| `!rating_hide_player`, `!rating_unhide_player` | `/rating hide_player`, `/rating unhide_player` | Mod | Hide a player from the leaderboard, or show them again |
| `!stats_reset_player` | `/stats reset_player` | Mod | Reset a player's stats |
| | `/stats undo_match` | Mod | Undo a finished match |
| | `/rating reset`, `/rating snap` | Admin | Reset all ratings, or snap them to rank values |
| | `/stats reset` | Admin | Reset all stats on the channel |
| `!stats_replace_player` | `/stats stats_replace_player` | Admin | Move one player's stats to another account |

The queue panel's **Pause queue** button has no chat command; see
[Moderator buttons](../queue-panel/moderators.md).

## Configuration

| Chat | Slash | Who | What it does |
|---|---|---|---|
| `!enable_pubobot` | `/channel enable` | Discord Administrator | Enable the bot on this channel |
| `!disable_pubobot` | `/channel disable` | Discord Administrator | Disable the bot on this channel |
| | `/channel delete` | Discord Administrator | Disable the bot and delete the channel's stats and configs |
| | `/channel show` | everyone | List the channel settings |
| | `/channel set <variable> <value>` | Admin | Change a [channel setting](channel-settings.md) |
| `!set_channel_cfg <json>` | | Admin | Change several channel settings at once |
| `!panel [off]` | `/channel panel` | Admin | **FragQ** Post, move down or remove the [queue panel](../queue-panel/panel.md) |
| | `/queue create_pickup <name> <size>` | Admin | Create a queue |
| | `/queue list`, `/queue show` | everyone | List the queues, or show a queue's settings |
| | `/queue set <queue> <variable> <value>` | Admin | Change a [queue setting](queue-settings.md) |
| `!set_queue_cfg <queue> <json>` | | Admin | Change several queue settings at once |
| | `/queue delete` | Admin | Delete a queue |

Everything in the Configuration table can also be done in the [web panel](../web-panel/overview.md).

!!! tip "Slash commands not showing?"
    Global slash commands can take up to an hour to appear after the bot starts for the first time or
    after an update. Set `DISCORD_SLASH_SERVERS` to your server id to register them there instantly; see
    the [.env reference](../administration/env.md#discord).
