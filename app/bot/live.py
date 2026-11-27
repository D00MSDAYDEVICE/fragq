# -*- coding: utf-8 -*-
"""
Live status of running matches, for !checkmatch / !cm and /checkmatch.

Any game can report: a game server, plugin or script sends a game-neutral snapshot to the connector API
(POST /live, with the key's Send match results permission), in the same terms as a result: teams with names and
scores, players with ids, teams and free-form stats, plus map, mode, state, elapsed time and a period ("Round 7 of
10", "Half 2", "Map 2 of 3"). FragQ ties it to the FragQ match the way it ties results (bot.connectors.find_match)
and keeps the latest snapshot per match in memory: live data is short-lived and comes back with the next update
after a restart.

!checkmatch shows every match in progress on the channel (and the running QueueGen events of the server) with
whatever is known: the live snapshot when a game server sends one, otherwise FragQ's own view of the match (teams,
stage, how long ago it started) and a note that no live data is coming in. Queues of any game work; only the
detail depends on what their game server sends.
"""
import time

from nextcord import Embed, Colour

from core.client import dc
from core.database import db
from core.utils import get_nick

import bot

STALE = 180               # seconds without an update before a snapshot is shown as stale
DROP = 900                # ... before it's forgotten
ENDED_DROP = 300          # an ended game's last snapshot is kept this long
STATES = ("warmup", "countdown", "live", "overtime", "intermission", "ended")
STATE_LABELS = dict(warmup="⏳ warmup", countdown="⏱️ countdown", live="🟢 live", overtime="🔥 overtime",
					intermission="⏸️ intermission", ended="🏁 ended")
COOLDOWN = 5              # seconds between !checkmatch replies in a channel
MAX_MATCHES = 6           # shown in one reply (an embed has at most 25 fields)
RECENT_UNRANKED = 1800    # an unranked match without live data is shown this long after it starts

_by_match = {}            # FragQ match id -> entry
_unmatched = {}           # connector id -> entry: a game this connector reports that matches no FragQ match
_uid = {}                 # (connector id, match_uid) -> FragQ match id, so updates skip the search
_last_reply = {}          # channel id -> time of the last !checkmatch reply
_seen = {}                # connector id -> time of its last live status (Connectors page)


# ------------------------------------------------------------------ receiving (POST /live)

def normalize(data):
	""" Check a live snapshot and return it in the stored form; raises ValueError with what is wrong. """
	c = bot.connectors
	if not isinstance(data, dict):
		raise ValueError("The body must be a JSON object.")
	if data.get("version", 1) != 1:
		raise ValueError("Unsupported live status version: this FragQ reads version 1.")
	out = dict(version=1)
	for key, limit in (("match_uid", 100), ("map", 60), ("mode", 40), ("server", 80), ("queue", 60), ("note", 200)):
		out[key] = c._text(data.get(key), limit)
	state = data.get("state")
	if state is not None and state not in STATES:
		raise ValueError(f"'state' must be one of: {', '.join(STATES)}.")
	out["state"] = state
	e = data.get("elapsed")
	out["elapsed"] = int(e) if isinstance(e, (int, float)) and not isinstance(e, bool) and 0 <= e <= 7 * 86400 else None
	m = data.get("fragq_match_id")
	out["fragq_match_id"] = int(m) if isinstance(m, int) and not isinstance(m, bool) and m > 0 else None

	period = data.get("period")
	out["period"] = None
	if period is not None:
		if not isinstance(period, dict) or not c._text(period.get("label"), 20):
			raise ValueError("'period' must be an object with a 'label', such as {\"label\": \"Round\", \"current\": 7, \"limit\": 10}.")
		num = [period.get(k) if isinstance(period.get(k), int) and not isinstance(period.get(k), bool) and 0 <= period.get(k) <= 100000 else None
			   for k in ("current", "limit")]
		out["period"] = dict(label=c._text(period["label"], 20), current=num[0], limit=num[1])

	teams = []
	for t in c._list(data, "teams", 4):
		if not isinstance(t, dict) or not c._text(t.get("name"), 40):
			raise ValueError("Every team needs a 'name'.")
		score = t.get("score")
		teams.append(dict(name=c._text(t["name"], 40), score=c._value(score, 12) if score is not None else None))
	out["teams"] = teams

	players = []
	for p in c._list(data, "players", 64):
		if not isinstance(p, dict):
			raise ValueError("Every player must be an object.")
		pid, name = c._text(p.get("id"), 32), c._text(p.get("name"), 64)
		if not pid and not name:
			raise ValueError("Every player needs an 'id' or a 'name'.")
		kind = p.get("id_type") or ("steam" if pid and c.STEAM_RE.match(pid) else "discord" if pid and pid.isdigit() else "name")
		if kind not in ("steam", "discord", "name"):
			raise ValueError("A player's 'id_type' must be 'steam', 'discord' or 'name'.")
		if kind == "steam" and not (pid and c.STEAM_RE.match(pid)):
			raise ValueError(f"'{pid}' is not a SteamID64.")
		stats = p.get("stats") or {}
		if not isinstance(stats, dict) or len(stats) > 24:
			raise ValueError("A player's 'stats' must be an object with at most 24 entries.")
		clean = {}
		for k, v in stats.items():
			label, shown = c._text(k, 24), c._value(v)
			if label and shown is not None:
				clean[label] = shown
		alive = p.get("alive")
		players.append(dict(id=pid or name, id_type=kind, name=name or pid, team=c._text(p.get("team"), 40),
							alive=alive if isinstance(alive, bool) else None, stats=clean))
	out["players"] = players
	table = [c._text(x, 24) for x in c._list(data, "table", 8)]
	out["table"] = [x for x in table if x]
	if not (out["state"] or teams or players):
		raise ValueError("Send at least a 'state', 'teams' or 'players'.")
	return out


