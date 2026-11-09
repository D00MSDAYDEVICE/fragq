# -*- coding: utf-8 -*-
"""
Game connectors (beta): game servers and tools send match results to FragQ over HTTPS.

A connector belongs to one Discord server and serves one or more of its queues. It has a secret key
(shown once; only its SHA-256 is stored) and settings that can change without a new key: what the key
may do, allowed IPs, a rate limit and an expiry date.

FragQ doesn't know any game. A result is a small JSON document with teams, players and their stats,
and "highlights" (Top Damage, Most Headshots, ...) worked out by the game's own plugin. FragQ finds the
FragQ match it belongs to from the players' linked Steam accounts and posts what it was given in that
queue's channel. Every game needs its own tool (a server plugin, a log reader, a script) to send it.

Players can also link their Steam account from a game server (!link in the minqlx plugin). The game
server vouches for the Steam account; FragQ sends the Discord member a direct message to confirm it.
"""
import datetime as dt
import hashlib
import ipaddress
import json
import math
import re
import secrets
import threading
import time

from nextcord import Embed, Colour, ButtonStyle, AllowedMentions, DiscordException
from nextcord.ui import View, Button
from nextcord.utils import escape_markdown

from core.client import dc
from core.config import __version__
from core.console import log
from core.database import db
from core.utils import get_nick, error_embed, ok_embed

import bot

db.ensure_table(dict(
	tname="fragq_connectors",
	columns=[
		dict(cname="id", ctype=db.types.int, autoincrement=True),
		dict(cname="guild_id", ctype=db.types.int),
		dict(cname="name", ctype=db.types.str),
		dict(cname="game", ctype=db.types.str),
		dict(cname="queues", ctype=db.types.text),           # JSON list of queue ids
		dict(cname="unmatched_queue", ctype=db.types.int),   # where results without a FragQ match go; 0 = nowhere
		dict(cname="prefix", ctype=db.types.str),
		dict(cname="key_hash", ctype=db.types.str),
		dict(cname="can_results", ctype=db.types.bool),
		dict(cname="can_check", ctype=db.types.bool),
		dict(cname="can_link", ctype=db.types.bool),
		dict(cname="can_export", ctype=db.types.bool),       # read every linked account of the server (Fragdex)
		dict(cname="allowed_ips", ctype=db.types.text),      # space separated IPs / CIDR ranges; empty = any
		dict(cname="rate_limit", ctype=db.types.int),        # requests per minute; 0 = unlimited
		dict(cname="expires_at", ctype=db.types.str),        # last valid day (UTC, YYYY-MM-DD); empty = never
		dict(cname="disabled", ctype=db.types.bool),
		dict(cname="requests", ctype=db.types.int),
		dict(cname="last_used_at", ctype=db.types.int),
		dict(cname="last_used_ip", ctype=db.types.str),
		dict(cname="last_denied_at", ctype=db.types.int),
		dict(cname="last_denied_ip", ctype=db.types.str),
		dict(cname="last_denied_reason", ctype=db.types.str),
		dict(cname="created_by", ctype=db.types.int),
		dict(cname="created_by_name", ctype=db.types.str),
		dict(cname="created_at", ctype=db.types.int),
		dict(cname="updated_at", ctype=db.types.int),
	],
	primary_keys=["id"]
))

db.ensure_table(dict(
	tname="fragq_match_results",
	columns=[
		dict(cname="id", ctype=db.types.int, autoincrement=True),
		dict(cname="connector_id", ctype=db.types.int),
		dict(cname="guild_id", ctype=db.types.int),
		dict(cname="channel_id", ctype=db.types.int),
		dict(cname="queue_id", ctype=db.types.int),
		dict(cname="match_id", ctype=db.types.int),          # the FragQ match, NULL if none was found
		dict(cname="match_uid", ctype=db.types.str),         # the game's own match id, for repeated sends
		dict(cname="at", ctype=db.types.int),
		dict(cname="message_id", ctype=db.types.int),
		dict(cname="data", ctype=db.types.dict),             # the result as received (normalised)
	],
	primary_keys=["id"]
))

# (key, label, emoji, colour). Generic is for anything not listed: the format is the same for every game.
GAMES = [
	("generic", "Generic", "🎮", 0x1ff2a2),
	("apex", "Apex Legends", "🪂", 0xda292a),
	("bf6", "Battlefield 6", "🪖", 0xf1a33c),
	("cs2", "Counter-Strike 2", "🔫", 0xde9b35),
	("overwatch2", "Overwatch 2", "🦸", 0xf99e1a),
	("quakelive", "Quake Live", "⚡", 0xc0392b),
]
GAME = {g[0]: g for g in GAMES}

PREFIX = "fq_"
DEFAULT_RATE = 60
MAX_RATE = 10000
MAX_ALLOWED_IPS = 50
MAX_CONNECTORS = 25          # per Discord server
MATCH_WINDOW = 6 * 3600      # a result can belong to a FragQ match started this long ago
LINK_TTL = 15 * 60           # an in-game !link waits this long for the Discord confirmation
LINK_COOLDOWN = 60           # between !link requests for the same Steam account
USAGE_FLUSH = 30
DATE_RE = re.compile(r"^\d{4}-\d\d-\d\d$")
STEAM_RE = re.compile(r"^7656\d{13}$")
BUTTON = "fragq:gamelink:"

