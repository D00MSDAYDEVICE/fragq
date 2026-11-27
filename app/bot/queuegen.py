# -*- coding: utf-8 -*-
"""
QueueGen (web panel page): admins generate a one-off queue for a scheduled match between two fixed teams.

Each event gets its own text channel, created by FragQ in the Events category, with its own channel config
(QueueChannel) and one queue, so it never touches an existing channel's queues, panel or ratings. The match runs
on FragQ's normal code: the rostered players check in by joining the event's queue (Check in on the event message,
or !add), and when the last one has, the queue starts its match with the two teams as the admin set them
(pick_teams "premade"). Reports, series, voice moves and game server results work as on any queue.

Only rostered players can check in; admins swap players on the QueueGen page (before or during the match).
FragQ also creates a voice channel per team, and a Lobby per event or one shared by every event (QueueGen
settings). Channels FragQ created are deleted after the cleanup time (24 hours by default) once the event is over;
its results and ratings stay.

States: scheduled -> open (check-in) -> live (match in progress) -> finished, or cancelled; -> archived once its
channels are deleted. A canceled match puts the event back to open.
"""
import json
import os
import re
import time

from datetime import datetime, timezone

from nextcord import (PermissionOverwrite, DiscordException, Forbidden, HTTPException, NotFound, Embed, Colour, ButtonStyle,
					  ChannelType, ScheduledEventEntityType, ScheduledEventStatus, EntityMetadata)
from nextcord.ui import View, Button

from core.client import dc
from core.console import log
from core.database import db
from core.utils import get_nick, join_and, valid_server_address

import bot

db.ensure_table(dict(
	tname="fragq_events",
	columns=[
		dict(cname="id", ctype=db.types.int, autoincrement=True),
		dict(cname="guild_id", ctype=db.types.int),
		dict(cname="state", ctype=db.types.str),
		dict(cname="start_at", ctype=db.types.int),
		dict(cname="data", ctype=db.types.text),        # JSON: see clean() and the provisioning below
		dict(cname="created_by", ctype=db.types.int),
		dict(cname="created_by_name", ctype=db.types.str),
		dict(cname="created_at", ctype=db.types.int),
		dict(cname="updated_at", ctype=db.types.int),
		dict(cname="ended_at", ctype=db.types.int),
	],
	primary_keys=["id"]
))

STATES = ("scheduled", "open", "live", "finished", "cancelled", "archived")
ACTIVE = ("scheduled", "open", "live")
MAX_TEAM = 8
CLEANUP_CHOICES = (24, 72, 168, 0)      # hours after the event ends; 0 = keep the channels
DURATIONS = (60, 120, 180, 360, 720, 1440, 2880)   # minutes from the start to the Discord event's end
DEFAULT_DURATION = 1440
# Cover images for the Discord event (drawn by dev/gen_covers.py): (name, label); the first is the default.
COVERS = (("crosshair", "Crosshair"), ("versus", "Versus"), ("grid", "Arena"), ("hud", "Match day"))
COVER_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "webui", "static", "covers")
LOBBY_MODES = ("event", "global_generate", "global_choose")
REMIND_EVERY = 10 * 60
THINK_EVERY = 3
DEFAULT_SETTINGS = dict(category_id=None, organizer_role_id=None, lobby_mode="global_generate", lobby_id=None, cleanup_hours=24)

db.ensure_table(dict(
	tname="fragq_tournaments",
	columns=[
		dict(cname="id", ctype=db.types.int, autoincrement=True),
		dict(cname="guild_id", ctype=db.types.int),
		dict(cname="name", ctype=db.types.str),
		dict(cname="data", ctype=db.types.text),        # JSON: rating_system, rating_initial, rating_deviation
		dict(cname="created_by_name", ctype=db.types.str),
		dict(cname="created_at", ctype=db.types.int),
		dict(cname="updated_at", ctype=db.types.int),
	],
	primary_keys=["id"]
))

# A tournament's ratings are kept under this key instead of a channel id (qc_players.channel_id): no Discord channel
# id is this small, and the key outlives the event channels, which are deleted after each event.
TOURNAMENT_KEY_BASE = 1_000_000
RATING_DEFAULTS = dict(rating_system="TrueSkill", rating_initial=1500, rating_deviation=200)   # QueueChannel's defaults

events = {}           # event id -> event dict (row columns, with data decoded)
tournaments = {}      # tournament id -> dict(id, guild_id, name, rating_system, rating_initial, rating_deviation, ...)
_last_think = 0
_signatures = {}      # event id -> what its Discord message last showed


class FieldError(ValueError):
	def __init__(self, field, message):
		super().__init__(message)
		self.field = field


# ------------------------------------------------------------------ settings (one set per Discord server)

def settings(guild_id):
	return dict(DEFAULT_SETTINGS, **(bot.settings.get(f"queuegen:{guild_id}") or {}))


async def save_settings(guild, values):
	s = settings(guild.id)
	cat = values.get("category_id")
	if cat:
		c = guild.get_channel(_int(cat))
		if c is None or getattr(c, "type", None) != ChannelType.category:
			raise FieldError("category_id", "Category not found.")
		s["category_id"] = c.id
	elif "category_id" in values:
		s["category_id"] = None
	role = values.get("organizer_role_id")
	if role:
		r = guild.get_role(_int(role))
		if r is None or r.is_default():
			raise FieldError("organizer_role_id", "Role not found.")
		s["organizer_role_id"] = r.id
	elif "organizer_role_id" in values:
		s["organizer_role_id"] = None
	if "lobby_mode" in values:
		if values["lobby_mode"] not in LOBBY_MODES:
			raise FieldError("lobby_mode", "Unknown lobby choice.")
		s["lobby_mode"] = values["lobby_mode"]
	if s["lobby_mode"] == "global_choose":
		lid = values.get("lobby_id", s.get("lobby_id"))
		v = guild.get_channel(_int(lid)) if lid else None
		if v is None or v not in guild.voice_channels:
			raise FieldError("lobby_id", "Choose the voice channel every event uses as its Lobby.")
		s["lobby_id"] = v.id
		s["lobby_generated"] = False
	elif s["lobby_mode"] == "global_generate" and not s.get("lobby_generated"):
		s["lobby_id"] = None    # generated with the next event
	if "cleanup_hours" in values:
		h = _int(values["cleanup_hours"])
		if h not in CLEANUP_CHOICES:
			raise FieldError("cleanup_hours", "Unknown cleanup time.")
		s["cleanup_hours"] = h
	await bot.settings.put(f"queuegen:{guild.id}", s)
	return s


# ------------------------------------------------------------------ lookups

def guild_events(guild_id):
	return sorted((e for e in events.values() if e["guild_id"] == guild_id), key=lambda e: (e["start_at"] or 0, e["id"]))


def for_channel(channel_id):
	""" The active or finished event whose generated text channel this is, or None. """
	return next((e for e in events.values() if e["data"].get("channel_id") == channel_id and e["state"] != "archived"), None)


def is_event_channel(channel_id):
	return for_channel(channel_id) is not None


def for_queue(q):
	return next((e for e in events.values() if e["data"].get("queue_id") == q.id and e["state"] != "archived"), None)


def roster_ids(ev):
	return [uid for team in ev["data"]["roster"] for uid in team]