async def receive(c, data):
	""" POST /live from a connector: store the snapshot under its FragQ match. """
	try:
		snap = normalize(data)
	except ValueError as e:
		raise bot.connectors.ConnectorError(400, str(e))
	now = time.time()
	key = (c["id"], snap["match_uid"]) if snap["match_uid"] else None
	match_id = _uid.get(key) if key else None
	if match_id is None:
		found = await bot.connectors.find_match(c, snap)
		match_id = found["match_id"] if found else None
		if match_id is not None and key:
			_uid[key] = match_id
	entry = dict(snap=snap, at=now, connector_id=c["id"], connector=c["name"], game=c["game"])
	_seen[c["id"]] = now
	if match_id is not None:
		_by_match[match_id] = entry
		_unmatched.pop(c["id"], None)
	else:
		_unmatched[c["id"]] = entry
	return dict(ok=True, status="matched" if match_id is not None else "unmatched", match_id=match_id)


def result_in(c, result, match):
	""" A final result came in (bot.connectors.receive): its live snapshot has done its job. """
	if match is not None:
		_by_match.pop(match["match_id"], None)
	if result.get("match_uid"):
		_uid.pop((c["id"], result["match_uid"]), None)
		for mid, e in list(_by_match.items()):
			if e["connector_id"] == c["id"] and e["snap"]["match_uid"] == result["match_uid"]:
				_by_match.pop(mid, None)
	u = _unmatched.get(c["id"])
	if u and (not result.get("match_uid") or u["snap"]["match_uid"] == result["match_uid"]):
		_unmatched.pop(c["id"], None)


def forget_connector(cid):
	""" A connector was deleted: what it reported goes with it (its id may be given to a new one). """
	_unmatched.pop(cid, None)
	_seen.pop(cid, None)
	for mid, e in list(_by_match.items()):
		if e["connector_id"] == cid:
			_by_match.pop(mid, None)
	for k in [k for k in _uid if k[0] == cid]:
		_uid.pop(k, None)


def think(frame_time):
	for store in (_by_match, _unmatched):
		for k, e in list(store.items()):
			limit = ENDED_DROP if e["snap"]["state"] == "ended" else DROP
			if frame_time - e["at"] > limit:
				store.pop(k, None)
	if len(_uid) > 500:
		_uid.clear()


def for_match(match_id):
	return _by_match.get(match_id)


def last_seen(cid):
	""" When this connector last sent a live status (since FragQ started), or None. """
	return _seen.get(cid)


def period_text(p):
	if not p:
		return None
	if p["current"] is None:
		return p["label"]
	return f"{p['label']} {p['current']}" + (f"/{p['limit']}" if p["limit"] else "")