connectors = {}       # id -> row (queues decoded)
pending_links = {}    # token -> dict(user_id, steam_id, name, connector_id, guild_id, at)
_link_at = {}         # steam_id -> time of the last !link request
_dirty = set()        # connector ids with usage counters not written yet
_next_flush = 0


class ConnectorError(Exception):
	""" A refused API request: HTTP status and a message for whoever wrote the game plugin. """

	def __init__(self, status, message, headers=None):
		super().__init__(message)
		self.status, self.message, self.headers = status, message, headers or {}


# ------------------------------------------------------------------ connectors and their keys

def hash_key(key):
	return hashlib.sha256(key.encode()).hexdigest()


def new_key():
	""" Returns (key, key_hash, prefix). The prefix is what the web panel shows to tell keys apart. """
	key = PREFIX + secrets.token_urlsafe(32)
	return key, hash_key(key), key[:len(PREFIX) + 6]


def _decode(row):
	row = dict(row)
	try:
		queues = row.get("queues") or "[]"
		row["queues"] = [int(x) for x in (queues if isinstance(queues, list) else json.loads(queues))]
	except (TypeError, ValueError):
		row["queues"] = []
	for k in ("can_results", "can_check", "can_link", "can_export", "disabled"):
		row[k] = bool(row.get(k))
	for k in ("requests", "last_used_at", "last_denied_at", "rate_limit", "unmatched_queue"):
		row[k] = int(row.get(k) or 0)
	for k in ("allowed_ips", "expires_at", "last_used_ip", "last_denied_ip", "last_denied_reason", "created_by_name"):
		row[k] = row.get(k) or ""
	return row


async def load():
	connectors.clear()
	for row in await db.select(["*"], "fragq_connectors"):
		connectors[row["id"]] = _decode(row)


def guild_connectors(guild_id):
	return sorted((c for c in connectors.values() if c["guild_id"] == guild_id), key=lambda c: (c["name"].lower(), c["id"]))


def today():
	return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d")


def state(c):
	""" 'active', 'disabled' or 'expired'. A key works through the whole of its expiry day (UTC). """
	if c["disabled"]:
		return "disabled"
	if c["expires_at"] and c["expires_at"] < today():
		return "expired"
	return "active"


def queue_objects(c):
	""" The connector's queues that still exist, in its order: [(queue, queue channel)]. """
	by_id = {q.id: (q, qc) for qc in bot.queue_channels.values() if qc.guild_id == c["guild_id"] for q in qc.queues}
	return [by_id[qid] for qid in c["queues"] if qid in by_id]


def parse_settings(values, guild_id, current=None):
	"""
	Validate the web panel's connector form. Returns a dict of columns; raises ValueError with a message
	for the first problem.
	"""
	name = re.sub(r"\s+", " ", str(values.get("name") or "")).strip()[:60]
	if not name:
		raise ValueError("Give the connector a name, such as the game server it is for.")
	game = str(values.get("game") or "generic")
	if game not in GAME:
		raise ValueError("Choose a game from the list.")

	in_guild = {q.id for qc in bot.queue_channels.values() if qc.guild_id == guild_id for q in qc.queues}
	try:
		queues = list(dict.fromkeys(int(x) for x in values.get("queues") or []))
	except (TypeError, ValueError):
		raise ValueError("Unknown queue.")
	perms = {k: bool(values.get(k)) for k in ("can_results", "can_check", "can_link", "can_export")}
	if not any(perms.values()):
		raise ValueError("Allow the key to do at least one thing.")
	if not queues and any(v for k, v in perms.items() if k != "can_export"):  # reading links needs no queue
		raise ValueError("Choose at least one queue for this connector's results.")
	if any(q not in in_guild for q in queues):
		raise ValueError("One of the chosen queues doesn't exist on this server any more.")
	try:
		unmatched = int(values.get("unmatched_queue") or 0)
	except (TypeError, ValueError):
		unmatched = -1
	if unmatched and unmatched not in queues:
		raise ValueError("Results without a FragQ match can only go to one of the connector's queues.")

	allowed = []
	for item in re.split(r"[\s,;]+", str(values.get("allowed_ips") or "").strip()):
		if not item:
			continue
		try:
			net = ipaddress.ip_network(item, strict=False)
		except ValueError:
			raise ValueError(f"'{item[:50]}' is not an IP address or range (such as 203.0.113.10 or 198.51.100.0/24).")
		addr = net.network_address
		if net.num_addresses == 1 and addr.version == 6 and addr.ipv4_mapped:
			addr = addr.ipv4_mapped
		s = str(net) if net.num_addresses > 1 else str(addr)
		if s not in allowed:
			allowed.append(s)
	if len(allowed) > MAX_ALLOWED_IPS:
		raise ValueError(f"A connector can have at most {MAX_ALLOWED_IPS} allowed IP addresses or ranges.")

	rate = str(values.get("rate_limit") if values.get("rate_limit") is not None else DEFAULT_RATE).strip()
	if not rate.isdigit() or int(rate) > MAX_RATE:
		raise ValueError(f"Rate limit must be a whole number from 0 (unlimited) to {MAX_RATE:,} requests per minute.")

	expires = str(values.get("expires_at") or "").strip()
	if expires:
		try:
			if not DATE_RE.match(expires):
				raise ValueError
			dt.date.fromisoformat(expires)
		except ValueError:
			raise ValueError("Expiry must be a date (YYYY-MM-DD), or empty for a key that never expires.")

	return dict(
		name=name, game=game, queues=json.dumps([str(q) for q in queues]), unmatched_queue=max(unmatched, 0),
		allowed_ips=" ".join(allowed), rate_limit=int(rate), expires_at=expires, **perms,
	)