def _queue(ev):
	qc = bot.queue_channels.get(ev["data"].get("channel_id"))
	return next((q for q in qc.queues if q.id == ev["data"].get("queue_id")), None) if qc else None


def _match(ev):
	q = _queue(ev)
	return next((m for m in bot.active_matches if m.queue is q), None) if q else None


def _int(v):
	try:
		return int(v)
	except (TypeError, ValueError):
		return None


# ------------------------------------------------------------------ hooks used by the queue and match code

def check_member(qc, member):
	"""
	QueueChannel.check_allowed_to_add, on an event channel: only rostered players can check in, and only while
	the event is open. Raises PermissionError.
	"""
	ev = for_channel(qc.id)
	if ev is None:
		return
	if member.id not in roster_ids(ev):
		raise bot.Exc.PermissionError(f"Only the players of **{ev['data']['name']}** can check in here. "
									  "Admins swap players on the web panel's QueueGen page.")
	if ev["state"] == "scheduled":
		raise bot.Exc.PermissionError(f"Check-in for **{ev['data']['name']}** isn't open yet: it starts <t:{ev['start_at']}:R>.")
	if ev["state"] != "open":
		raise bot.Exc.PermissionError(f"**{ev['data']['name']}** isn't taking check-ins ({ev['state']}).")


def allowed(q, member):
	""" PickupQueue.add_member: False for anyone off the roster of the event this queue belongs to. """
	ev = for_queue(q)
	return ev is None or (member.id in roster_ids(ev) and ev["state"] == "open")


def match_cfg(q, cfg):
	""" PickupQueue._match_cfg: an event's match uses its fixed teams, names and server. """
	ev = for_queue(q)
	if ev is None:
		return cfg
	d = ev["data"]
	cfg.update(
		pick_teams="premade", pick_captains="no captains", teams=[list(t) for t in d["roster"]],
		team_names=list(d["team_names"]), check_in_timeout=0, maps=[], map_count=0, vote_maps=0,
		slipgate_balance=False,
	)
	return cfg


def is_event_queue(q):
	return for_queue(q) is not None


async def match_done(match, reported):
	"""
	Match.finish_match (reported, after its result is saved) and Match.cancel: the background loop then finishes the
	event, or puts it back to check-in. A series keeps the event live until it ends.
	"""
	ev = for_queue(match.queue)
	if ev is None or ev["state"] != "live":
		return
	if reported and bot.series.of(match.queue):   # a game of the series was reported: the event ends with the series
		ev["data"]["ended"] = dict(match_id=match.id, reported=True)
		await _save(ev)
		return
	await _end_match(dc.get_guild(ev["guild_id"]), ev, reported, match)


async def match_started(match):
	""" Match.new: the event's match is on (its last player checked in). """
	ev = for_queue(match.queue)
	if ev is None or ev["state"] != "open":
		return
	d = ev["data"]
	d["match_id"] = match.id
	d.pop("ended", None)
	d.pop("missing_since", None)
	await _save(ev, state="live")
	if (guild := dc.get_guild(ev["guild_id"])):
		await _refresh(guild, ev)


# ------------------------------------------------------------------ validation

def clean(values, guild, current=None):
	""" The editor's values -> event data. Raises FieldError. `current`: the event being edited. """
	old = current["data"] if current else {}
	state = current["state"] if current else "scheduled"
	d = dict(old)

	name = str(values.get("name", old.get("name", "")) or "").strip()
	teams = values.get("team_names", old.get("team_names")) or ["", ""]
	if not isinstance(teams, list) or len(teams) != 2:
		raise FieldError("team_names", "Give both team names.")
	teams = [str(t or "").strip() for t in teams]
	for i, t in enumerate(teams):
		if not 1 <= len(t) <= 40:
			raise FieldError(f"team_name{i + 1}", "1 to 40 characters.")
	if teams[0].casefold() == teams[1].casefold():
		raise FieldError("team_name2", "The two teams need different names.")
	name = name or f"{teams[0]} vs {teams[1]}"
	if len(name) > 60:
		raise FieldError("name", "At most 60 characters.")
	d["name"], d["team_names"] = name, teams

	size = _int(values.get("team_size", old.get("team_size", 4)))
	if size is None or not 1 <= size <= MAX_TEAM:
		raise FieldError("team_size", f"1 to {MAX_TEAM} players per team.")
	if current and state in ("open", "live") and size != old.get("team_size"):
		raise FieldError("team_size", "The team size can't change once check-in is open.")
	d["team_size"] = size

	if "start_at" in values or not current:
		start = _int(values.get("start_at"))
		if start is None:
			raise FieldError("start_at", "Choose the date and time.")
		if start < time.time() - 60 and (not current or start != current["start_at"]) and state == "scheduled":
			raise FieldError("start_at", "Choose a time in the future.")
		d["start_at"] = start
	else:
		d["start_at"] = current["start_at"]

	roster = values.get("roster", old.get("roster")) or [[], []]
	if not isinstance(roster, list) or len(roster) != 2:
		raise FieldError("roster", "Bad roster.")
	seen, out = set(), []
	for i, team in enumerate(roster):
		ids = []
		for uid in team or []:
			uid = _int(uid)
			if uid is None or uid in seen:
				raise FieldError(f"roster{i + 1}", "A player can only be in one team once.")
			if guild.get_member(uid) is None:
				raise FieldError(f"roster{i + 1}", "A player isn't a member of this server.")
			if not bot.steam.get_link(uid) and uid not in roster_ids(current or dict(data=dict(roster=[[], []]))):
				raise FieldError(f"roster{i + 1}", f"{get_nick(guild.get_member(uid))} hasn't linked a Steam account.")
			seen.add(uid)
			ids.append(uid)
		if len(ids) > size:
			raise FieldError(f"roster{i + 1}", f"At most {size} players.")
		out.append(ids)
	if current and state == "live" and out != old.get("roster"):
		raise FieldError("roster", "The match is on: swap players instead.")
	d["roster"] = out

	server = str(values.get("server", old.get("server", "")) or "").strip()
	if server and not valid_server_address(server):
		raise FieldError("server", "Use IP:port, such as 131.153.224.87:27970.")
	d["server"] = server

	desc = str(values.get("description", old.get("description", "")) or "").strip()
	if len(desc) > 1000:
		raise FieldError("description", "At most 1000 characters.")
	d["description"] = desc

	series = _int(values.get("series_length", old.get("series_length", 1)))
	if series is None or not 1 <= series <= 9:
		raise FieldError("series_length", "1 to 9 games.")
	if current and state == "live" and series != old.get("series_length"):
		raise FieldError("series_length", "The series can't change during the match.")
	d["series_length"] = series

	for key, default in (("slipgate_results", True), ("rated", True), ("private", False), ("discord_event", True), ("auto_open", True)):
		d[key] = bool(values.get(key, old.get(key, default)))
	if current and state == "live" and d["rated"] != old.get("rated"):
		raise FieldError("rated", "Can't change during the match.")

	minutes = _int(values.get("duration_minutes", old.get("duration_minutes", DEFAULT_DURATION)))
	if minutes not in DURATIONS:
		raise FieldError("duration_minutes", "Unknown length.")
	d["duration_minutes"] = minutes

	tid = values.get("tournament_id", old.get("tournament_id"))
	tid = _int(tid) if tid not in (None, "") else None
	if tid is not None and (tid not in tournaments or tournaments[tid]["guild_id"] != guild.id):
		raise FieldError("tournament_id", "Tournament not found.")
	if current and state in ("open", "live") and tid != old.get("tournament_id"):
		raise FieldError("tournament_id", "The tournament can't change once check-in is open.")
	d["tournament_id"] = tid

	cover = values.get("cover", old.get("cover", COVERS[0][0]))
	if cover not in [c for c, _ in COVERS] + [""]:
		raise FieldError("cover", "Unknown cover image.")
	d["cover"] = cover

	cid = values.get("connector_id", old.get("connector_id"))
	cid = _int(cid) if cid not in (None, "") else None
	if cid is not None:
		c = bot.connectors.connectors.get(cid)
		if c is None or c["guild_id"] != guild.id or not c["can_results"]:
			raise FieldError("connector_id", "Choose a connector that sends match results.")
	d["connector_id"] = cid

	hours = values.get("cleanup_hours", old.get("cleanup_hours", settings(guild.id)["cleanup_hours"]))
	hours = _int(hours)
	if hours not in CLEANUP_CHOICES:
		raise FieldError("cleanup_hours", "Unknown cleanup time.")
	d["cleanup_hours"] = hours
	return d


