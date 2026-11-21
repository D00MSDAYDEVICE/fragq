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

With `qlx_fragqVoice 1`, the plugin sends FragQ the teams when a match starts and a few seconds after team
changes, and sends the players back to the lobby when the match ends or is aborted (`!abort` or an abort
vote). FragQ then moves them between the queue's Discord voice channels. It needs:

- [voice moves](../administration/voice.md) turned on for the queue, with its three voice channels set;
- the **Move players in voice** permission on the connector;
- players' Steam accounts linked to Discord.

The red team goes to the team channel with *red* in its name and blue to the one with *blue*; with other
channel names, see [how FragQ decides](../administration/voice.md#game-servers). Only team modes (CA, TDM,
CTF and so on) send teams. `!fragq` shows the result of the last request.

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
that has several queues, set each server's queue:

```text
set qlx_fragqQueue "CA"
```

`qlx_fragqQueue` is sent with match results too, so FragQ only looks for the match in that queue. `!fragq test`
warns when the key has no queue of that name, or two of them (in different channels).

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

## Commands

| Command | Permission | What it does |
|---|---|---|
| `!link <discord id>` | everyone | Link your Steam account |
| `!link <player id> <discord id>` | `qlx_fragqAdminLevel` | Link another player's account |
| `!linkenforce [on\|off]` | `qlx_fragqAdminLevel` | Require linked Steam accounts to play |
| `!setdiscord <invite URL>` | `qlx_fragqAdminLevel` | The Discord invite shown to players; `off` removes it |
| `!voice teams` / `lobby` / `<player id> red\|blue\|lobby` `[queue]` | `qlx_voicemoveperm` | [Move players in voice](#moving-players-by-hand) now |
| `!fragq` | `qlx_fragqAdminLevel` | Status: address, key, last result sent |
| `!fragq url <address>` | 5 | Set the FragQ address |
| `!fragq key <key>` | 5, console / rcon only | Set the connector key |
| `!fragq test` | 5 | Check the address and the key |

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

## Troubleshooting

| Symptom | Fix |
|---|---|
| `!fragq test`: *HTTP 401: Invalid connector key* | The key is wrong or was replaced. Set it again with `!fragq key`. |
| *HTTP 403: … can't be used from …* | The server's address isn't in the connector's **Allowed IPs**. The message shows the address FragQ saw. |
| *HTTP 401: Not logged in* or *HTTP 404: Wrong address* | The address has a path after the panel's address, such as `https://fragq.example.com/api`. Set it to the panel's address alone with `!fragq url https://fragq.example.com`. Plugin 1.2.1 and later remove the extra path themselves. |
| *Several of this connector's queues have voice moves on…* | Set `qlx_fragqQueue`, or add the queue's name after `!voice`. |
| *This connector has 2 queues named …* | Two of the key's queues, in different channels, have the same name. Give each server its own connector, or rename one. |
| *certificate verify failed* | Set `qlx_fragqVerifyTls 0` for a self-signed certificate. |
| Results are never sent | `zmq_stats_enable 1` is missing (needed on minqlx and minqlxtended). Check `!fragq` for the last result's status. |
| Results post without a match number | Fewer than half the match's players have linked Steam accounts, or the match is older than 6 hours, or the queue isn't one of the connector's queues. |
