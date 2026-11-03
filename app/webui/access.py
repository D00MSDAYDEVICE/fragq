# -*- coding: utf-8 -*-
"""
Web panel permissions.

Who can do what in the web interface, per server:
  * the bot owner, the Discord server owner and members with Discord's Administrator permission
    have every permission (implicit, can't be edited);
  * members holding a channel's Admin role have CHANNEL_ADMIN on that channel (PUBobot2 behaviour);
  * grants made on the Users page give a Discord user or role a set of permissions, on the whole
    server or on chosen channels. A member's permissions are the union of everything that applies.

Grants are stored in the database (fragq_web_access) so they survive updates.
These only cover the web panel; Discord commands keep using the channel's moderator / admin roles.
"""
import json
import time

from core.client import dc
from core.config import cfg
from core.database import db

import bot

db.ensure_table(dict(
	tname="fragq_web_access",
	columns=[
		dict(cname="id", ctype=db.types.int, autoincrement=True),
		dict(cname="guild_id", ctype=db.types.int),
		dict(cname="subject_type", ctype=db.types.str),   # "user" or "role"
		dict(cname="subject_id", ctype=db.types.int),
		dict(cname="channels", ctype=db.types.text),      # JSON list of channel ids, [] = whole server
		dict(cname="perms", ctype=db.types.text),         # JSON list of permission names
		dict(cname="granted_by", ctype=db.types.int),
		dict(cname="granted_by_name", ctype=db.types.str),
		dict(cname="granted_at", ctype=db.types.int),
		dict(cname="updated_at", ctype=db.types.int),
	],
	primary_keys=["id"]
))

# (name, group, label, description). Order is the order on the Users page.
CATALOG = [
	("view", "Viewing", "View", "See the server, its channels and queues, the Live tab, settings (read-only) and config exports."),
	("stats", "Viewing", "Stats", "Leaderboard and Matches tabs, player / match CSV downloads."),
	("clear_queues", "Queue control", "Clear queues", "Remove all players from a queue."),
	("pause", "Queue control", "Pause queues", "Pause and resume a channel's queues."),
	("panel", "Queue control", "Queue panel", "Post, move down and remove the Discord queue panel."),
	("edit_channel", "Configuration", "Edit channel settings", "Change and reset channel settings, import channel configs."),
	("edit_queue", "Configuration", "Edit queue settings", "Change and reset queue settings, import queue configs."),
	("manage_queues", "Configuration", "Create / delete queues", "Create new queues and delete existing ones."),
	("manage_channels", "Server", "Manage channels", "Enable the bot on new channels and disable it. Whole-server grants only."),
	("manage_users", "Server", "Manage users", "Use the Users page to grant access to others, up to their own permissions."),
	("manage_connectors", "Server", "Manage connectors", "Create and change game connectors and their keys. Whole-server grants only."),
]
PERMS = [p[0] for p in CATALOG]
ALL = frozenset(PERMS)
SERVER_ONLY = frozenset({"manage_channels", "manage_connectors"})
CHANNEL_ADMIN = ALL - {"manage_channels", "manage_users", "manage_connectors"}

PRESETS = [
	("viewer", "Viewer", ["view", "stats"]),
	("moderator", "Moderator", ["view", "stats", "clear_queues", "pause", "panel"]),
	("manager", "Manager", ["view", "stats", "clear_queues", "pause", "panel", "edit_channel", "edit_queue", "manage_queues"]),
	("admin", "Admin", PERMS),
]

grants = {}  # grant id -> row (channels / perms decoded)


def _decode(row):
	row = dict(row)
	for key in ("channels", "perms"):
		try:
			row[key] = [int(x) if key == "channels" else str(x) for x in json.loads(row[key] or "[]")]
		except (TypeError, ValueError):
			row[key] = []
	row["perms"] = [p for p in row["perms"] if p in ALL]
	return row


async def load():
	grants.clear()
	for row in await db.select(["*"], "fragq_web_access"):
		grants[row["id"]] = _decode(row)


def is_owner(uid):
	return bool(cfg.DC_OWNER_ID) and uid == cfg.DC_OWNER_ID


def is_guild_admin(uid, guild):
	""" Bot owner, server owner or Discord Administrator: every permission, can't be edited. """
	if is_owner(uid) or guild.owner_id == uid:
		return True
	member = guild.get_member(uid)
	return bool(member and member.guild_permissions.administrator)