# ------------------------------------------------------------------ storage

def _decode(row):
	row = dict(row)
	try:
		row["data"] = json.loads(row.get("data") or "{}")
	except ValueError:
		row["data"] = {}
	return row


async def load():
	events.clear()
	for row in await db.select(["*"], "fragq_events"):
		ev = _decode(row)
		events[ev["id"]] = ev
	tournaments.clear()
	for row in await db.select(["*"], "fragq_tournaments"):
		t = _decode_tournament(row)
		tournaments[t["id"]] = t


# ------------------------------------------------------------------ tournaments (shared ratings)
#
# Events in the same tournament share one rating history: their channels keep their ratings under the tournament's
# key with the tournament's rating settings. The key is chosen once, never one that already has ratings (a database
# may reuse a deleted tournament's id), and kept in backups. An event without a tournament keeps its own ratings,
# in its own channel.

def _decode_tournament(row):
	t = dict(row)
	try:
		extra = json.loads(t.pop("data", None) or "{}")
	except ValueError:
		extra = {}
	t.update({k: extra.get(k, v) for k, v in RATING_DEFAULTS.items()})
	t["key"] = _int(extra.get("key")) or TOURNAMENT_KEY_BASE + int(t["id"])
	return t


def tournament_key(t):
	return t["key"]


async def _free_key(want=None):
	""" A rating key no other tournament uses and nothing is rated under yet; `want` (a restored key) if possible. """
	taken = {t["key"] for t in tournaments.values()}
	if want and TOURNAMENT_KEY_BASE <= want < TOURNAMENT_KEY_BASE * 1000 and want not in taken:
		return want
	key = max(taken | {TOURNAMENT_KEY_BASE}) + 1
	while True:
		used = await db.fetchall("SELECT 1 AS x FROM `qc_players` WHERE channel_id=%s LIMIT 1", (key,)) or \
			await db.fetchall("SELECT 1 AS x FROM `qc_rating_history` WHERE channel_id=%s LIMIT 1", (key,))
		if not used:
			return key
		key += 1


def guild_tournaments(guild_id):
	return sorted((t for t in tournaments.values() if t["guild_id"] == guild_id), key=lambda t: t["name"].casefold())


def tournament_of(ev):
	t = tournaments.get(ev["data"].get("tournament_id"))
	return t if t and t["guild_id"] == ev["guild_id"] else None


def rating_key(channel_id):
	""" QueueChannel: the key an event channel keeps its ratings under, when its event is in a tournament; else None. """
	ev = next((e for e in events.values() if e["data"].get("channel_id") == channel_id), None)
	t = tournament_of(ev) if ev else None
	return tournament_key(t) if t else None


def clean_tournament(values, guild, current=None):
	name = str(values.get("name", (current or {}).get("name", "")) or "").strip()
	if not 1 <= len(name) <= 60:
		raise FieldError("name", "1 to 60 characters.")
	if any(t["name"].casefold() == name.casefold() and t is not current for t in guild_tournaments(guild.id)):
		raise FieldError("name", "A tournament with this name already exists.")
	out = dict(name=name)
	system = values.get("rating_system", (current or RATING_DEFAULTS)["rating_system"])
	if system not in bot.QueueChannel.rating_names:
		raise FieldError("rating_system", "Unknown rating system.")
	out["rating_system"] = system
	initial = _int(values.get("rating_initial", (current or RATING_DEFAULTS)["rating_initial"]))
	if initial is None or not 0 <= initial <= 10000:
		raise FieldError("rating_initial", "0 to 10000.")
	out["rating_initial"] = initial
	dev = _int(values.get("rating_deviation", (current or RATING_DEFAULTS)["rating_deviation"]))
	if dev is None or not 1 <= dev <= 3000:
		raise FieldError("rating_deviation", "1 to 3000.")
	out["rating_deviation"] = dev
	return out


def _tournament_row(t):
	return dict(guild_id=t["guild_id"], name=t["name"], data=json.dumps(dict({k: t[k] for k in RATING_DEFAULTS}, key=t["key"])),
				created_by_name=t.get("created_by_name"), created_at=t.get("created_at"), updated_at=int(time.time()))


async def create_tournament(guild, values, by_name, key=None):
	""" key: a restored tournament's rating key, so it finds its ratings again when it's free. """
	t = dict(clean_tournament(values, guild), guild_id=guild.id, created_by_name=by_name, created_at=int(time.time()),
			 key=await _free_key(key))
	row = _tournament_row(t)
	t["id"] = await db.insert("fragq_tournaments", row)
	t["updated_at"] = row["updated_at"]
	tournaments[t["id"]] = t
	return t


async def update_tournament(guild, t, values):
	t.update(clean_tournament(values, guild, t))
	row = _tournament_row(t)
	t["updated_at"] = row["updated_at"]
	await db.update("fragq_tournaments", row, keys=dict(id=t["id"]))
	for ev in events.values():   # its events' channels follow the new rating settings (new players only)
		if ev["data"].get("tournament_id") == t["id"] and ev["state"] in ACTIVE:
			await _apply_rating(ev)
	return t


async def delete_tournament(t):
	busy = [e["data"]["name"] for e in events.values() if e["data"].get("tournament_id") == t["id"] and e["state"] in ACTIVE]
	if busy:
		raise bot.Exc.PermissionError(f"These events still use the tournament: {join_and(busy)}. Finish, cancel or move them first.")
	tournaments.pop(t["id"], None)
	await db.delete("fragq_tournaments", where=dict(id=t["id"]))