async def create(guild_id, values, by_id, by_name):
	""" Returns (row, key). The key is not stored anywhere: show it once. """
	if len(guild_connectors(guild_id)) >= MAX_CONNECTORS:
		raise ValueError(f"A server can have at most {MAX_CONNECTORS} connectors.")
	fields = parse_settings(values, guild_id)
	key, key_hash, prefix = new_key()
	now = int(time.time())
	row = dict(
		guild_id=guild_id, prefix=prefix, key_hash=key_hash, disabled=False, requests=0, last_used_at=0,
		last_used_ip="", last_denied_at=0, last_denied_ip="", last_denied_reason="", created_by=by_id,
		created_by_name=by_name[:191], created_at=now, updated_at=now, **fields,
	)
	row["id"] = await db.insert("fragq_connectors", row)
	row = _decode(row)
	connectors[row["id"]] = row
	log.info(f"Connector '{row['name']}' ({row['id']}) created on guild {guild_id} by {by_name}.")
	return row, key


async def _save(c, fields):
	fields["updated_at"] = int(time.time())
	await db.update("fragq_connectors", fields, keys=dict(id=c["id"]))
	c.update(_decode(dict(c, **fields)))
	return c


async def update(c, values):
	limiter.reset(c["id"])
	return await _save(c, parse_settings(values, c["guild_id"], current=c))


async def rotate(c):
	key, key_hash, prefix = new_key()
	await _save(c, dict(key_hash=key_hash, prefix=prefix))
	return c, key


async def set_disabled(c, disabled):
	return await _save(c, dict(disabled=bool(disabled)))


async def delete(c):
	await db.delete("fragq_connectors", where=dict(id=c["id"]))
	connectors.pop(c["id"], None)
	_dirty.discard(c["id"])
	limiter.reset(c["id"])


async def restore(guild_id, x, queues, unmatched, old=None):
	""" A connector from a Settings page backup: same key (its hash), settings and queues. """
	game = x.get("game") if x.get("game") in GAME else "generic"
	allowed = " ".join(str(x.get("allowed_ips") or "").split()[:MAX_ALLOWED_IPS])
	expires = str(x.get("expires_at") or "")
	try:
		rate = min(max(int(x.get("rate_limit") or 0), 0), MAX_RATE)
	except (TypeError, ValueError):
		rate = DEFAULT_RATE
	fields = dict(
		name=str(x.get("name") or "Connector")[:60], game=game, queues=json.dumps([str(q) for q in queues]),
		unmatched_queue=unmatched or 0, prefix=str(x.get("prefix") or PREFIX)[:20], key_hash=x["key_hash"],
		can_results=bool(x.get("can_results")), can_check=bool(x.get("can_check")), can_link=bool(x.get("can_link")),
		can_export=bool(x.get("can_export")), allowed_ips=allowed, rate_limit=rate, expires_at=expires if DATE_RE.match(expires) else "", disabled=bool(x.get("disabled")),
	)
	if old:
		return await _save(old, fields)
	now = int(time.time())
	try:
		created_by = int(x.get("created_by") or 0)
	except (TypeError, ValueError):
		created_by = 0
	row = dict(
		guild_id=guild_id, requests=0, last_used_at=0, last_used_ip="", last_denied_at=0, last_denied_ip="",
		last_denied_reason="", created_by=created_by, created_by_name=str(x.get("created_by_name") or "")[:191],
		created_at=int(x.get("created_at") or now), updated_at=now, **fields,
	)
	row["id"] = await db.insert("fragq_connectors", row)
	row = _decode(row)
	connectors[row["id"]] = row
	return row


async def forget_queue(queue_id):
	""" A queue was deleted: take it off the connectors serving it. """
	for c in list(connectors.values()):
		if queue_id in c["queues"]:
			rest = [q for q in c["queues"] if q != queue_id]
			await _save(c, dict(queues=json.dumps([str(q) for q in rest]),
								unmatched_queue=0 if c["unmatched_queue"] == queue_id else c["unmatched_queue"]))


# ------------------------------------------------------------------ authenticating API requests

def ip_allowed(ip, allowed):
	if not allowed:
		return True
	try:
		addr = ipaddress.ip_address(ip)
	except ValueError:
		return False
	if addr.version == 6 and addr.ipv4_mapped:
		addr = addr.ipv4_mapped
	return any(addr in ipaddress.ip_network(n, strict=False) for n in allowed.split())


