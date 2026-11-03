# Joining queues

Every channel FragQ is enabled on has one or more queues. You can join them in four ways, and they all
do the same thing.

## With the queue panel

If the channel has a [queue panel](../queue-panel/panel.md), press <span class="dbtn green">➕ Join</span>.
With several queues, each has its own **Join *queue*** button. <span class="dbtn red">✖️ Leave</span>
removes you from every queue on the channel. The bot's reply is only visible to you, so the channel
stays clean.

## With chat commands

| Type | What it does |
|---|---|
| `++` | Join the channel's default queues |
| `+4v4-pickup` or `+4v4` | Join a queue by name or [alias](../reference/queue-settings.md#general) |
| `!add` / `!j` | Join the default queues; `!add duel 4v4` joins several by name |
| `--` | Leave all queues |
| `-duel` | Leave one queue |
| `!remove` / `!l` | Leave all queues; `!remove duel` leaves one |
| `!who` | List who is in each queue |

`!` is the default prefix; a channel can use another one (**Command prefix**, `prefix`). The default
queues are those with **is default** (`is_default`) turned on.

## With slash commands

`/add`, `/remove` and `/who` work like their chat versions, with the queue names offered as you type.

## Staying in the queue

FragQ removes players who aren't around anymore. What applies depends on the channel's
[auto-remove settings](../reference/channel-settings.md#auto-remove):

- **Offline:** you are removed when your Discord status goes offline. `!allow_offline` (`!ao`)
  keeps you in the queues while offline, until your next match. Run it again to switch it off.
- **AFK:** you are removed when you go idle (AFK).
- **Expire timer:** you are removed a while after your last `!add`. `!expire 1h30m` sets your own timer
  for now, `/expire_default` sets the timer you get every time you join, and `!expire` shows it.

## Who can't join

- **Paused queues:** a moderator can [pause the channel](../queue-panel/moderators.md#pause-queue).
  Join buttons turn grey and `!add` replies that joining is paused. Moderators can still add players.
- **Blacklist / whitelist roles:** a channel or queue can refuse members with a blacklist role, or only
  accept members with a whitelist role.
- **Noadds:** moderators can ban a player from the queues for a while with `/noadds add`.
- **Linked Steam account:** when the bot owner turns on
  [Require Linked Steam IDs](../administration/steam.md#require-linked-steam-ids), FragQ asks for your
  Steam ID the first time you join. See [Linking Steam](steam.md).
- **Already in a match:** you can't join while you are in a match that hasn't finished.

## Promoting a queue

`!promote` (or `/promote`) pings the channel's or queue's **Promotion role** with how many players are
still needed. Members subscribe to that role with `/subscribe` and leave it with `/unsubscribe`. The
channel's **Promotion delay** limits how often a queue can be promoted.

Next: [Matches](matches.md).