async def tournament_summary(t, top=10):
	""" Leaderboard (top players) and match count of a tournament, from its rating key and its events' channels. """
	rows = await db.select(["user_id", "nick", "rating", "deviation", "wins", "losses", "draws"], "qc_players",
						   where=dict(channel_id=tournament_key(t)))
	rated = sorted((r for r in rows if r.get("rating") is not None), key=lambda r: -r["rating"])
	# rated matches, from the rating history kept under the tournament's key: still there after the events are gone
	got = await db.fetchall("SELECT COUNT(DISTINCT match_id) AS n FROM `qc_rating_history` WHERE channel_id=%s", (tournament_key(t),))
	matches = (got[0].get("n") if got else 0) or 0
	return dict(players=len(rated), matches=matches, leaderboard=rated[:top])


async def _apply_rating(ev):
	""" Point the event channel's ratings at its tournament (settings and key), or back at its own channel. """
	qc = bot.queue_channels.get(ev["data"].get("channel_id"))
	if qc is None:
		return
	t = tournament_of(ev)
	src = t or RATING_DEFAULTS
	values = {k: str(src[k]) for k in RATING_DEFAULTS}
	if any(str(getattr(qc.cfg, k)) != v for k, v in values.items()):
		await qc.cfg.update(values)   # calls qc.update_rating_system
	qc.update_rating_system()   # the key can change without a setting changing


async def _save(ev, **cols):
	ev.update(cols)
	ev["updated_at"] = int(time.time())
	await db.update("fragq_events", dict(
		state=ev["state"], start_at=ev["start_at"], data=json.dumps(ev["data"]), updated_at=ev["updated_at"],
		ended_at=ev.get("ended_at"),
	), keys=dict(id=ev["id"]))


# ------------------------------------------------------------------ Discord channels

def _slug(name):
	s = re.sub(r"[^\w]+", "-", name.lower()).strip("-")
	return (s or "event")[:90]


def _queue_name(name):
	return re.sub(r"[\s:+]+", "-", name).strip("-")[:30] or "event"


CREATE_EVENTS = 1 << 44   # Discord's Create Events permission (newer than nextcord 2.6, which has no name for it)
NEEDED = [
	("view_channel", "View Channels"), ("send_messages", "Send Messages"), ("embed_links", "Embed Links"),
	("read_message_history", "Read Message History"), ("manage_channels", "Manage Channels"),
	("manage_roles", "Manage Roles"), ("connect", "Connect"), ("move_members", "Move Members"),
]


def _bot_perms(guild):
	return getattr(getattr(guild, "me", None), "guild_permissions", None)


def can_create_events(guild):
	p = _bot_perms(guild)
	return p is not None and bool(getattr(p, "administrator", False) or getattr(p, "manage_events", False)
								  or int(getattr(p, "value", 0) or 0) & CREATE_EVENTS)


def missing_permissions(guild, events=True):
	""" Discord permissions QueueGen needs and the bot doesn't have on the server (labels). """
	p = _bot_perms(guild)
	if p is None or getattr(p, "administrator", False):
		return []
	out = [label for attr, label in NEEDED if not getattr(p, attr, False)]
	if events and not can_create_events(guild):
		out.append("Create Events")
	return out


def _ow(guild, **perms):
	"""
	A permission overwrite with only what the bot may hand out: Discord refuses to create a channel whose overwrites
	allow or deny a permission the bot doesn't have itself (error 50013).
	"""
	p = _bot_perms(guild)
	if p is None or getattr(p, "administrator", False):
		return PermissionOverwrite(**perms)
	return PermissionOverwrite(**{k: v for k, v in perms.items() if getattr(p, k, False)})


async def _discord(guild, step, coro):
	""" Run a Discord call; a refusal names the step and the permissions to check. """
	try:
		return await coro
	except Forbidden:
		missing = missing_permissions(guild, events=False)
		hint = (" The bot's role is missing: " + ", ".join(missing) + ".") if missing else \
			" Check the bot's permissions on the Events category (it needs View Channels, Manage Channels and Manage Roles there)."
		raise bot.Exc.PermissionError(f"Discord refused {step} (missing permissions).{hint}")
	except HTTPException as e:
		raise bot.Exc.PermissionError(f"Discord refused {step}: {getattr(e, 'text', '') or e}")


def _staff(guild):
	""" Who besides the roster may type and connect: the bot, the organizer role, the server's admin roles. """
	s = settings(guild.id)
	out = [guild.me]
	if s["organizer_role_id"] and (r := guild.get_role(s["organizer_role_id"])):
		out.append(r)
	out.extend(r for r in guild.roles
			   if getattr(getattr(r, "permissions", None), "administrator", False) and not r.managed and not r.is_default())
	return out


def _text_overwrites(guild, ev):
	d = ev["data"]
	ow = {guild.default_role: _ow(guild, view_channel=not d["private"], send_messages=False, add_reactions=False)}
	for who in _staff(guild):
		ow[who] = _ow(guild, view_channel=True, send_messages=True, embed_links=True, read_message_history=True)
	for uid in roster_ids(ev):
		if (m := guild.get_member(uid)):
			ow[m] = _ow(guild, view_channel=True, send_messages=True, read_message_history=True)
	return ow


def _voice_overwrites(guild, ev, team=None):
	""" team: 0 or 1 for a team channel (only its players connect), None for an event's own Lobby (the roster). """
	d = ev["data"]
	ow = {guild.default_role: _ow(guild, view_channel=not d["private"], connect=False)}
	for who in _staff(guild):
		ow[who] = _ow(guild, view_channel=True, connect=True, speak=True, move_members=True)
	for uid in (d["roster"][team] if team is not None else roster_ids(ev)):
		if (m := guild.get_member(uid)):
			ow[m] = _ow(guild, view_channel=True, connect=True, speak=True)
	return ow


async def _category(guild):
	s = settings(guild.id)
	if s["category_id"] and (c := guild.get_channel(s["category_id"])):
		return c
	c = await _discord(guild, "creating the FragQ Events category",
					   guild.create_category("FragQ Events", reason="QueueGen: category for generated event channels"))
	s["category_id"] = c.id
	await bot.settings.put(f"queuegen:{guild.id}", s)
	return c


async def _lobby(guild, category, ev):
	""" (voice channel, generated for this event) for the event's Lobby, per the QueueGen settings. """
	s = settings(guild.id)
	if s["lobby_mode"] == "global_choose":
		return guild.get_channel(s["lobby_id"]) if s["lobby_id"] else None, False
	if s["lobby_mode"] == "global_generate":
		if s["lobby_id"] and (v := guild.get_channel(s["lobby_id"])):
			return v, False
		v = await _discord(guild, "creating the voice channel 🔊 Events Lobby",
						   guild.create_voice_channel("🔊 Events Lobby", category=category, reason="QueueGen: shared lobby for events"))
		s.update(lobby_id=v.id, lobby_generated=True)
		await bot.settings.put(f"queuegen:{guild.id}", s)
		return v, False
	name = f"🔊 {ev['data']['name']}"[:100]
	v = await _discord(guild, f"creating the voice channel {name}", guild.create_voice_channel(
		name, category=category, overwrites=_voice_overwrites(guild, ev), reason="QueueGen: event lobby"))
	return v, True


def _topic(ev):
	d = ev["data"]
	parts = [f"{d['team_names'][0]} vs {d['team_names'][1]}"]
	if d["description"]:
		parts.append(d["description"])
	return " · ".join(parts)[:1024]