def score_text(s, bold=False):
	b = "**" if bold else ""
	return " — ".join(f"{b}{t['name']} {t['score'] if t['score'] is not None else '–'}{b}" for t in s["teams"])


def groups(s, guild):
	""" The snapshot's players by team, in the teams' order: [(team name, score or None, [(shown name, player)])]. """
	names = bot.connectors._shown_names(s, guild)
	order = [t["name"] for t in s["teams"]]
	for p in s["players"]:
		if p["team"] and p["team"] not in order:
			order.append(p["team"])
	score = {t["name"]: t["score"] for t in s["teams"]}
	out = [(t, score.get(t), [(names.get(p["id"], p["name"]), p) for p in s["players"] if p["team"] == t]) for t in order]
	rest = [(names.get(p["id"], p["name"]), p) for p in s["players"] if not p["team"] or p["team"] not in order]
	if rest:
		out.append(("Players", None, rest))
	return [g for g in out if g[2]]


def web_dict(match_id, guild):
	""" A match's live status for the web panel's Live tab, or None. """
	e = _by_match.get(match_id)
	if e is None:
		return None
	s, now = e["snap"], time.time()
	columns = s["table"] or sorted({k for p in s["players"] for k in p["stats"]})[:8]
	return dict(
		state=s["state"], state_label=STATE_LABELS.get(s["state"]) if s["state"] else None,
		period=period_text(s["period"]), clock=_clock(s["elapsed"]) if s["elapsed"] is not None else None,
		map=s["map"], mode=s["mode"], note=s["note"], server=s["server"] or e["connector"],
		teams=s["teams"], columns=columns, age=int(now - e["at"]), stale=now - e["at"] > STALE,
		groups=[dict(name=name, score=score, players=[dict(name=n, dead=p.get("alive") is False,
															 stats=[p["stats"].get(c, "") for c in columns]) for n, p in players])
				for name, score, players in groups(s, guild)],
	)


def summary(match_id, clock=False):
	"""
	A few lines for a QueueGen event message: '🟢 live · Round 7/10', the score, the map; or None. Without the
	clock by default, so the message only changes when the game's state, period or score does.
	"""
	e = _by_match.get(match_id)
	if e is None:
		return None
	s = e["snap"]
	parts = [STATE_LABELS.get(s["state"]) if s["state"] else "📡 live", period_text(s["period"]),
			 _clock(s["elapsed"]) if clock and s["elapsed"] is not None else None]
	line = " · ".join(x for x in parts if x)
	if s["teams"]:
		line += "\n" + score_text(s, bold=True)
	if s["map"]:
		line += f"\n{s['map']}" + (f" · {s['mode']}" if s["mode"] else "")
	return line


# ------------------------------------------------------------------ what !checkmatch shows

async def _recent_unranked(qc):
	""" Unranked matches of the channel that started within LIVE_WINDOW: they leave FragQ when they start. """
	rows = await db.fetchall(
		"SELECT m.match_id, m.queue_id, m.queue_name, m.alpha_name, m.beta_name, m.at, p.user_id, p.nick, p.team "
		"FROM `qc_matches` AS m JOIN `qc_player_matches` AS p ON p.match_id=m.match_id AND p.channel_id=m.channel_id "
		"WHERE m.ranked=0 AND m.at>=%s AND m.channel_id=%s",
		(int(time.time()) - bot.connectors.LIVE_WINDOW, qc.id)
	)
	out = {}
	for r in rows:
		m = out.setdefault(r["match_id"], dict(match_id=r["match_id"], queue=r["queue_name"], qc=qc, started=r["at"],
												stage="started", team_names=[r["alpha_name"], r["beta_name"]], teams=[[], []], event=None))
		if r["team"] in (0, 1):
			m["teams"][int(r["team"])].append(r["user_id"])
	return list(out.values())


def _from_match(m, event=None):
	stage = {m.CHECK_IN: "check-in", m.DRAFT: "draft", m.WAITING_REPORT: "in progress"}.get(m.state, "starting")
	return dict(match_id=m.id, queue=m.queue.name, qc=m.qc, started=m.start_time, stage=stage, event=event,
				team_names=[m.teams[0].name, m.teams[1].name], teams=[[p.id for p in m.teams[i] if p] for i in (0, 1)])


