# Quake Live (minqlx)

The FragQ plugin for Quake Live servers:

- sends each match's results to FragQ when it ends, with six highlights and a stats table per team;
- adds `!link`, so players can link their Steam account to Discord from the game;
- adds `!linkenforce`, which keeps players without a linked account in spectator;
- adds `!setdiscord`, so players who aren't on your Discord yet are given an invite link.

It is one file, `fragq.py`, that works on both **minqlx** and **minqlxtended**.

## Install

1. In the FragQ web panel, open **Connectors** and create a connector with the game **Quake Live**. Choose
   the queues this server plays and keep all three permissions ticked. Copy the key.
2. Press **Download fragq.py** on the Connectors page (or take `app/plugins/minqlx/fragq.py` from the
   [repository](https://github.com/D00MSDAYDEVICE/fragq)) and put it in the server's `minqlx-plugins`
   folder.
3. Add `fragq` to `qlx_plugins` in `server.cfg`, and turn on the stats feed, which the plugin reads match
   stats from. Both **minqlx** and **minqlxtended** need it for match results; voice moves, `!link` and
   link enforcement work without it:

    ```text
    set qlx_plugins "..., fragq"
    set zmq_stats_enable 1
    ```

4. Restart the server, or load the plugin with `qlx !load fragq`.
5. From the server console or rcon, set the address and key. Never type the key in chat: chat is
   logged and visible to players.

    ```text
    qlx !fragq url https://fragq.example.com
    qlx !fragq key fq_...
    qlx !fragq test
    ```

    `!fragq test` answers with the connector's name and queues. You can also set
    `qlx_fragqUrl` and `qlx_fragqKey` in `server.cfg`; values set with `!fragq` take precedence.

6. Optionally, give players your Discord invite (see [`!setdiscord`](#setdiscord)):

    ```text
    !setdiscord https://discord.gg/abc123
    ```

!!! note "Self-signed certificate"
    If FragQ runs on a LAN address with its own certificate (such as `https://192.168.1.50:8443`),
    set `qlx_fragqVerifyTls 0`.

## Voice moves

With `qlx_fragqVoice 1`, the plugin sends FragQ the teams as soon as the match countdown starts, again when
the match starts if the teams changed, and a few seconds after team changes during the countdown or the match.
It sends the players back to the lobby when the match ends or is aborted (`!abort` or an abort vote). FragQ
then moves them between the queue's Discord voice channels. Changing `qlx_fragqVoice` in warmup takes effect
at the next countdown. It needs:

- [voice moves](../administration/voice.md) turned on for the queue, with its three voice channels set;
- the **Move players in voice** permission on the connector;
- players' Steam accounts linked to Discord.

The red team goes to the team channel with *red* in its name and blue to the one with *blue*; with other
channel names, see [how FragQ decides](../administration/voice.md#game-servers). Only team modes (CA, TDM,
CTF and so on) send teams. A countdown that is called off (a player leaves before it ends) sends nothing,
so the players stay in their team channels until the next countdown or `!voice lobby`.

`!fragq` shows two voice lines:

- **Last voice event**: what the last countdown, match start, team change, match end or abort did, or why it
  sent nothing, such as *nothing sent, qlx_fragqVoice is 0*, *nothing sent, duel isn't a team mode* or
  *nothing sent, only bots on red and blue*.
- **Last voice request**: how FragQ answered, with the reason for anyone not moved, such as
  *countdown: 3 of 4 moved (CHI3): 1 not in voice*.

The server log has a `fragq: voice` line for every event and request.

During a [series](../playing/matches.md#series), FragQ answers the Lobby moves after each game with
*in a series* (shown in **Last voice request**) and leaves the players in their team channels; the
countdown moves still run every game. Each match result the plugin sends counts one game of the series.

### Several servers and queues

FragQ only moves players between the voice channels of one of the **key's** queues, so *blue* always means
the blue channel of that queue. Which queue:

1. the queue typed after `!voice`, such as `!voice 5 blue ca`;
2. else `qlx_fragqQueue`, the queue this server plays;
3. else the queue of the FragQ match the players are in;
4. else the key's only queue with voice moves on.

If none of these decides it, FragQ refuses and the reply says why; nobody is moved. Queue names are not
case-sensitive. Players are only moved if they are already in that queue's Lobby or team channels, so someone
in another queue's channels is never pulled across.

The simplest setup is one connector per server, with only the queues that server plays. If servers share a key
that has several queues, set each server's queue in `server.cfg` (or `+set qlx_fragqQueue CA` on the
command line), so it is still set after a restart:

```text
set qlx_fragqQueue "CA"
```

Without it, automatic moves only work for players in a FragQ match, since that tells FragQ the queue.

`qlx_fragqQueue` is sent with match results too, so FragQ only looks for the match in that queue. `!fragq test`
warns when the key has no queue of that name, or two of them (in different channels), and when it isn't set but
several of the key's queues have voice moves on. `!fragq queue` says so too.

`!fragq queue` lists the key's queues with their channel and whether voice moves are on, marks the one
`qlx_fragqQueue` picks, and names the Discord server's queues the key doesn't have:

```text
FragQ: queues of the key CHI server:
  CHI in #chi-pickup, voice moves on <- qlx_fragqQueue
  DEN in #den-pickup, voice moves off
Not on this key: CHI3 (#chi3-pickup). Tick a queue on the connector in FragQ's Connectors page to use it.
```

### Moving players by hand

For teams arranged in the game rather than picked in Discord, admins can tell FragQ to move players with
`!voice`. It works in warmup too, and whether `qlx_fragqVoice` is on or off; the key still needs **Move players
in voice**.

| Command | What FragQ does |
|---|---|
| `!voice teams` | Moves everyone on red and blue to their team's voice channel now |
| `!voice lobby` | Moves everyone in a team channel back to the lobby |
| `!voice <player id> red` / `blue` / `lobby` | Moves one player (player ids are shown by `/players`) |

Add a queue name at the end, such as `!voice teams CA` (any case), to choose the queue; without one, the
plugin uses `qlx_fragqQueue` (see [Several servers and queues](#several-servers-and-queues)).
The same rules apply as for automatic moves: only players already in the queue's lobby or team channels are
moved. The reply says how many moved and why the others didn't, such as *3 of 4 moved: 1 not linked*. There
are 5 seconds between `!voice` commands. Who may use it is set with `qlx_voicemoveperm` (permission level 4 by
default).

## Match results

When a match ends, the plugin waits a few seconds for the final stats of every player, then sends
one request. Aborted matches, warmup and matches with fewer than `qlx_fragqMinPlayers` players are
not sent. If FragQ can't be reached, the plugin tries again after 5 s, 30 s, 2 min and 10 min.

| Highlight | Who |
|---|---|
| **Top Damage** | Most damage dealt |
| **Least Damage** | Least damage dealt, among players who stayed to the end and played at least half the match |
| **Most Damage Taken** | Most damage received |
| **Most Frags** | Most kills |
| **Highest Accuracy** | Hits ÷ shots over all weapons except the gauntlet, for players with at least `qlx_fragqMinShots` shots |
| **Quitters** | Players who left before the end (*None* if nobody did) |

Ties list every player. In duel and free-for-all a **Winner** highlight is added. The table has
Score, K(ills), D(eaths), Dmg and Acc for each player. A player who left and came back has their
stats added up.

If the server also runs [Slipgate](https://slipgate.gg)'s plugin, turn on **Add Slipgate details to results** on
its connector: once Slipgate has the match, the posted result gets a link to it, its top highlights and its demos.
See [Slipgate details on results](../administration/slipgate.md#slipgate-details-on-results).

## Live status

While a match runs, the plugin keeps FragQ up to date, so [`!checkmatch`](../reference/commands.md#matches) in
Discord shows how it stands. Plugin 1.7.0 or later, on by default (`qlx_fragqLive 0` turns it off); the key needs
**Send match results**.

| Sent | |
|---|---|
| When | At the countdown, when the match starts, at every round end and team change, and every 30 seconds while it runs (at most every 10 seconds); the final score when it ends, *Match aborted* after an abort |
| What | State, map, mode, the clock, the team scores, and each player's team, score, kills, deaths and damage, and who is dead at that moment (most useful in round modes) |
| Period | CA, Freeze Tag, Attack & Defend and Red Rover: the round, with *First to N rounds*. Other modes: the minute of the time limit, with *First to N captures / frags* |

The final result uses the same match id, so it replaces the live status in FragQ. `!fragq` shows **Live status**
and the **Last live update**. If FragQ refuses live status (a FragQ before 1.7, or a key without **Send match
results**), the plugin stops sending until the next map, and `!fragq` says why.

## !link

```text
!link <discord id>
!link <player id> <discord id>
```

- `<discord id>`: the player's Discord user id, or their Discord username. To find the id, turn on
  Developer Mode in Discord (Settings → Advanced), right-click your name and choose **Copy User ID**.
- `<player id>`: the client id shown by `/players`. Players can only use their own id. Admins
  (`qlx_fragqAdminLevel`) can link another player's account, and the server console can too.

FragQ sends the Discord member a direct message to confirm, and the plugin tells the player to check
Discord. Once they confirm, the plugin tells them within about 10 seconds that they are linked. See
[Linking Steam accounts from the game](index.md#linking-steam-accounts-from-the-game).

If the id or username doesn't belong to a member of the connector's Discord server, nothing is
linked and the player gets a warning in yellow:

```text
FragQ: No member of the Thunderdome Discord has that id or username. Check it: your Discord user id
is under Developer Mode, right-click your name, Copy User ID.
FragQ: not on our Discord yet? Join discord.gg/abc123, then type !link again.
```

The second line, with the invite, is only there when an invite is set with `!setdiscord`.

## !setdiscord

```text
!setdiscord <invite URL>
!setdiscord off
!setdiscord
```

Sets the Discord invite that players are given when they need to join your Discord server first.
It appears:

- in the warning when `!link` names someone who isn't a member of the server;
- in the spectator warning and on-screen message while [`!linkenforce`](#linkenforce) is on.

Any usual invite form works, such as `https://discord.gg/abc123`, `discord.gg/abc123` or
`https://discord.com/invite/abc123`; it is shown as `discord.gg/abc123`. Make the invite one that
never expires (in Discord: right-click the server → **Invite People** → **Edit invite link**).

`!setdiscord off` removes it, and `!setdiscord` on its own shows the current one. The invite is kept
in the bot's database, so it survives restarts. It needs `qlx_fragqAdminLevel`.

## !linkenforce

```text
!linkenforce [on|off]
```

With enforcement on, players need a Steam account linked in FragQ to play on this server:

- players without one are moved to spectator, with a warning that they stay there until it is linked
  (and your Discord invite, if one is set with [`!setdiscord`](#setdiscord));
- they can't join a team until they have linked it with `!link`;
- going to spectator is always allowed.

Without an argument, `!linkenforce` switches between on and off. The setting is kept in the bot's
database, so it survives restarts. When enforcement is off, nothing changes for unlinked players.

If FragQ can't be reached, players aren't kept out: the plugin lets them join and tries again later.

## !queueverify

```text
!queueverify            (or !qv)
!queueverify dry
!queueverify status
```

Checks Red and Blue against the FragQ match this server is playing, and fixes them: players who aren't in the
PUG are moved to spectator, and PUG players who are spectating take their place. *Contributed by Kr3m.*

- **The match:** the newest current match of the key's queues (`qlx_fragqQueue` if set) that at least half of
  its players are on this server for. A match still in check-in or draft isn't checked yet. Unranked matches
  count for 2 hours after they start.
- **Who is who:** Discord accounts come from Fragdex (`POST /players/lookup`), and FragQ's own Steam links fill
  the gaps. While Fragdex can't be asked, players without a FragQ link are left
  alone rather than moved.
- **Sides:** FragQ's teams are team 1 and team 2, not Red and Blue. A spectating PUG player is put straight on a
  colour only when every PUG player already on a team agrees which colour is which; otherwise they are told in
  chat and on screen to join their team, with their teammates' names.
- **Safe moves:** every move runs on the game thread and checks that the slot still holds the same Steam account.
  After 1.5 seconds the plugin checks the moves stuck, and reports any another plugin undid.

`!queueverify dry` says what it would change without moving anyone. `!queueverify status` shows the key's queues
and permissions. If FragQ can't be reached, nothing moves.

It needs the key's **Check linked players** permission, and Fragdex's address and key: `qlx_fragdexUrl` and
`qlx_fragdexKey`, or the values saved by the Fragdex plugin (`fragdex.py`) on the same server. It works for
[QueueGen events](../administration/queuegen.md) too, when the event's **Results from** is this server's
connector.

### !sub and !unsub

```text
!sub <player id>                     a sub: !queueverify never moves them
!sub <player id> <player id>         the first player subs for the second, taking their place and team
!sub                                 list the subs
!sub off <player id>, !unsub <player id>, !sub clear
```

Subs belong to one PUG: they are cleared when `!queueverify` finds a new FragQ match. Undoing a sub for a
named player gives that player their place back.

## !whois

```text
!whois <player id | Steam ID | Discord user id | Discord username | part of a name>
```

Shows a player's in-game name, Steam ID (SteamID64 or `STEAM_0:X:Y`), Steam name and linked Discord account, from
Fragdex. When Fragdex can't be reached, FragQ's own links still say whether a Steam ID is linked. Replies go only
to whoever asked, with 3 seconds between lookups. *Contributed by Kr3m.*

It shows who is behind a Steam account, so it needs permission level 3 by default (`qlx_fragqWhoisLevel`).

## Commands

| Command | Permission | What it does |
|---|---|---|
| `!link <discord id>` | everyone | Link your Steam account |
| `!link <player id> <discord id>` | `qlx_fragqAdminLevel` | Link another player's account |
| `!linkenforce [on\|off]` | `qlx_fragqAdminLevel` | Require linked Steam accounts to play |
| `!setdiscord <invite URL>` | `qlx_fragqAdminLevel` | The Discord invite shown to players; `off` removes it |
| `!voice teams` / `lobby` / `<player id> red\|blue\|lobby` `[queue]` | `qlx_voicemoveperm` | [Move players in voice](#moving-players-by-hand) now |
| `!fragq` | `qlx_fragqAdminLevel` | Status, one setting per line: address, key, results and the last one sent, link required, Discord invite, queue, auto voice moves (`qlx_fragqVoice`), the last voice event and the last voice request, live status and the last live update |
| `!fragq queue` | `qlx_fragqAdminLevel` | The key's queues (channel, voice moves on or off, which one `qlx_fragqQueue` picks) and the Discord server's queues the key doesn't have |
| `!fragq url <address>` | 5 | Set the FragQ address |
| `!fragq key <key>` | 5, console / rcon only | Set the connector key |
| `!fragq test` | 5 | Check the address and the key |
| `!queueverify [dry\|status]`, `!qv` | `qlx_fragqQverifyLevel` | [Check and fix the teams](#queueverify) against the FragQ match |
| `!sub …`, `!unsub <player id>` | `qlx_fragqQverifyLevel` | [Subs](#sub-and-unsub) `!queueverify` leaves alone |
| `!whois <who>` | `qlx_fragqWhoisLevel` | [Who is behind a player](#whois): Steam and Discord accounts |

## Cvars

| Cvar | Default | Purpose |
|---|---|---|
| `qlx_fragqUrl` | | The FragQ web panel address, such as `https://fragq.example.com` |
| `qlx_fragqKey` | | The connector key |
| `qlx_fragqServerName` | `sv_hostname` | Server name shown with results |
| `qlx_fragqResults` | `1` | `0` = don't send match results |
| `qlx_fragqMinPlayers` | `2` | Fewest players a match needs for its results to be sent |
| `qlx_fragqMinShots` | `50` | Fewest shots for Highest Accuracy |
| `qlx_fragqEnforceLink` | `0` | Start value for `!linkenforce` before it is first used |
| `qlx_fragqAdminLevel` | `3` | Permission level for `!linkenforce`, `!setdiscord`, `!fragq` and linking others |
| `qlx_fragqDiscordInvite` | | Start value for `!setdiscord` before it is first used |
| `qlx_fragqVerifyTls` | `1` | `0` = accept a self-signed certificate |
| `qlx_fragqVoice` | `0` | `1` = move players between the queue's Discord voice channels ([voice moves](#voice-moves)) |
| `qlx_voicemoveperm` | `4` | Permission level for [`!voice`](#moving-players-by-hand) |
| `qlx_fragqQueue` | | The FragQ queue this server plays, in any case. Sent with voice moves and results ([several servers and queues](#several-servers-and-queues)) |
| `qlx_fragqLive` | `1` | `0` = don't send FragQ the [live status](#live-status) of running matches |
| `qlx_fragqQverifyLevel` | `qlx_fragqAdminLevel` | Permission level for `!queueverify` and `!sub` |
| `qlx_fragqWhoisLevel` | `3` | Permission level for `!whois` |
| `qlx_fragdexUrl`, `qlx_fragdexKey` | | Fragdex's address and key, for `!queueverify` and `!whois`. Shared with `fragdex.py`, whose saved values take precedence |
| `qlx_fragdexVerifyTls` | `1` | `0` = accept a self-signed certificate from Fragdex |

## Troubleshooting

| Symptom | Fix |
|---|---|
| `!fragq test`: *HTTP 401: Invalid connector key* | The key is wrong or was replaced. Set it again with `!fragq key`. |
| *HTTP 403: … can't be used from …* | The server's address isn't in the connector's **Allowed IPs**. The message shows the address FragQ saw. |
| *HTTP 401: Not logged in* or *HTTP 404: Wrong address* | The address has a path after the panel's address, such as `https://fragq.example.com/api`. Set it to the panel's address alone with `!fragq url https://fragq.example.com`. Plugin 1.2.1 and later remove the extra path themselves. |
| *Several of this connector's queues have voice moves on…* | FragQ can't tell which queue's voice channels to use. Set `qlx_fragqQueue` in `server.cfg` (a value set in the console is gone after a restart), or add the queue's name after `!voice`. Plugin 1.4.0 says this in the error itself. |
| *The queue … isn't one of this connector's queues* | The queue exists but isn't ticked on the key. Edit the connector on the **Connectors** page and tick it. Queues added or duplicated later aren't added to connectors by themselves. |
| *This connector has 2 queues named …* | Two of the key's queues, in different channels, have the same name. Give each server its own connector, or rename one. |
| *certificate verify failed* | Set `qlx_fragqVerifyTls 0` for a self-signed certificate. |
| Players aren't moved when a match starts, but `!voice` works | Run `!fragq` after a countdown and read **Last voice event**. *None since the plugin loaded* on plugin 1.3.x and older: those wait for the match to start, which some minqlxtended builds never report. Plugin 1.4.0 moves at the countdown. *Nothing sent, …* says what to change. **Auto voice moves** must be on: that is `qlx_fragqVoice 1` on the game server, not the queue's setting in FragQ. |
| Results are never sent | `zmq_stats_enable 1` is missing (needed on minqlx and minqlxtended). Check `!fragq` for the last result's status. |
| Results post without a match number | Fewer than half the match's players have linked Steam accounts, or the match is older than 6 hours, or the queue isn't one of the connector's queues. |