# ------------------------------------------------------------------ Discord scheduled events (promotion)
#
# An event that isn't private gets a Discord scheduled event: "Somewhere Else" at the Discord server's name, titled
# ◄Team1 vs Team2►, with the rosters as its description and one of FragQ's cover images (COVERS). Members see it in
# the server's event list, can press Interested and get Discord's reminder.
# It follows the event: edited while scheduled, started when check-in opens, completed when the event finishes,
# canceled or deleted with it. A failure never blocks the event itself; it shows on the QueueGen page.

def discord_event_url(guild_id, event_id):
	return f"https://discord.com/events/{guild_id}/{event_id}"


def _wants_discord_event(ev):
	d = ev["data"]
	return bool(d.get("discord_event", True)) and not d.get("private")


def _dt(ts):
	return datetime.fromtimestamp(int(ts), tz=timezone.utc)


def discord_event_title(ev):
	t = ev["data"]["team_names"]
	return f"◄{t[0]} vs {t[1]}►"[:100]


def discord_event_rosters(guild, ev):
	""" The Discord event's description: each team and its players. """
	d = ev["data"]
	blocks = []
	for i in (0, 1):
		names = [get_nick(m) if (m := guild.get_member(uid)) else str(uid) for uid in d["roster"][i]]
		blocks.append("\n".join([d["team_names"][i]] + ([f"• {n}" for n in names] or ["• (no players yet)"])))
	return "\n\n".join(blocks)[:1000]


def _cover_bytes(name):
	if not name:
		return None
	try:
		with open(os.path.join(COVER_DIR, f"{name}.png"), "rb") as f:
			return f.read()
	except OSError as e:
		log.error(f"QueueGen: cover image {name} not found: {e}")
		return None


def _discord_event_fields(guild, ev):
	"""
	A "Somewhere Else" (external) event at the Discord server's name, titled ◄Team1 vs Team2►, from the event's
	start for its expected length (a day by default), with the rosters as its description. It doesn't repeat.
	"""
	d = ev["data"]
	return dict(
		name=discord_event_title(ev), description=discord_event_rosters(guild, ev),
		start_time=_dt(ev["start_at"]), end_time=_dt(ev["start_at"] + int(d.get("duration_minutes") or DEFAULT_DURATION) * 60),
		entity_type=ScheduledEventEntityType.external, metadata=EntityMetadata(location=guild.name[:100]),
	)


async def _get_discord_event(guild, ev):
	eid = ev["data"].get("discord_event_id")
	if not eid:
		return None
	se = guild.get_scheduled_event(eid)
	if se is None:
		try:
			se = await guild.fetch_scheduled_event(eid)
		except NotFound:
			ev["data"].pop("discord_event_id", None)
			return None
		except DiscordException:
			return None
	return se


async def sync_discord_event(guild, ev):
	""" Create, update or remove the event's Discord scheduled event to match it. Never raises. """
	d = ev["data"]
	before = (d.get("discord_event_id"), d.get("discord_event_error"), d.get("discord_cover"))
	try:
		se = await _get_discord_event(guild, ev)
		if not _wants_discord_event(ev) or ev["state"] not in ACTIVE:
			if se is not None and ev["state"] in ACTIVE:
				await se.delete()
			if ev["state"] in ACTIVE:
				d.pop("discord_event_id", None)
			d.pop("discord_event_error", None)
		elif ev["state"] != "scheduled":   # already started: only its name and description follow
			if se is not None:
				f = _discord_event_fields(guild, ev)
				await se.edit(name=f["name"], description=f["description"])
		elif ev["start_at"] <= time.time() + 60:
			pass   # Discord only schedules events in the future
		elif not can_create_events(guild):
			d["discord_event_error"] = "The bot needs the Create Events permission to promote the event in Discord."
		else:
			f = _discord_event_fields(guild, ev)
			if se is not None and se.entity_type != f["entity_type"]:   # made in a voice channel by an earlier build: redo it
				await se.delete()
				se = None
			cover = d.get("cover", COVERS[0][0])
			if se is None:
				image = _cover_bytes(cover)
				se = await guild.create_scheduled_event(reason=f"QueueGen event #{ev['id']}", **f, **({"image": image} if image else {}))
				d["discord_event_id"] = se.id
				d["discord_cover"] = cover if image else ""
			else:
				f["type"] = f.pop("entity_type")
				if d.get("discord_cover", "") != cover:   # only send the image when it changed
					f["image"] = _cover_bytes(cover)
					d["discord_cover"] = cover if f["image"] else ""
				await se.edit(reason="QueueGen: event edited", **f)
			d.pop("discord_event_error", None)
	except DiscordException as e:
		d["discord_event_error"] = f"Discord refused the scheduled event: {getattr(e, 'text', '') or e}"
		log.error(f"QueueGen: Discord scheduled event of event #{ev['id']}: {e}")
	if (d.get("discord_event_id"), d.get("discord_event_error"), d.get("discord_cover")) != before:
		await _save(ev)


async def _discord_event_status(guild, ev, how):
	""" how: "start" (check-in opened), "finish", "cancel" or "delete". Never raises. """
	if guild is None or not ev["data"].get("discord_event_id"):
		return
	try:
		se = await _get_discord_event(guild, ev)
		if se is None:
			return
		status = se.status
		if how == "start" and status == ScheduledEventStatus.scheduled:
			await se.edit(status=ScheduledEventStatus.active)
		elif how == "finish" and status == ScheduledEventStatus.active:
			await se.edit(status=ScheduledEventStatus.completed)
		elif how in ("finish", "cancel") and status == ScheduledEventStatus.scheduled:
			await se.edit(status=ScheduledEventStatus.canceled)
		elif how in ("cancel", "delete"):
			await se.delete()
			ev["data"].pop("discord_event_id", None)
	except DiscordException as e:
		log.error(f"QueueGen: couldn't {how} the Discord scheduled event of event #{ev['id']}: {e}")


async def provision(guild, ev):
	""" Create the event's channels, channel config and queue. """
	d = ev["data"]
	if missing := missing_permissions(guild, events=False):
		raise bot.Exc.PermissionError("The bot needs these Discord permissions for QueueGen: " + ", ".join(missing) + ".")
	category = await _category(guild)
	slug = _slug(d["name"])
	text = await _discord(guild, f"creating the text channel #{slug}", guild.create_text_channel(
		slug, category=category, overwrites=_text_overwrites(guild, ev), topic=_topic(ev), reason=f"QueueGen event #{ev['id']}"))
	d["channel_id"] = text.id
	voice = {}
	try:
		for i in (0, 1):
			name = f"{('🔴', '🔵')[i]} {d['team_names'][i]}"[:100]
			v = await _discord(guild, f"creating the voice channel {name}", guild.create_voice_channel(
				name, category=category, overwrites=_voice_overwrites(guild, ev, i), reason=f"QueueGen event #{ev['id']}"))
			voice[f"team{i + 1}"] = v.id
		lobby, generated = await _lobby(guild, category, ev)
		voice["lobby"], voice["lobby_generated"] = (lobby.id if lobby else None), generated
	finally:
		d["voice"] = voice
		await _save(ev)

	qc = await bot.QueueChannel.create(text)
	for stale in list(qc.queues):   # a brand-new channel has no queues; never let leftovers join the event's
		await stale.cfg.delete()
		qc.queues.remove(stale)
	bot.queue_channels[text.id] = qc
	await qc.update_info(text)
	s = settings(guild.id)
	await qc.cfg.update(dict(
		remove_afk="off", remove_offline="off", expire_time="none",
		**({"admin_role": str(s["organizer_role_id"])} if s["organizer_role_id"] and guild.get_role(s["organizer_role_id"]) else {}),
	))
	await _apply_rating(ev)   # a tournament's shared ratings, or the channel's own
	cfg = await bot.PickupQueue.cfg_factory.spawn(guild, f_key=qc.id)
	await cfg.update(_queue_values(ev))
	q = bot.PickupQueue(qc, cfg)
	qc.queues.append(q)
	d["queue_id"] = q.id
	await _save(ev)
	await _connector(ev, None)
	log.info(f"QueueGen: event #{ev['id']} '{d['name']}' got #{text.name} on {guild.name}.")
	await sync_discord_event(guild, ev)
	try:   # the event's message: when, where, who; it becomes the check-in message when check-in opens
		msg = await text.send(embed=_embed(guild, ev))
		d["message_id"] = msg.id
		await _save(ev)
		_signatures[ev["id"]] = _signature(ev)
	except DiscordException as e:
		log.error(f"QueueGen: couldn't post the message of event #{ev['id']}: {e}")