class RateLimiter:
	""" Requests per connector per clock minute. """

	def __init__(self):
		self._windows = {}
		self._lock = threading.Lock()

	def hit(self, cid, limit):
		""" Count one request. Returns (allowed, retry_after_seconds). """
		if limit <= 0:
			return True, 0
		now = time.time()
		window = int(now // 60)
		with self._lock:
			w, n = self._windows.get(cid, (window, 0))
			if w != window:
				n = 0
			if n >= limit:
				return False, int(60 - now % 60) + 1
			self._windows[cid] = (window, n + 1)
			return True, 0

	def reset(self, cid):
		with self._lock:
			self._windows.pop(cid, None)


limiter = RateLimiter()


def _denied(c, ip, reason):
	c.update(last_denied_at=int(time.time()), last_denied_ip=ip[:191], last_denied_reason=reason)
	_dirty.add(c["id"])


def authenticate(raw_key, ip, need=None):
	""" The connector a request's key belongs to, after its state, IP allow list and rate limit are checked. """
	if not raw_key:
		raise ConnectorError(401, "Missing connector key. Send it in the header 'Authorization: Bearer <key>'.")
	h = hash_key(raw_key)
	c = next((c for c in connectors.values() if secrets.compare_digest(c["key_hash"], h)), None)
	if c is None:
		raise ConnectorError(401, "Invalid connector key.")
	st = state(c)
	if st != "active":
		_denied(c, ip, st)
		raise ConnectorError(403, f"This connector is {st}.")
	if not ip_allowed(ip, c["allowed_ips"]):
		_denied(c, ip, "ip")
		raise ConnectorError(403, f"This connector key can't be used from {ip}.")
	ok, retry = limiter.hit(c["id"], c["rate_limit"])
	if not ok:
		raise ConnectorError(429, f"Rate limit of {c['rate_limit']} requests per minute reached. Try again in {retry} seconds.",
							 {"Retry-After": str(retry)})
	if need and not c[need]:
		what = {"can_results": "send match results", "can_check": "check linked players", "can_link": "link Steam accounts",
				"can_export": "read linked accounts"}[need]
		_denied(c, ip, need)
		raise ConnectorError(403, f"This connector isn't allowed to {what}. Change that on the Connectors page of the FragQ web panel.")
	c.update(requests=c["requests"] + 1, last_used_at=int(time.time()), last_used_ip=ip[:191])
	_dirty.add(c["id"])
	return c


async def flush_usage():
	for cid in list(_dirty):
		_dirty.discard(cid)
		c = connectors.get(cid)
		if c is None:
			continue
		await db.update("fragq_connectors", {k: c[k] for k in (
			"requests", "last_used_at", "last_used_ip", "last_denied_at", "last_denied_ip", "last_denied_reason"
		)}, keys=dict(id=cid))


def status(c):
	""" GET /status: what the key is for, so a plugin can show it in its test command. """
	return dict(
		ok=True, fragq_version=__version__,
		connector=dict(
			name=c["name"], game=GAME.get(c["game"], GAME["generic"])[1],
			queues=[q.name for q, _ in queue_objects(c)],
			can=dict(results=c["can_results"], check=c["can_check"], link=c["can_link"], export=c["can_export"]),
		),
		server_time=int(time.time()),
	)


# ------------------------------------------------------------------ the result format

def _text(value, limit):
	if value is None:
		return None
	s = re.sub(r"[\x00-\x1f\x7f]+", " ", str(value)).strip()
	return s[:limit] or None


def _value(value, limit=40):
	""" A stat or highlight value as shown: numbers get thousands separators. """
	if isinstance(value, bool):
		return "Yes" if value else "No"
	if isinstance(value, int):
		return f"{value:,}"
	if isinstance(value, float):
		if not math.isfinite(value):
			return None
		return f"{value:,.2f}".rstrip("0").rstrip(".")
	return _text(value, limit)


def _list(data, key, limit):
	v = data.get(key)
	if v is None:
		return []
	if not isinstance(v, list):
		raise ValueError(f"'{key}' must be a list.")
	if len(v) > limit:
		raise ValueError(f"'{key}' can have at most {limit} entries.")
	return v


def normalize(data):
	""" Check a result and return it in the stored form; raises ValueError with what is wrong. """
	if not isinstance(data, dict):
		raise ValueError("The body must be a JSON object.")
	if data.get("version", 1) != 1:
		raise ValueError("Unsupported result version: this FragQ reads version 1.")
	out = dict(version=1)
	for key, limit in (("match_uid", 100), ("game", 60), ("title", 100), ("map", 60), ("mode", 40), ("server", 80), ("queue", 60)):
		out[key] = _text(data.get(key), limit)
	d = data.get("duration")
	out["duration"] = int(d) if isinstance(d, (int, float)) and not isinstance(d, bool) and 0 <= d <= 7 * 86400 else None
	m = data.get("fragq_match_id")
	out["fragq_match_id"] = int(m) if isinstance(m, int) and not isinstance(m, bool) and m > 0 else None

	teams = []
	for t in _list(data, "teams", 4):
		if not isinstance(t, dict) or not _text(t.get("name"), 40):
			raise ValueError("Every team needs a 'name'.")
		score = t.get("score")
		teams.append(dict(name=_text(t["name"], 40), score=_value(score, 12) if score is not None else None))
	out["teams"] = teams
	out["winner"] = _text(data.get("winner"), 40)
	if out["winner"] and teams and out["winner"].lower() not in {t["name"].lower() for t in teams}:
		raise ValueError("'winner' must be the name of one of the teams (or null for a draw).")

	players = []
	for p in _list(data, "players", 64):
		if not isinstance(p, dict):
			raise ValueError("Every player must be an object.")
		pid = _text(p.get("id"), 32)
		name = _text(p.get("name"), 64)
		if not pid and not name:
			raise ValueError("Every player needs an 'id' or a 'name'.")
		kind = p.get("id_type") or ("steam" if pid and STEAM_RE.match(pid) else "discord" if pid and pid.isdigit() else "name")
		if kind not in ("steam", "discord", "name"):
			raise ValueError("A player's 'id_type' must be 'steam', 'discord' or 'name'.")
		if kind == "steam" and not (pid and STEAM_RE.match(pid)):
			raise ValueError(f"'{pid}' is not a SteamID64.")
		stats = p.get("stats") or {}
		if not isinstance(stats, dict) or len(stats) > 24:
			raise ValueError("A player's 'stats' must be an object with at most 24 entries.")
		clean = {}
		for k, v in stats.items():
			label, shown = _text(k, 24), _value(v)
			if label and shown is not None:
				clean[label] = shown
		players.append(dict(id=pid or name, id_type=kind, name=name or pid, team=_text(p.get("team"), 40),
							quit=bool(p.get("quit")), stats=clean))
	if not players:
		raise ValueError("A result needs at least one player.")
	out["players"] = players
	ids = {p["id"] for p in players}

	highlights = []
	for h in _list(data, "highlights", 12):
		if not isinstance(h, dict) or not _text(h.get("label"), 40):
			raise ValueError("Every highlight needs a 'label'.")
		who = h.get("players") if isinstance(h.get("players"), list) else ([h["player"]] if h.get("player") is not None else [])
		who = [str(x) for x in who[:16]]
		if any(x not in ids for x in who):
			raise ValueError(f"Highlight '{h['label']}' names a player who isn't in 'players'.")
		value = _value(h.get("value"), 60) if h.get("value") is not None else None
		highlights.append(dict(label=_text(h["label"], 40), players=who, value=value))
	out["highlights"] = highlights

	table = [_text(c, 24) for c in _list(data, "table", 6)]
	out["table"] = [c for c in table if c]
	return out


# ------------------------------------------------------------------ finding the FragQ match

def _steam_owners():
	return {r["steam_id"]: uid for uid, r in bot.steam.links.items()}


def player_users(result):
	""" Discord user id per result player id, for the players FragQ can identify. """
	owners = _steam_owners()
	out = {}
	for p in result["players"]:
		if p["id_type"] == "steam" and p["id"] in owners:
			out[p["id"]] = owners[p["id"]]
		elif p["id_type"] == "discord" and p["id"].isdigit():
			out[p["id"]] = int(p["id"])
	return out


async def _recent(c, queue_ids):
	""" Matches of the connector's queues that the result can belong to: [dict(match_id, qc, queue, users, at)]. """
	cands = []
	for m in bot.active_matches:
		if m.queue.id in queue_ids:
			cands.append(dict(match_id=m.id, qc=m.qc, queue=m.queue, users={p.id for p in m.players}, at=m.start_time))
	known = {x["match_id"] for x in cands}
	by_qid = {q.id: (q, qc) for q, qc in queue_objects(c)}
	channels = sorted({by_qid[q][1].id for q in queue_ids if q in by_qid})
	if channels:
		rows = await db.fetchall(
			"SELECT m.match_id, m.channel_id, m.queue_id, m.at, p.user_id FROM `qc_matches` AS m "
			"JOIN `qc_player_matches` AS p ON p.match_id=m.match_id AND p.channel_id=m.channel_id "
			f"WHERE m.at>=%s AND m.channel_id IN ({', '.join(['%s'] * len(channels))})",
			(int(time.time()) - MATCH_WINDOW, *channels)
		)
		found = {}
		for r in rows:
			if r["match_id"] in known or r["queue_id"] not in queue_ids:
				continue
			q, qc = by_qid[r["queue_id"]]
			found.setdefault(r["match_id"], dict(match_id=r["match_id"], qc=qc, queue=q, users=set(), at=r["at"]))["users"].add(r["user_id"])
		cands.extend(found.values())
	return cands


async def find_match(c, result):
	""" The FragQ match a result belongs to, or None: most of its players must be in the game's result. """
	queue_ids = set(c["queues"])
	if result.get("queue"):
		named = {q.id for q, _ in queue_objects(c) if q.name.lower() == result["queue"].lower()}
		queue_ids = named or queue_ids
	cands = await _recent(c, queue_ids)
	if result.get("fragq_match_id"):
		return next((m for m in cands if m["match_id"] == result["fragq_match_id"]), None)
	users = set(player_users(result).values())
	if not users or not cands:
		return None
	rows = await db.fetchall(
		f"SELECT match_id FROM `fragq_match_results` WHERE match_id IN ({', '.join(['%s'] * len(cands))})",
		tuple(m["match_id"] for m in cands)
	)
	reported = {r["match_id"] for r in rows}
	best = None
	for m in cands:
		overlap = len(m["users"] & users)
		if not m["users"] or overlap < max(1, math.ceil(len(m["users"]) / 2)):
			continue
		# a fuller overlap first, then matches that have no result yet, then the most recent
		score = (overlap / len(m["users"]), m["match_id"] not in reported, m["at"])
		if best is None or score > best[0]:
			best = (score, m)
	return best[1] if best else None


# ------------------------------------------------------------------ the Discord message

def _shown_names(result, guild):
	""" What to call each player: their Discord name when FragQ knows them, else the name from the game. """
	users = player_users(result)
	out = {}
	for p in result["players"]:
		member = guild.get_member(users[p["id"]]) if guild and p["id"] in users else None
		out[p["id"]] = get_nick(member) if member else p["name"]
	return out


def _duration(seconds):
	h, rest = divmod(int(seconds), 3600)
	m, s = divmod(rest, 60)
	return f"{h}:{m:02}:{s:02}" if h else f"{m}:{s:02}"


def _table(players, columns, names, width=1000):
	""" A fixed-width table of players and their stats, inside a code block. """
	def cell(s):
		return str(s).replace("`", "'")
	head = ["Player"] + columns
	rows = []
	for p in players:
		name = names[p["id"]] + (" (left)" if p["quit"] else "")
		rows.append([cell(name)[:18]] + [cell(p["stats"].get(col, "–")) for col in columns])
	widths = [max(len(r[i]) for r in [head] + rows) for i in range(len(head))]
	lines = ["  ".join(v.ljust(widths[i]) if i == 0 else v.rjust(widths[i]) for i, v in enumerate(r)) for r in [head] + rows]
	out, shown = [], 0
	for line in lines:
		if sum(len(x) + 1 for x in out) + len(line) + 30 > width:
			break
		out.append(line)
		shown += 1
	more = len(lines) - shown
	if more:
		out.append(f"… {more} more")
	return "```\n" + "\n".join(out) + "\n```"


def build_embed(c, result, match=None, guild=None, test=False):
	_, game_label, emoji, colour = GAME.get(c["game"], GAME["generic"])
	names = _shown_names(result, guild)
	esc = lambda s: escape_markdown(str(s))

	if match:
		title = f"{emoji} {match['queue'].name} · Match #{match['match_id']} results"
	else:
		title = f"{emoji} {result.get('title') or 'Match results'}"
	if test:
		title = "🧪 Test: " + title

	lines = []
	teams = result["teams"]
	if len(teams) == 2 and all(t["score"] is not None for t in teams):
		lines.append(f"**{esc(teams[0]['name'])}** {teams[0]['score']} – {teams[1]['score']} **{esc(teams[1]['name'])}**")
	elif teams:
		lines.append(" · ".join(f"**{esc(t['name'])}**" + (f" {t['score']}" if t["score"] is not None else "") for t in teams))
	if result["winner"]:
		lines.append(f"🏆 {esc(result['winner'])} win" + ("" if result["winner"].lower().endswith("s") else "s"))
	elif teams and all(t["score"] is not None for t in teams) and len({t["score"] for t in teams}) == 1:
		lines.append("🤝 Draw")
	meta = [x for x in (
		result.get("map") and esc(result["map"]), result.get("mode") and esc(result["mode"]),
		result.get("duration") is not None and _duration(result["duration"]), result.get("server") and esc(result["server"]),
	) if x]
	if meta:
		lines.append(" · ".join(meta))

	embed = Embed(title=title[:256], description="\n".join(lines)[:4000] or None, colour=Colour(colour),
				  timestamp=dt.datetime.now(dt.timezone.utc))
	for h in result["highlights"]:
		who = ", ".join(esc(names.get(x, x)) for x in h["players"])
		value = " · ".join(x for x in (f"**{who}**" if who else None, h["value"] and esc(h["value"])) if x) or "—"
		embed.add_field(name=h["label"], value=value[:1024], inline=True)

	columns = [col for col in result["table"] if any(col in p["stats"] for p in result["players"])]
	if columns:
		by_team = {}
		for p in result["players"]:
			by_team.setdefault(p["team"] or "", []).append(p)
		order = [t["name"] for t in teams if t["name"] in by_team] + [t for t in by_team if t not in {x["name"] for x in teams}]
		for team in order[:4]:
			score = next((t["score"] for t in teams if t["name"] == team), None)
			label = (team or "Players") + (f" · {score}" if score is not None else "")
			embed.add_field(name=label[:256], value=_table(by_team[team], columns, names), inline=False)

	embed.set_footer(text=f"{result.get('game') or game_label} · {c['name']} · FragQ connectors (beta)"[:2048])
	return embed


async def post(c, result, match=None, queue_qc=None, test=False):
	""" Post a result in its queue's channel. Returns the message id, or None. """
	qc = match["qc"] if match else queue_qc
	channel = dc.get_channel(qc.id) if qc else None
	if channel is None:
		return None
	try:
		msg = await channel.send(embed=build_embed(c, result, match, channel.guild, test), allowed_mentions=AllowedMentions.none())
	except DiscordException as e:
		log.error(f"Connector '{c['name']}' couldn't post a result in #{getattr(channel, 'name', qc.id)}: {e}")
		return None
	bot.panel.bump(qc)
	return msg.id


async def receive(c, data):
	""" POST /results. Returns the answer for the game plugin. """
	try:
		result = normalize(data)
	except ValueError as e:
		raise ConnectorError(400, str(e))
	if result["match_uid"]:
		old = await db.select(["id", "match_id", "message_id"], "fragq_match_results",
							  where=dict(connector_id=c["id"], match_uid=result["match_uid"]), one=True)
		if old:
			return dict(ok=True, status="duplicate", result_id=old["id"], match_id=old["match_id"], posted=bool(old["message_id"]))

	match = await find_match(c, result)
	queue, qc = (match["queue"], match["qc"]) if match else (None, None)
	if match is None and c["unmatched_queue"]:
		queue, qc = next(((q, x) for q, x in queue_objects(c) if q.id == c["unmatched_queue"]), (None, None))
	message_id = await post(c, result, match, qc) if qc else None
	row = dict(
		connector_id=c["id"], guild_id=c["guild_id"], channel_id=qc.id if qc else None, queue_id=queue.id if queue else None,
		match_id=match["match_id"] if match else None, match_uid=result["match_uid"], at=int(time.time()),
		message_id=message_id, data=json.dumps(result, ensure_ascii=False),
	)
	result_id = await db.insert("fragq_match_results", row)
	where = f"match #{match['match_id']} ({queue.name})" if match else (f"no FragQ match, posted in {queue.name}" if qc else "no FragQ match, stored only")
	log.info(f"Connector '{c['name']}': result received, {where}.")
	return dict(
		ok=True, status="posted" if message_id else "stored", result_id=result_id,
		match_id=match["match_id"] if match else None, queue=queue.name if queue else None, posted=bool(message_id),
	)


async def summary(guild_id):
	""" {connector id: (results received, time of the last one)} """
	rows = await db.fetchall(
		"SELECT connector_id, COUNT(*) AS n, MAX(at) AS last FROM `fragq_match_results` WHERE guild_id=%s GROUP BY connector_id",
		(guild_id,)
	)
	return {r["connector_id"]: (int(r["n"]), int(r["last"] or 0)) for r in rows}


def sample_result(c):
	""" A made-up result for the web panel's Send test button. """
	players = [m for m in (dc.get_guild(c["guild_id"]).members if dc.get_guild(c["guild_id"]) else []) if not m.bot][:4]
	names = [get_nick(m) for m in players] + ["Player A", "Player B", "Player C", "Player D"]
	people = [dict(id=f"test{i}", id_type="name", name=names[i], team="Red" if i < 2 else "Blue",
				   stats=dict(Score=[42, 31, 27, 12][i], Kills=[21, 15, 12, 6][i])) for i in range(4)]
	if c["game"] == "quakelive":
		hl = [("Top Damage", 0, "3,214"), ("Least Damage", 3, "612"), ("Most Damage Taken", 2, "2,980"),
			  ("Most Frags", 0, "21"), ("Highest Accuracy", 1, "47%")]
	else:
		hl = [("MVP", 0, None), ("Most Kills", 0, "21"), ("Top Score", 1, "31")]
	return dict(
		version=1, title="Test result", game=GAME[c["game"]][1], map="Test map", mode="Test", duration=612,
		teams=[dict(name="Red", score=8), dict(name="Blue", score=5)], winner="Red", players=people,
		highlights=[dict(label=lbl, player=f"test{i}", value=v) for lbl, i, v in hl], table=["Score", "Kills"],
	)


# ------------------------------------------------------------------ linked players and !link from a game

def resolve_member(guild, text):
	""" A member of the connector's server from a Discord user id or username. """
	s = str(text or "").strip().lstrip("@").strip("<>!@")
	if not s:
		return None
	if s.isdigit():
		return guild.get_member(int(s))
	low = s.lower()
	exact = [m for m in guild.members if m.name.lower() == low]
	if exact:
		return exact[0]
	nick = [m for m in guild.members if (m.nick or m.display_name or "").lower() == low]
	return nick[0] if len(nick) == 1 else None


def linked(c, steam_ids):
	""" POST /players/linked """
	if not isinstance(steam_ids, list) or len(steam_ids) > 64:
		raise ConnectorError(400, "'steam_ids' must be a list of at most 64 SteamID64s.")
	owners = _steam_owners()
	guild = dc.get_guild(c["guild_id"])
	waiting = {p["steam_id"] for p in pending_links.values()}
	out = []
	for sid in steam_ids:
		sid = str(sid)
		if not STEAM_RE.match(sid):
			raise ConnectorError(400, f"'{sid[:20]}' is not a SteamID64.")
		uid = owners.get(sid)
		member = guild.get_member(uid) if guild and uid else None
		out.append(dict(steam_id=sid, linked=uid is not None, member=member is not None,
						discord_name=get_nick(member) if member else None, confirming=sid in waiting))
	return dict(ok=True, players=out)


def steam_links(c):
	""" GET /steam/links: the links of the members of the connector's Discord server. """
	guild = dc.get_guild(c["guild_id"])
	if guild is None or guild.unavailable:
		raise ConnectorError(503, "The bot can't see this connector's Discord server right now.")
	out = []
	for uid, r in bot.steam.links.items():
		if (member := guild.get_member(uid)) is not None:
			out.append(dict(
				steam_id=r["steam_id"], discord_id=str(uid), discord_name=member.name, persona=r.get("persona") or None,
				verified_by=r.get("verified_by") or "", linked_at=r.get("linked_at") or None,
			))
	return dict(ok=True, links=out)


def _link_answer(status, message, **extra):
	return dict(ok=status in ("sent", "already_linked"), status=status, message=message, **extra)


async def request_link(c, data):
	""" POST /link: a player typed !link on a game server. Sends the Discord member a confirmation. """
	if not isinstance(data, dict):
		raise ConnectorError(400, "The body must be a JSON object.")
	sid = str(data.get("steam_id") or "")
	if not STEAM_RE.match(sid):
		raise ConnectorError(400, "'steam_id' must be a SteamID64.")
	name = _text(data.get("name"), 64) or sid
	guild = dc.get_guild(c["guild_id"])
	if guild is None:
		raise ConnectorError(503, "The bot can't see this connector's Discord server right now.")
	member = resolve_member(guild, data.get("discord"))
	if member is None:
		return _link_answer("not_member", f"No member of the {guild.name} Discord has that id or username. Check it: "
										  "your Discord user id is under Developer Mode, right-click your name, Copy User ID.")
	now = time.time()
	for token, p in list(pending_links.items()):
		if now - p["at"] > LINK_TTL:
			pending_links.pop(token, None)
	owner = _steam_owners().get(sid)
	if owner == member.id:
		return _link_answer("already_linked", f"Your Steam account is already linked to {get_nick(member)}.")
	if owner is not None:
		return _link_answer("taken", "This Steam account is already linked to another Discord member. Ask a server admin.")
	wait = LINK_COOLDOWN - (now - _link_at.get(sid, 0))
	if wait > 0:
		return _link_answer("wait", f"Wait {int(wait) + 1} seconds before asking again.", retry_after=int(wait) + 1)
	_link_at[sid] = now
	if len(_link_at) > 5000:
		for k, t in list(_link_at.items()):
			if now - t > LINK_COOLDOWN:
				_link_at.pop(k, None)

	for token, p in list(pending_links.items()):
		if p["steam_id"] == sid:
			pending_links.pop(token, None)  # a newer request replaces it
	token = secrets.token_urlsafe(12)
	pending_links[token] = dict(user_id=member.id, steam_id=sid, name=name, connector_id=c["id"], guild_id=guild.id, at=now)

	current = bot.steam.links.get(member.id)
	text = (f"**{escape_markdown(name)}** on **{escape_markdown(c['name'])}** ({GAME.get(c['game'], GAME['generic'])[1]}) "
			f"asked to link the Steam account `{sid}` to your Discord account on **{escape_markdown(guild.name)}**.\n\n"
			"Only confirm if that was you.")
	if current:
		text += f"\n\nYou are linked to Steam `{current['steam_id']}` now: confirming asks a moderator to approve the change."
	embed = Embed(colour=Colour(0x66c0f4), title="🔗 Link your Steam account?", description=text)
	embed.set_footer(text=f"This request expires in {LINK_TTL // 60} minutes.")
	view = View(timeout=None, auto_defer=False)
	view.add_item(Button(style=ButtonStyle.success, label="Confirm", emoji="✅", custom_id=f"{BUTTON}yes:{token}"))
	view.add_item(Button(style=ButtonStyle.secondary, label="That wasn't me", custom_id=f"{BUTTON}no:{token}"))
	try:
		await member.send(embed=embed, view=view)
	except Exception:
		pending_links.pop(token, None)
		_link_at.pop(sid, None)
		return _link_answer("dm_failed", f"FragQ couldn't send {get_nick(member)} a direct message. Allow direct messages "
										 f"from server members on {guild.name}, or link with !steam in Discord.")
	log.info(f"Connector '{c['name']}': {name} ({sid}) asked to link Steam to {get_nick(member)} ({member.id}).")
	return _link_answer("sent", f"Check your Discord direct messages and press Confirm within {LINK_TTL // 60} minutes.",
						discord_name=get_nick(member))


async def on_button(interaction):
	""" The Confirm / That wasn't me buttons of a link request (in a direct message). """
	action, _, token = interaction.data["custom_id"][len(BUTTON):].partition(":")
	p = pending_links.get(token)
	if p is None or time.time() - p["at"] > LINK_TTL:
		pending_links.pop(token, None)
		await interaction.response.edit_message(
			embed=error_embed("This request has expired. Type `!link` on the game server again.", title=None), view=None)
		return
	if interaction.user.id != p["user_id"]:
		await interaction.response.send_message(embed=error_embed("This request isn't for you.", title=None), ephemeral=True)
		return
	pending_links.pop(token, None)
	if action != "yes":
		log.info(f"{interaction.user} declined linking Steam {p['steam_id']} ({p['name']}).")
		await interaction.response.edit_message(embed=ok_embed("Cancelled. Nothing was linked.", title=None), view=None)
		return
	guild = dc.get_guild(p["guild_id"])
	member = guild.get_member(p["user_id"]) if guild else None
	if member is None:
		await interaction.response.edit_message(embed=error_embed("You are no longer on that server.", title=None), view=None)
		return
	await interaction.response.defer()
	try:
		st, row = await bot.steam.link(member, p["steam_id"], method="game")
	except bot.Exc.PubobotException as e:
		await interaction.edit_original_message(embed=error_embed(str(e), title="Steam link failed"), view=None)
		return
	await interaction.edit_original_message(embed=ok_embed(bot.steam.result_text(st, row), title=None), view=None)


# ------------------------------------------------------------------ events

@dc.event
async def on_init():
	await load()


@dc.event
async def on_think(frame_time):
	global _next_flush
	if frame_time > _next_flush and _dirty:
		_next_flush = frame_time + USAGE_FLUSH
		try:
			await flush_usage()
		except Exception as e:
			log.error(f"Connector usage update failed: {e!r}")