async def candidates(qc):
	""" Matches !checkmatch can show from this channel: its own, recent unranked ones, and running QueueGen events. """
	seen, out = set(), []
	for m in bot.active_matches:
		if m.qc is qc:
			out.append(_from_match(m, bot.queuegen.for_queue(m.queue)))
			seen.add(m.id)
	now = time.time()
	for m in await _recent_unranked(qc):
		# FragQ doesn't know when an unranked game ends: show it while its game server reports, or while it's fresh
		if m["match_id"] not in seen and (m["match_id"] in _by_match or now - (m["started"] or 0) < RECENT_UNRANKED):
			out.append(m)
			seen.add(m["match_id"])
	for ev in bot.queuegen.guild_events(qc.guild_id):
		if ev["state"] != "live" or ev["data"].get("channel_id") == qc.id:
			continue
		m = next((x for x in bot.active_matches if x.id == ev["data"].get("match_id")), None)
		if m is not None and m.id not in seen:
			out.append(_from_match(m, ev))
			seen.add(m.id)
	return out


def choices(qc, typed=""):
	""" /checkmatch suggestions: the channel's queues, its matches, and running QueueGen events. """
	typed = (typed or "").casefold().lstrip("#")
	opts = [q.name for q in qc.queues]
	opts += [f"#{m.id} · {m.queue.name}" for m in bot.active_matches if m.qc is qc]
	opts += [f"🏆 {ev['data']['name']}" for ev in bot.queuegen.guild_events(qc.guild_id)
			 if ev["state"] in ("open", "live") and ev["data"].get("channel_id") != qc.id]
	return [o for o in opts if typed in o.casefold()][:25]


def _pick(cands, target):
	""" The matches a !checkmatch argument names: a match number, a queue name or a QueueGen event's name. """
	t = (target or "").strip()
	if not t:
		return cands
	t = t[1:].strip() if t.startswith("🏆") else t
	num = t.lstrip("#").split(" ")[0]
	if num.isdigit():
		return [m for m in cands if m["match_id"] == int(num)]
	low = t.casefold()
	return [m for m in cands if (m["queue"] or "").casefold() == low or (m["event"] and m["event"]["data"]["name"].casefold() == low)] \
		or [m for m in cands if low in (m["queue"] or "").casefold() or (m["event"] and low in m["event"]["data"]["name"].casefold())]


def _ago(seconds):
	seconds = max(0, int(seconds))
	if seconds < 60:
		return f"{seconds}s"
	if seconds < 3600:
		return f"{seconds // 60} min"
	return f"{seconds // 3600}h{(seconds % 3600) // 60:02}"


def _clock(seconds):
	m, s = divmod(int(seconds), 60)
	h, m = divmod(m, 60)
	return f"{h}:{m:02}:{s:02}" if h else f"{m}:{s:02}"


def _stats_line(p, columns):
	keys = columns or list(p["stats"])
	parts = [f"{k} {p['stats'][k]}" for k in keys if k in p["stats"]][:8]
	return " · ".join(parts)


def _player_line(name, p, columns):
	dead = " 💀" if p and p.get("alive") is False else ""
	stats = _stats_line(p, columns) if p else ""
	return f"**{name}**{dead}" + (f" — {stats}" if stats else "")