def _queue_values(ev):
	d, v = ev["data"], ev["data"].get("voice") or {}
	values = dict(
		name=_queue_name(d["name"]), size=str(d["team_size"] * 2), team_size=str(d["team_size"]),
		autostart="on", is_default="on", ranked="on" if d["rated"] else "off", check_in_timeout="none",
		hold_time="none" if d["rated"] else "03:00:00", series_length=str(d["series_length"]),
		slipgate_results_off="off" if d["slipgate_results"] else "on", require_steam_link="off",
		server=d["server"] or "none", start_msg="none",
	)
	if v.get("team1") and v.get("team2") and v.get("lobby"):
		values.update(voice_moves="on", voice_lobby=str(v["lobby"]), voice_team1=str(v["team1"]), voice_team2=str(v["team2"]))
	else:
		values.update(voice_moves="off")
	return values


async def _connector(ev, old_id):
	""" Serve the event's queue from its connector (results), and no longer from the one it had. """
	qid, new_id = ev["data"].get("queue_id"), ev["data"].get("connector_id")
	if not qid:
		return
	for cid in {old_id, new_id} - {None}:
		c = bot.connectors.connectors.get(cid)
		if c is None:
			continue
		want = cid == new_id and ev["state"] != "archived"
		if want and qid not in c["queues"]:
			await bot.connectors._save(c, dict(queues=json.dumps([str(q) for q in c["queues"] + [qid]])))
		elif not want and qid in c["queues"]:
			rest = [x for x in c["queues"] if x != qid]
			await bot.connectors._save(c, dict(queues=json.dumps([str(x) for x in rest]),
											   unmatched_queue=0 if c["unmatched_queue"] == qid else c["unmatched_queue"]))


async def _apply(guild, ev, old):
	""" An edited event: bring its channels and queue in line. """
	d = ev["data"]
	text = guild.get_channel(d.get("channel_id"))
	if text:
		await _discord(guild, f"editing #{text.name}", text.edit(
			name=_slug(d["name"]), topic=_topic(ev), overwrites=_text_overwrites(guild, ev), reason="QueueGen: event edited"))
	v = d.get("voice") or {}
	for i in (0, 1):
		if (vc := guild.get_channel(v.get(f"team{i + 1}"))):
			await _discord(guild, f"editing the voice channel {vc.name}", vc.edit(
				name=f"{('🔴', '🔵')[i]} {d['team_names'][i]}"[:100], overwrites=_voice_overwrites(guild, ev, i)))
	if v.get("lobby_generated") and (vc := guild.get_channel(v.get("lobby"))):
		await _discord(guild, f"editing the voice channel {vc.name}", vc.edit(
			name=f"🔊 {d['name']}"[:100], overwrites=_voice_overwrites(guild, ev)))
	if old.get("start_at", ev["start_at"]) != ev["start_at"]:
		d.pop("start_notice", None)
	if old.get("tournament_id") != d.get("tournament_id"):
		await _apply_rating(ev)
	await sync_discord_event(guild, ev)
	q = _queue(ev)
	if q is not None:
		values = _queue_values(ev)
		if ev["state"] == "live":    # the match is on: only what doesn't affect it
			values = {k: values[k] for k in ("name", "server")}
		await q.cfg.update(values)
		# players taken off the roster leave the check-in
		gone = [m for m in q.queue if m.id not in roster_ids(ev)]
		if gone:
			q.pop_members(*gone)
	if old.get("connector_id") != d.get("connector_id"):
		await _connector(ev, old.get("connector_id"))
	_signatures.pop(ev["id"], None)


async def teardown(guild, ev):
	""" Delete the channels FragQ created for the event, and its channel config. The results and ratings stay. """
	d = ev["data"]
	qc = bot.queue_channels.get(d.get("channel_id"))
	if qc is not None:
		for m in [m for m in bot.active_matches if m.qc is qc]:
			try:
				await m.cancel(bot.SystemContext(qc))
			except (Exception, bot.Exc.PubobotException) as e:
				log.error(f"QueueGen: canceling match {m.id} of event #{ev['id']} failed: {e!r}")
		await bot.panel.remove(qc)
		for q in list(qc.queues):
			await q.reset()
			await q.cfg.delete()
			await bot.connectors.forget_queue(q.id)
		await qc.cfg.delete()
		bot.queue_channels.pop(qc.id, None)
	v = d.get("voice") or {}
	ids = [d.get("channel_id"), v.get("team1"), v.get("team2")] + ([v.get("lobby")] if v.get("lobby_generated") else [])
	for cid in ids:
		if cid and guild and (c := guild.get_channel(cid)):
			try:
				await c.delete(reason=f"QueueGen: event #{ev['id']} cleaned up")
			except DiscordException as e:
				log.error(f"QueueGen: couldn't delete channel {cid} of event #{ev['id']}: {e}")


# ------------------------------------------------------------------ actions (web panel)

async def create(guild, values, by_id, by_name):
	data = clean(values, guild)
	now = int(time.time())
	row = dict(guild_id=guild.id, state="scheduled", start_at=data.pop("start_at"), data=json.dumps(data),
			   created_by=by_id, created_by_name=by_name, created_at=now, updated_at=now, ended_at=None)
	ev = _decode(dict(row, id=await db.insert("fragq_events", row)))
	events[ev["id"]] = ev
	try:
		await provision(guild, ev)
	except (Exception, bot.Exc.PubobotException):
		await teardown(guild, ev)
		events.pop(ev["id"], None)
		await db.delete("fragq_events", where=dict(id=ev["id"]))
		raise
	return ev


async def update(guild, ev, values):
	if ev["state"] not in ACTIVE:
		raise bot.Exc.PermissionError("This event is over: it can't be edited.")
	old = dict(ev["data"], start_at=ev["start_at"])
	data = clean(values, guild, ev)
	ev["start_at"] = data.pop("start_at")
	ev["data"] = data
	await _save(ev)
	await _apply(guild, ev, old)
	return ev