def moderated_guilds(uid):
	"""
	Servers where the user may review Steam account changes: server admins, and members holding a
	channel's Admin or Moderator role (the Discord roles, as for moderator commands).
	"""
	out = set()
	for guild in dc.guilds:
		if is_guild_admin(uid, guild):
			out.add(guild.id)
			continue
		member = guild.get_member(uid)
		if member is None:
			continue
		roles = {r.id for r in member.roles}
		for qc in bot.queue_channels.values():
			if qc.guild_id == guild.id and any(r is not None and r.id in roles for r in (qc.cfg.admin_role, qc.cfg.moderator_role)):
				out.add(guild.id)
				break
	return out


class Access:
	""" A user's permissions on one server. """

	def __init__(self, uid, guild):
		self.uid, self.guild = uid, guild
		self.admin = is_guild_admin(uid, guild)
		self.server = set(ALL) if self.admin else set()  # permissions on every channel
		self.channels = {}                                 # channel id -> extra permissions there
		if self.admin:
			return
		member = guild.get_member(uid)
		roles = {r.id for r in member.roles} if member else set()
		for qc in bot.queue_channels.values():
			if qc.guild_id == guild.id and qc.cfg.admin_role and qc.cfg.admin_role.id in roles:
				self.channels.setdefault(qc.id, set()).update(CHANNEL_ADMIN)
		for g in grants.values():
			if g["guild_id"] != guild.id:
				continue
			if not ((g["subject_type"] == "user" and g["subject_id"] == uid) or (g["subject_type"] == "role" and g["subject_id"] in roles)):
				continue
			perms = set(g["perms"]) | {"view"}
			if g["channels"]:
				for cid in g["channels"]:
					self.channels.setdefault(cid, set()).update(perms - SERVER_ONLY)
			else:
				self.server.update(perms)

	def on(self, qc_id):
		""" Permissions on one queue channel. """
		return self.server | self.channels.get(qc_id, set())

	def has(self, perm, qc_id=None):
		return perm in (self.server if qc_id is None else self.on(qc_id))

	def any(self):
		return bool(self.server or any(self.channels.values()))

	def visible(self, qc_id):
		return "view" in self.on(qc_id)

	def can_manage_users(self):
		return "manage_users" in self.server or any("manage_users" in p for p in self.channels.values())

	def scope_perms(self, channels):
		""" Permissions held over a whole grant scope: server-wide ([]) or every listed channel. """
		if not channels:
			return set(self.server)
		sets = [self.on(c) for c in channels]
		return set.intersection(*sets) if sets else set()

	def covers(self, channels, perms):
		""" Can this user hand out (or take back) `perms` on `channels`? """
		held = self.scope_perms(channels)
		return "manage_users" in held and set(perms) <= held


def guild_grants(guild_id):
	return [g for g in grants.values() if g["guild_id"] == guild_id]


def find(guild_id, subject_type, subject_id):
	return next((g for g in grants.values()
				 if g["guild_id"] == guild_id and g["subject_type"] == subject_type and g["subject_id"] == subject_id), None)


async def save(guild_id, subject_type, subject_id, channels, perms, by_id, by_name, grant_id=None):
	now = int(time.time())
	perms = [p for p in PERMS if p in set(perms) | {"view"}]
	channels = sorted(set(int(c) for c in channels))
	row = dict(
		guild_id=guild_id, subject_type=subject_type, subject_id=subject_id,
		channels=json.dumps([str(c) for c in channels]), perms=json.dumps(perms),
		granted_by=by_id, granted_by_name=by_name[:191], updated_at=now,
	)
	if grant_id is not None:
		await db.update("fragq_web_access", row, keys=dict(id=grant_id))
		row = dict(grants[grant_id], **row)
	else:
		row["granted_at"] = now
		await db.insert("fragq_web_access", row)
		saved = await db.select(["*"], "fragq_web_access", where=dict(
			guild_id=guild_id, subject_type=subject_type, subject_id=subject_id), one=True)
		row = saved
	row = _decode(row)
	grants[row["id"]] = row
	return row


async def delete(grant_id):
	await db.delete("fragq_web_access", where=dict(id=grant_id))
	return grants.pop(grant_id, None)


async def forget_channel(channel_id):
	""" A channel was disabled: drop it from channel-scoped grants (and grants left with no channel). """
	for g in list(grants.values()):
		if channel_id in g["channels"]:
			rest = [c for c in g["channels"] if c != channel_id]
			if rest:
				await save(g["guild_id"], g["subject_type"], g["subject_id"], rest, g["perms"],
						   g["granted_by"], g["granted_by_name"] or "", grant_id=g["id"])
			else:
				await delete(g["id"])


@dc.event
async def on_init():
	await load()
