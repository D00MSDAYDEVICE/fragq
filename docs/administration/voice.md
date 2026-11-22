# Voice moves

FragQ can move a match's players between Discord voice channels: from a lobby into their team's channel
when the match starts, and back to the lobby when it ends. It is **off for every queue** until you turn it
on, including queues that existed before the update.

## What gets moved

Each queue has three voice channels of its own, with any names: a **Lobby** and one channel per team.

- When a match starts (its teams are final), players who are **in the Lobby** are moved into their team's
  channel.
- When the match is reported or canceled, they are moved from the team channels back to the Lobby, if
  **Back to the lobby after the match** is on.
- Game servers can also move players, for substitutes and team changes (see below).

FragQ never pulls anyone into voice. A player who isn't in voice, or is in any voice channel other than the
queue's three, is left alone. Only these moves happen:

| From | To |
|---|---|
| The Lobby | A team channel |
| One team channel | The other team channel (a team change) |
| A team channel | The Lobby |

An unranked match ends as soon as its teams are posted, so for those FragQ only moves players into the team
channels. Players go back to the Lobby when a game server sends them there, or on their own.

## Set it up

1. Give the bot **Move Members**, **Connect** and **View Channels** on the three voice channels: in each
   channel's permissions, or for the bot's role in **Server Settings → Roles**. The invite link asks for
   these since FragQ 1.3.0; a bot invited before that needs them added.
2. In the web panel, open the queue, then **Settings → Voice**.
3. Pick the **Lobby voice channel**, the **First team's voice channel** and the **Second team's voice
   channel**. They must be three different channels.
4. Turn on **Move players in voice** and press **Save changes**.

The first team is the first one in the match message (Alpha by default, or the first of the queue's
**Team names**). The settings are also available as `voice_moves`, `voice_lobby`, `voice_team1`,
`voice_team2` and `voice_return` with `/queue set`; see the [queue settings](../reference/queue-settings.md).

## Game servers

A [connector](../connectors/index.md) with the **Move players in voice** permission can move players too, for
substitutes and team changes during a match. It works for any game: the game server sends its teams with the
players' Steam IDs, and FragQ moves their linked Discord accounts, following the same rules as above. The
request is described in the [result format](../connectors/result-format.md#voice-moves). The
[Quake Live plugin](../connectors/quake-live.md#voice-moves) does it with `qlx_fragqVoice 1`, and admins on the
game server can [move players by hand](../connectors/quake-live.md#moving-players-by-hand) with `!voice`, for
teams arranged in the game.

Each request is for one queue, and only ever one of the connector's own queues: the queue the game server
names, else the queue of the FragQ match its players are in, else the connector's only queue with voice moves
on. If none of these decides it, FragQ refuses the request and moves nobody. Giving each game server
[its own connector](../connectors/index.md#create-a-connector) avoids the question.

Games name their teams their own way. FragQ decides which game team goes to which of that queue's channels like
this:

1. **By name:** a game team goes to the team channel that has its name in it, so `red` goes to *🔴 Red
   Team* and `blue` to *Blue side*.
2. If the names don't help, **where the players already are**: the team channel most of the game team's
   players are in, or that the FragQ match put them in.
3. If that doesn't decide it either, **at random**.

The choice is kept for the rest of the match, so the teams don't swap channels when a later request comes in.

## When nobody moves

FragQ logs what it did for each match. A game server gets the outcome for each player:

| Outcome | Meaning |
|---|---|
| `moved` | Moved |
| `already_there` | Already in the right channel |
| `not_in_voice` | Not connected to voice |
| `other_channel` | In a voice channel that isn't the Lobby or the other team's channel, so left alone |
| `not_linked` | The Steam account isn't linked to a Discord account (game servers only) |
| `not_member` | Not a member of the Discord server |
| `no_permission` | The bot lacks Move Members, Connect or View Channels on one of the channels |
| `failed` | Discord refused for another reason; the bot's log says why |
| `in_series` | A Lobby move from the game server between a [series](../playing/matches.md#series)' games: players stay in their team channels until the series ends |