async def open_now(guild, ev):
	if ev["state"] != "scheduled":
		raise bot.Exc.PermissionError("Check-in is already open." if ev["state"] in ("open", "live") else "This event is over.")
	d = ev["data"]
	short = [d["team_names"][i] for i in (0, 1) if len(d["roster"][i]) != d["team_size"]]
	if short:
		raise bot.Exc.PermissionError(f"Fill both teams first ({join_and(short)} needs {d['team_size']} players).")
	if _queue(ev) is None:
		raise bot.Exc.PermissionError("The event's channel is gone.")
	d["opened_at"] = d["last_reminder"] = int(time.time())
	await _save(ev, state="open")
	await _discord_event_status(guild, ev, "start")
	text = guild.get_channel(d["channel_id"])
	if text:
		if d.get("message_id"):   # the announcement posted with the event: check-in replaces it at the bottom
			try:
				await text.get_partial_message(d["message_id"]).delete()
			except DiscordException:
				pass
		try:
			msg = await text.send(content=" ".join(f"<@{uid}>" for uid in roster_ids(ev)) + f"\n**{d['name']}**: check-in is open. Press **Check in** when you're ready.",
								  embed=_embed(guild, ev), view=_view(ev))
			d["message_id"] = msg.id
			await _save(ev)
		except DiscordException as e:
			log.error(f"QueueGen: couldn't post the message of event #{ev['id']}: {e}")
	_signatures[ev["id"]] = _signature(ev)
	return ev


async def cancel(guild, ev):
	if ev["state"] not in ACTIVE:
		raise bot.Exc.PermissionError("This event is already over.")
	q = _queue(ev)
	m = _match(ev)
	await _finish(guild, ev, "cancelled")   # first, so canceling the match doesn't reopen check-in
	await _discord_event_status(guild, ev, "cancel")
	await _save(ev)
	if m is not None:
		await m.cancel(bot.SystemContext(m.qc))
	if q is not None:
		if bot.series.of(q):
			await bot.series.end(q, "event cancelled")
		await q.reset()
	text = guild.get_channel(ev["data"].get("channel_id"))
	if text:
		try:
			await text.send(f"❌ **{ev['data']['name']}** was cancelled." + _cleanup_line(ev))
		except DiscordException:
			pass
	return ev


async def delete(guild, ev):
	await _discord_event_status(guild, ev, "delete")
	if ev["state"] != "archived":
		ev["state"] = "archived"   # canceling its match on the way out doesn't reopen check-in
		await teardown(guild, ev)
	await _connector_drop(ev)
	events.pop(ev["id"], None)
	_signatures.pop(ev["id"], None)
	await db.delete("fragq_events", where=dict(id=ev["id"]))


async def _connector_drop(ev):
	qid = ev["data"].get("queue_id")
	if qid:
		await bot.connectors.forget_queue(qid)


async def swap(guild, ev, out_id, in_id):
	""" Replace a rostered player with a linked member, before or during the match. """
	if ev["state"] not in ACTIVE:
		raise bot.Exc.PermissionError("This event is over.")
	d = ev["data"]
	out_id, in_id = _int(out_id), _int(in_id)
	team = next((i for i in (0, 1) if out_id in d["roster"][i]), None)
	if team is None:
		raise FieldError("out", "That player isn't on the roster.")
	new = guild.get_member(in_id) if in_id else None
	if new is None:
		raise FieldError("in", "Choose a member of this server.")
	if in_id in roster_ids(ev):
		raise FieldError("in", f"{get_nick(new)} is already on the roster.")
	if not bot.steam.get_link(in_id):
		raise FieldError("in", f"{get_nick(new)} hasn't linked a Steam account.")
	old = guild.get_member(out_id)
	m = _match(ev)
	if m is not None:
		if any(new in x.players for x in bot.active_matches):
			raise FieldError("in", f"{get_nick(new)} is in another match.")
		if old is None or old not in m.players:
			raise FieldError("out", "That player isn't in the match.")
		await m.draft.sub_for(bot.SystemContext(m.qc), old, new, force=True)
	q = _queue(ev)
	if q is not None and old is not None and old in q.queue:
		q.pop_members(old)
	d["roster"][team] = [in_id if uid == out_id else uid for uid in d["roster"][team]]
	await _save(ev)
	await _apply(guild, ev, dict(d))
	text = guild.get_channel(d.get("channel_id"))
	if text and ev["state"] in ("open", "live"):
		try:
			await text.send(f"🔁 {new.mention} replaces **{get_nick(old) if old else out_id}** in **{d['team_names'][team]}**.")
		except DiscordException:
			pass
	return ev


# ------------------------------------------------------------------ the event message

def _state_of(ev, uid, q):
	if q is not None and any(m.id == uid for m in q.queue):
		return "✅"
	if any(p.id == uid for m in bot.active_matches if not (q and m.queue is q) for p in m.players):
		return "🎮"
	return "⌛"


def _embed(guild, ev):
	d, q = ev["data"], _queue(ev)
	colour = {"scheduled": 0x5865f2, "open": 0x1ff2a2, "live": 0xf1c40f, "finished": 0x2ecc71}.get(ev["state"], 0x95a5a6)
	e = Embed(title=f"🏆 {d['name']}", description=d["description"] or None, colour=Colour(colour))
	e.add_field(name="When", value=f"<t:{ev['start_at']}:F> (<t:{ev['start_at']}:R>)", inline=False)
	if d["server"]:
		e.add_field(name="Server", value=f"`{d['server']}`", inline=True)
	if d["series_length"] > 1:
		e.add_field(name="Series", value=f"Best of {d['series_length']}", inline=True)
	for i in (0, 1):
		lines = []
		for uid in d["roster"][i]:
			mem = guild.get_member(uid)
			mark = _state_of(ev, uid, q) if ev["state"] == "open" else "•"
			lines.append(f"{mark} {mem.mention if mem else uid}")
		e.add_field(name=d["team_names"][i], value="\n".join(lines) or "—", inline=True)
	if d.get("discord_event_id") and ev["state"] in ("scheduled", "open"):
		e.add_field(name="Discord event", value=f"[Interested? Get a reminder]({discord_event_url(guild.id, d['discord_event_id'])})", inline=False)
	e.set_footer(text=_status_line(ev, q))
	return e


def _status_line(ev, q):
	d = ev["data"]
	if ev["state"] == "open":
		n = len(q.queue) if q else 0
		return f"Check-in: {n}/{d['team_size'] * 2}. ✅ checked in · ⌛ waiting · 🎮 still in another match"
	if ev["state"] == "live":
		return f"Match #{d.get('match_id')} is on."
	if ev["state"] == "finished":
		r = d.get("result") or {}
		return f"Finished: {r.get('text') or 'reported'}."
	if ev["state"] == "cancelled":
		return "Cancelled."
	return "Check-in opens at the start time." if d.get("auto_open", True) else "Check-in opens when an admin opens it."


def _view(ev):
	if ev["state"] != "open" or not ev["data"].get("queue_id"):
		return None
	view = View(timeout=None, auto_defer=False)
	view.add_item(Button(style=ButtonStyle.success, label="Check in", emoji="✅", custom_id=f"{bot.panel.PREFIX}add:{ev['data']['queue_id']}"))
	view.add_item(Button(style=ButtonStyle.danger, label="Leave", emoji="✖️", custom_id=f"{bot.panel.PREFIX}remove"))
	return view


