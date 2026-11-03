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
| `GET /status` | any | The connector's name, game, queues and permissions. Use it to test the key. |
| `POST /results` | Send match results | Send one match's result (below) |
| `POST /players/linked` | Check linked players | `{"steam_ids": ["7656…", …]}` (up to 64): which players have a linked Steam account |
| `POST /link` | Link Steam accounts from the game | `{"steam_id": "7656…", "name": "in-game name", "discord": "user id or username"}`: ask the member to confirm the link in Discord |

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
| `queue` | text | A queue name: only look for the FragQ match in this one of the connector's queues |
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
`match_id` is the FragQ match the result was attached to, or `null`.

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