def _section(guild, m, now):
	""" (header field, [team fields]) for one match. """
	entry = _by_match.get(m["match_id"])
	ev = m["event"]
	label = f"🏆 {ev['data']['name']}" if ev else (m["queue"] or "?")
	game = bot.connectors.GAME.get(entry["game"]) if entry else None
	icon = game[2] if game else "🎮"
	head = [f"{label} · Match #{m['match_id']}" if ev else f"{icon} {label} · Match #{m['match_id']}"]
	lines = []
	if entry:
		s = entry["snap"]
		head.append(STATE_LABELS.get(s["state"], "📡 live data") if s["state"] else "📡 live data")
		if s["period"]:
			head.append(period_text(s["period"]))
		if s["elapsed"] is not None:
			head.append(_clock(s["elapsed"]))
		if s["teams"]:
			lines.append(score_text(s, bold=True))
		where = " · ".join(x for x in (s["map"], s["mode"]) if x)
		if where:
			lines.append(where)
		if s["note"]:
			lines.append(f"*{s['note']}*")
		age = now - entry["at"]
		by = s["server"] or entry["connector"]
		lines.append(f"Updated {_ago(age)} ago by {by}" + (" · ⚠️ stale, the game server stopped reporting" if age > STALE else ""))
	else:
		head.append(m["stage"])
		if m["started"]:
			lines.append(f"started {_ago(now - m['started'])} ago" +
						 (" (FragQ doesn't follow unranked games once they start)" if m["stage"] == "started" else ""))
		lines.append("📡 No live data: this queue's game server doesn't send live status.")
	header = (" · ".join(head)[:256], "\n".join(lines)[:1024] or "—")

	teams = []
	if entry and entry["snap"]["players"]:
		s = entry["snap"]
		for name, score, players in groups(s, guild):
			title = f"{name} ({score})" if score is not None else name
			body = "\n".join(_player_line(shown, p, s["table"]) for shown, p in players)
			teams.append((title[:256], body[:1024]))
	else:
		for i in (0, 1):
			if not m["teams"][i]:
				continue
			names = [get_nick(guild.get_member(uid)) if guild and guild.get_member(uid) else str(uid) for uid in m["teams"][i]]
			teams.append((str(m["team_names"][i] or f"Team {i + 1}")[:256], "\n".join(f"**{n}**" for n in names)[:1024]))
	return header, teams


def build_embed(guild, qc, matches, unmatched=()):
	now = time.time()
	e = Embed(title="📡 Match status", colour=Colour(0x1ff2a2))
	total = 0
	for m in matches[:MAX_MATCHES]:
		header, teams = _section(guild, m, now)
		if len(e.fields) + 1 + len(teams) > 25 or total + sum(len(a) + len(b) for a, b in [header] + teams) > 5500:
			break
		e.add_field(name=header[0], value=header[1], inline=False)
		for name, value in teams:
			e.add_field(name=name, value=value, inline=True)
		total += sum(len(a) + len(b) for a, b in [header] + teams)
	for entry in unmatched:
		if len(e.fields) >= 25:
			break
		s = entry["snap"]
		score = score_text(s)
		e.add_field(name=f"🎮 {s['server'] or entry['connector']} · not linked to a FragQ match"[:256],
					value=" · ".join(x for x in (STATE_LABELS.get(s["state"]), score, s["map"]) if x)[:1024] or "—", inline=False)
	hidden = len(matches) - MAX_MATCHES
	foot = "Live data comes from the game servers' connectors."
	if hidden > 0:
		foot = f"{hidden} more match(es): name one with !checkmatch <match number or queue>. " + foot
	e.set_footer(text=foot)
	return e


async def unmatched_for(qc):
	""" Games the connectors of this channel's queues report that match no FragQ match. """
	ids = {q.id for q in qc.queues}
	out = []
	for cid, entry in _unmatched.items():
		c = bot.connectors.connectors.get(cid)
		if c and ids & set(c["queues"]):
			out.append(entry)
	return out


async def check(ctx, target=None):
	""" !checkmatch / !cm / /checkmatch: the status of the matches in progress. """
	now = time.time()
	if now - _last_reply.get(ctx.qc.id, 0) < COOLDOWN and not target:
		raise bot.Exc.PermissionError(f"Match status was just posted: try again in {int(COOLDOWN - (now - _last_reply[ctx.qc.id])) + 1}s.")
	guild = dc.get_guild(ctx.qc.guild_id)
	cands = await candidates(ctx.qc)
	matches = _pick(cands, target)
	unmatched = await unmatched_for(ctx.qc) if not target else []
	if not matches and not unmatched:
		if target:
			raise bot.Exc.NotFoundError(f"No match in progress matches '{str(target)[:40]}'.")
		raise bot.Exc.NotFoundError(ctx.qc.gt("> no active matches"))
	matches.sort(key=lambda m: (m["match_id"] not in _by_match, -(m["started"] or 0)))
	_last_reply[ctx.qc.id] = now
	await ctx.reply(embed=build_embed(guild, ctx.qc, matches, unmatched))