def _signature(ev):
	q = _queue(ev)
	return (ev["state"], tuple(m.id for m in q.queue) if q else (), json.dumps(ev["data"]["roster"]), ev["data"].get("match_id"),
			tuple(sorted(p.id for m in bot.active_matches for p in m.players)) if ev["state"] == "open" else ())


async def _refresh(guild, ev):
	sig = _signature(ev)
	if _signatures.get(ev["id"]) == sig or not ev["data"].get("message_id"):
		return
	_signatures[ev["id"]] = sig
	text = guild.get_channel(ev["data"].get("channel_id"))
	if not text:
		return
	try:
		await text.get_partial_message(ev["data"]["message_id"]).edit(embed=_embed(guild, ev), view=_view(ev))
	except DiscordException as e:
		log.error(f"QueueGen: couldn't update the message of event #{ev['id']}: {e}")


def _cleanup_line(ev):
	h = ev["data"].get("cleanup_hours")
	if not h:
		return ""
	return f" This channel is deleted <t:{int(ev['ended_at'] or time.time()) + h * 3600}:R>."


# ------------------------------------------------------------------ the background loop

async def _finish(guild, ev, state):
	ev["ended_at"] = int(time.time())
	await _save(ev, state=state)
	_signatures.pop(ev["id"], None)
	if guild:
		await _refresh(guild, ev)


async def _result(ev):
	mid = ev["data"].get("match_id")
	row = await db.select_one(["winner", "alpha_score", "beta_score", "alpha_name", "beta_name"], "qc_matches",
							  where=dict(match_id=mid, channel_id=ev["data"].get("channel_id"))) if mid else None
	if not row:
		return None
	names = [row.get("alpha_name") or ev["data"]["team_names"][0], row.get("beta_name") or ev["data"]["team_names"][1]]
	if row.get("winner") is None:
		text = "draw"
	else:
		text = f"{names[row['winner']]} won"
	if row.get("alpha_score") is not None and row.get("beta_score") is not None:
		text += f" ({row['alpha_score']}–{row['beta_score']})"
	return dict(match_id=mid, winner=row.get("winner"), text=text)


async def _step(ev, now):
	guild = dc.get_guild(ev["guild_id"])
	d = ev["data"]
	if ev["state"] in ("finished", "cancelled"):
		h = d.get("cleanup_hours")
		if h and now >= (ev["ended_at"] or now) + h * 3600:
			await teardown(guild, ev)
			await _save(ev, state="archived")
			log.info(f"QueueGen: event #{ev['id']} '{d['name']}' archived, its channels deleted.")
		return
	if guild is not None and ev["state"] == "scheduled":
		await _start_time(guild, ev, now)
		return await _refresh(guild, ev)
	if guild is None or ev["state"] not in ("open", "live"):
		return
	q = _queue(ev)
	if q is None:
		return
	m = _match(ev)
	if ev["state"] == "open":
		if m is not None:
			d["match_id"] = m.id
			d.pop("ended", None)
			d.pop("missing_since", None)
			await _save(ev, state="live")
		elif now - (d.get("last_reminder") or now) >= REMIND_EVERY:
			d["last_reminder"] = int(now)
			await _save(ev)
			waiting = [uid for uid in roster_ids(ev) if all(p.id != uid for p in q.queue)]
			text = guild.get_channel(d["channel_id"])
			if waiting and text:
				try:
					await text.send(f"⏰ {' '.join(f'<@{uid}>' for uid in waiting)}: check in for **{d['name']}** (press **Check in** above).")
				except DiscordException:
					pass
	elif ev["state"] == "live":
		if m is not None:
			if m.id != d.get("match_id"):   # renumbered after a restart
				d["match_id"] = m.id
				await _save(ev)
		elif not bot.series.of(q):
			ended = d.get("ended")
			if ended is None:
				# no word from the match code (a restart lost the match): give it a moment, then count it as canceled
				d.setdefault("missing_since", int(now))
				if now - d["missing_since"] < 30:
					return await _refresh(guild, ev)
				ended = dict(reported=False)
			return await _end_match(guild, ev, ended["reported"])
	await _refresh(guild, ev)


async def _start_time(guild, ev, now):
	""" A scheduled event at its start time: open check-in (with auto-open on), or say what's missing, once. """
	d = ev["data"]
	if now < ev["start_at"] or not d.get("auto_open", True) or d.get("start_notice"):
		return
	short = [d["team_names"][i] for i in (0, 1) if len(d["roster"][i]) != d["team_size"]]
	if not short and _queue(ev) is not None:
		await open_now(guild, ev)
		log.info(f"QueueGen: event #{ev['id']} '{d['name']}' opened check-in at its start time.")
		return
	d["start_notice"] = int(now)
	await _save(ev)
	text = guild.get_channel(d.get("channel_id"))
	if text:
		try:
			await text.send(f"⚠️ **{d['name']}** should start now, but {join_and(short)} "
							f"{'is' if len(short) == 1 else 'are'} short of players: an admin needs to fill the roster on the "
							"QueueGen page and press **Open check-in**.")
		except DiscordException:
			pass


async def _end_match(guild, ev, reported, match=None):
	""" The event's match (or series) is over: the event is finished, or back to check-in if it was canceled. """
	d = ev["data"]
	q = _queue(ev)
	d.pop("ended", None)
	d.pop("missing_since", None)
	text = guild.get_channel(d["channel_id"]) if guild else None
	if not reported:
		d.pop("match_id", None)
		d["last_reminder"] = int(time.time())
		if q is not None:
			await q.reset()
		await _save(ev, state="open")
		if text:
			try:
				msg = await text.send(f"The match of **{d['name']}** was canceled: check in again to restart it.",
									  embed=_embed(guild, ev), view=_view(ev))
				d["message_id"] = msg.id
				await _save(ev)
			except DiscordException:
				pass
		_signatures[ev["id"]] = _signature(ev)
		return
	if match is not None and not match.ranked:   # unrated matches are saved without their winner
		names = d["team_names"]
		d["result"] = dict(match_id=match.id, winner=match.winner,
						   text="draw" if match.winner is None else f"{names[match.winner]} won")
	else:
		d["result"] = await _result(ev) or dict(match_id=d.get("match_id"), winner=None, text="reported")
	await _finish(guild, ev, "finished")
	await _discord_event_status(guild, ev, "finish")
	if text:
		try:
			await text.send(f"🏁 **{d['name']}** is over: {d['result']['text']}." + _cleanup_line(ev))
		except DiscordException:
			pass


async def think(frame_time):
	global _last_think
	if frame_time - _last_think < THINK_EVERY:
		return
	_last_think = frame_time
	for ev in list(events.values()):
		try:
			await _step(ev, frame_time)
		except (Exception, bot.Exc.PubobotException) as e:
			log.error(f"QueueGen: event #{ev['id']}: {e!r}")


@dc.event
async def on_init():
	await load()
	for qc in list(bot.queue_channels.values()):   # channels loaded before the events: point them at their tournament
		if rating_key(qc.id):
			qc.update_rating_system()


@dc.event
async def on_think(frame_time):
	await think(frame_time)
