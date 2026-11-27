# Result format

Any tool that can send HTTPS requests can send match results to FragQ: a game server plugin, a script
that reads the game's logs, or a bot. This page is everything you need to build one. Connectors are
in beta, and this format is version 1.

## Requests

The base address is shown on the **Connectors** page: your web panel address followed by
`/api/connect/v1`. Every request sends the connector's key:

```text
Authorization: Bearer fq_...
```

| Request | Key permission | What it does |
|---|---|---|
| `GET /status` | any | The connector's name, game, queues and permissions. Use it to test the key. `connector.queue_list` gives each of the key's queues with its channel and `voice` (voice moves on), and `connector.other_queues` the Discord server's queues the key doesn't have. |
| `POST /results` | Send match results | Send one match's result (below) |
| `POST /players/linked` | Check linked players | `{"steam_ids": ["7656…", …]}` (up to 64): which players have a linked Steam account |
| `POST /match` | Check linked players | The current matches of the connector's queues, with each player's team ([below](#current-matches)) |
| `POST /live` | Send match results | The live status of a game in progress, for `!checkmatch` ([below](#live-status)) |
| `POST /link` | Link Steam accounts from the game | `{"steam_id": "7656…", "name": "in-game name", "discord": "user id or username"}`: ask the member to confirm the link in Discord |
| `GET /steam/links` | Read linked accounts | Every link of a member of the connector's Discord server ([below](#linked-accounts)) |
| `POST /voice` | Move players in voice | Move players between a queue's voice channels ([below](#voice-moves)) |

Answers are JSON. Refused requests have `"ok": false` and an `error` message:

| Status | Why |
|---|---|
| `400` | The body is wrong; `error` says what |
| `401` | Missing or invalid key |
| `403` | The connector is disabled or expired, the request came from an address not in **Allowed IPs**, or the key isn't allowed to do this |
| `413` | Bodies are limited to 256 KB |
| `429` | The rate limit was reached; `Retry-After` says when to try again |

Don't send a `4xx` request again unchanged (except `429`). Do retry when FragQ couldn't be reached or
answered `5xx`, with the same `match_uid`, so the result is posted once.

## Current matches

`POST /match` lists the FragQ matches a game server can be playing now, so it can check who belongs on its teams
(the Quake Live plugin's [`!queueverify`](quake-live.md#queueverify)). The body is optional:
`{"queue": "CA"}` (any case) limits it to one of the connector's queues.

```json
{
  "ok": true,
  "matches": [
    {
      "match_id": 1234, "queue": "CA", "state": "waiting_report", "finished": false, "started_at": 1795750000,
      "team_names": ["Alpha", "Beta"],
      "players": [
        {"discord_id": "2000…", "discord_name": "sk1nner", "steam_id": "7656…", "team": 0},
        {"discord_id": "2000…", "discord_name": "st01c", "steam_id": null, "team": 1}
      ]
    }
  ]
}
```

| Field | |
|---|---|
| `state` | `check_in`, `draft` or `waiting_report` for a match still in FragQ; `started` for an unranked match from the match history |
| `finished` | `false` for a match still in FragQ. An unranked match leaves FragQ as soon as its teams are set, so unranked matches that started in the last 2 hours are listed too, with `"finished": true` |
| `team` | `0` or `1`, FragQ's two teams (not the game's red and blue), or `null` while unpicked |
| `steam_id` | The player's linked Steam account, or `null` |

Newest first. A queue name the connector doesn't have is refused with `400`.

## Live status

`POST /live` tells FragQ how a game in progress stands, so `!checkmatch` / `/checkmatch` can show it in Discord.
It works for any game: the fields are the same kind as a result's, and what a game puts in `period`, `stats` and
`note` is up to it. Send it when something changes (a round ends, the score changes, a team changes) and every
minute or so while the game runs, at most every few seconds.

```json
{
  "version": 1,
  "match_uid": "6f1c0a52-…",
  "state": "live",
  "map": "campgrounds", "mode": "CA", "server": "CA #1",
  "elapsed": 412,
  "period": {"label": "Round", "current": 7, "limit": 10},
  "teams": [{"name": "Red", "score": 4}, {"name": "Blue", "score": 2}],
  "players": [
    {"id": "76561198000000001", "name": "st01c", "team": "Red", "alive": true, "stats": {"K": 12, "D": 4, "Dmg": 2345}}
  ],
  "table": ["K", "D", "Dmg"],
  "note": "Blue is down to one player"
}
```

| Field | |
|---|---|
| `state` | `warmup`, `countdown`, `live`, `overtime`, `intermission` or `ended` |
| `elapsed` | Seconds since the game started |
| `period` | Where the game is: `{"label": "Round", "current": 7, "limit": 10}`, `{"label": "Half", "current": 2}`, `{"label": "Map", "current": 2, "limit": 3}`… |
| `teams`, `players`, `table` | As in a [result](#a-result): players by Steam ID, Discord id or name, each with free-form `stats` (up to 24) and the columns to show in `table` (up to 8). `alive: false` shows 💀 |
| `match_uid`, `fragq_match_id`, `queue` | Find the FragQ match, as for a result. Send the same `match_uid` with the final result: the result then replaces the live status |
| `note`, `server` | Free text, shown with the status |

Only `version` and one of `state`, `teams` or `players` are needed. FragQ keeps the latest status of each match in
memory: it shows as stale after 3 minutes without an update and is forgotten after 15. The answer says
`"status": "matched"` with the FragQ `match_id`, or `"unmatched"`; an unmatched game still shows in `!checkmatch`
in the channels of the connector's queues, as *not linked to a FragQ match*.

Besides `!checkmatch`, the live status shows on the web panel's [Live tab](../web-panel/live-and-stats.md#live), on a
[QueueGen](../administration/queuegen.md) event's message and card, and the **Connectors** page marks a connector
that sends it with **Live status** and its last update.

## Voice moves

`POST /voice` moves players between the Discord voice channels of one of the connector's queues, which needs
[voice moves](../administration/voice.md) turned on for that queue. Send each team's players by SteamID64,
and the players who should go back to the lobby. Up to 64 players and two teams per request:

```json
{
  "teams": {"red": ["76561198000000001", "76561198000000002"], "blue": ["76561198000000003"]},
  "lobby": [],
  "queue": "CA"
}
```

`queue` is optional, and not case-sensitive (`ca` finds *CA*). Without it, FragQ uses the queue of the FragQ
match these players are in, or the connector's only queue with voice moves on; if several of the connector's
queues have voice moves on and no match is found, the answer is `400` and nobody is moved. A name that none of
the connector's queues has, or that two of them share (in different channels), is also refused with `400`. Team names can be anything; FragQ
[matches them to the team channels](../administration/voice.md#game-servers) and keeps that choice for the
rest of the match. FragQ only moves members who are already in the queue's Lobby or team channels.

```json
{
  "ok": true,
  "queue": "CA",
  "match_id": 9024,
  "teams": {"red": "🔴 Red Team", "blue": "🔵 Blue Team"},
  "players": [
    {"steam_id": "76561198000000001", "discord_name": "username", "status": "moved", "channel": "🔴 Red Team", "fragdex": false},
    {"steam_id": "76561198000000002", "discord_name": null, "status": "not_linked", "channel": "🔴 Red Team", "fragdex": false}
  ]
}
```

`status` is one of `moved`, `already_there`, `not_in_voice`, `other_channel`, `not_linked`, `not_member`,
`no_permission`, `failed` or `in_series` (a Lobby move skipped between a [series](../playing/matches.md#series)' games; see [Voice moves](../administration/voice.md#when-nobody-moves)). The answer is
`409` when none of the connector's queues has voice moves on.

Each player also has `"fragdex": true` when FragQ found them with a
[Fragdex lookup](../administration/settings-page.md#fragdex) rather than a FragQ link, and `false` otherwise.
`POST /players/linked` answers the same way, next to `linked`, `member`, `discord_name` and `confirming`.

## Linked accounts

`GET /steam/links` lists the links of the members of the connector's Discord server. Pending account
changes aren't included. If the bot can't see the server right now, the answer is `503`.

```json
{
  "ok": true,
  "links": [
    {
      "steam_id": "76561198000000000",
      "discord_id": "200000000000000001",
      "discord_name": "username",
      "persona": "Steam name",
      "verified_by": "steam",
      "linked_at": 1794194577
    }
  ]
}
```

`discord_id` is always a string. `persona` and `linked_at` can be `null`. `verified_by` is `""` for a
link the player only typed in, `"game"` for `!link` confirmed in Discord, and `"steam"` for a Steam
sign-in on the [`/verify` page](../administration/steam.md#the-verify-page).

## A result

```json
{
  "version": 1,
  "match_uid": "6f1c0a52-…",
  "game": "Quake Live",
  "map": "campgrounds",
  "mode": "CA",
  "duration": 612,
  "server": "EU CA #1",
  "teams": [{ "name": "Red", "score": 8 }, { "name": "Blue", "score": 5 }],
  "winner": "Red",
  "players": [
    { "id": "76561198000000001", "id_type": "steam", "name": "st01c", "team": "Red",
      "stats": { "Score": 52, "K": 21, "D": 9, "Dmg": 3214, "Acc": "41%" } },
    { "id": "76561198000000002", "id_type": "steam", "name": "flood", "team": "Blue", "quit": true,
      "stats": { "Score": 12, "K": 4, "D": 11, "Dmg": 980, "Acc": "28%" } }
  ],
  "highlights": [
    { "label": "Top Damage", "player": "76561198000000001", "value": 3214 },
    { "label": "Quitters", "players": ["76561198000000002"] }
  ],
  "table": ["Score", "K", "D", "Dmg", "Acc"]
}
```

Only `players` is required. Everything else is optional; leave out what your game doesn't have.

| Field | Type | Meaning |
|---|---|---|
| `version` | `1` | The format version |
| `match_uid` | text, ≤ 100 | The game's own id for this match. A result with a `match_uid` the connector already sent is not posted again (the answer says `duplicate`). |
| `game` | text | Shown in the footer instead of the connector's game |
| `title` | text | Title for results that don't belong to a FragQ match (default *Match results*) |
| `map`, `mode`, `server` | text | Shown under the score |
| `duration` | seconds | Match length, shown as `10:12` |
| `queue` | text | A queue name, in any case: only look for the FragQ match in this one of the connector's queues |
| `fragq_match_id` | number | The FragQ match number, if your tool knows it. Skips the matching by players. |
| `teams` | up to 4 `{name, score}` | Teams and scores. With two scored teams, the score is shown as *Red 8 – 5 Blue*. |
| `winner` | text or `null` | The winning team's name; `null` with equal scores shows *Draw* |
| `players` | up to 64 | See below |
| `highlights` | up to 12 | See below |
| `table` | up to 6 stat names | Columns of the per-team players table, in order |

### Players

| Field | Meaning |
|---|---|
| `id` | The player's id in `id_type` |
| `id_type` | `steam` (a SteamID64), `discord` (a Discord user id) or `name`. Default: `steam` for a SteamID64, otherwise `name`. Steam and Discord ids let FragQ match the result to a FragQ match and show the Discord name. |
| `name` | The in-game name, used when FragQ doesn't know the player |
| `team` | The name of their team in `teams` |
| `quit` | `true` if they left before the end: shown as *(left)* in the table |
| `stats` | Up to 24 `"name": value` pairs. Numbers get thousands separators; text is shown as sent, so format percentages and times yourself. |

### Highlights

A highlight is a labelled award, shown side by side above the table. Your tool decides what they
are and who gets them.

| Field | Meaning |
|---|---|
| `label` | Such as *Top Damage* or *Most Headshots* |
| `player` or `players` | The `id` of one player, or a list for ties. They must be in `players`. |
| `value` | Optional, shown after the names: `3214` → *3,214* |

A highlight with only a `value` (such as `{"label": "Quitters", "value": "None"}`) shows the value.

## Answer

```json
{ "ok": true, "status": "posted", "result_id": 12, "match_id": 9024, "queue": "4v4-pickup", "posted": true }
```

`status` is `posted`, `stored` (no FragQ match, and the connector doesn't post those) or `duplicate`.
`match_id` is the FragQ match the result was attached to, or `null`. During a
[series](../playing/matches.md#series), `series` gives the game the result counted as, such as
`{"game": 2, "of": 3}`; otherwise it is `null`.

## Examples

```bash
curl -H "Authorization: Bearer fq_..." https://fragq.example.com/api/connect/v1/status
```

```bash
curl -H "Authorization: Bearer fq_..." -H "Content-Type: application/json" \
  -d '{"version":1,"players":[{"id":"76561198000000001","name":"st01c","stats":{"Kills":21}}],"table":["Kills"]}' \
  https://fragq.example.com/api/connect/v1/results
```

```python
import json, urllib.request

def send_result(base, key, result):
    req = urllib.request.Request(
        base + "/results", data=json.dumps(result).encode(), method="POST",
        headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read())

print(send_result("https://fragq.example.com/api/connect/v1", "fq_...", {
    "version": 1, "match_uid": "my-server-2026-11-02-1932", "map": "Mirage", "mode": "Competitive",
    "teams": [{"name": "CT", "score": 13}, {"name": "T", "score": 9}], "winner": "CT",
    "players": [{"id": "76561198000000001", "name": "st01c", "team": "CT", "stats": {"K": 24, "HS": "58%"}}],
    "highlights": [{"label": "Most Headshots", "player": "76561198000000001", "value": 14}],
    "table": ["K", "HS"],
}))
```

The [Quake Live plugin](https://github.com/D00MSDAYDEVICE/fragq/blob/main/app/plugins/minqlx/fragq.py)
is a complete example, including retries and the linked-player check.
