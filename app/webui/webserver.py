# -*- coding: utf-8 -*-
"""
FragQ web interface: an aiohttp server that runs inside the bot process, so every change goes
through the live QueueChannel / PickupQueue objects exactly like the chat commands do.
"""
import csv
import hashlib
import io
import json
import os
import re
import time
from datetime import datetime, timezone

from aiohttp import web
from nextcord import ChannelType

import bot
from core.client import dc
from core.config import cfg, __version__
from core.console import log
from core.database import db
from core.utils import get_nick

from webui import auth, schema, access, backup, verify

STATIC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
PLUGINS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "plugins")
CONNECT = "/api/connect/v1"   # game connector API: authenticated with connector keys, not a login
MAX_RESULT_BYTES = 256 * 1024
STARTED = time.time()

runner: web.AppRunner = None


# ------------------------------------------------------------------ helpers

PERM_LABELS = {name: label for name, _, label, _ in access.CATALOG}


def jerror(status, message, **extra):
	return web.json_response(dict(error=message, **extra), status=status)


def _http(exc, message):
	return exc(text=json.dumps(dict(error=message)), content_type="application/json")


def user_id(request) -> int:
	return int(request["user"]["id"])


def is_owner(uid: int) -> bool:
	return access.is_owner(uid)


def guild_channels(guild):
	return [qc for qc in bot.queue_channels.values() if qc.guild_id == guild.id]


def get_access(request, guild):
	""" The user's web panel permissions on `guild`, worked out once per request. """
	key = f"access:{guild.id}"
	if key not in request:
		request[key] = access.Access(user_id(request), guild)
	return request[key]


def perm_list(perms):
	return [p for p in access.PERMS if p in perms]


def client_ip(request):
	""" Caddy, the only way in, always sets X-FragQ-Client-IP itself (replacing anything the client sent). """
	return request.headers.get("X-FragQ-Client-IP") or request.remote or ""


def public_url(request):
	return cfg.WS_ROOT_URL or f"{request.headers.get('X-Forwarded-Proto') or request.scheme}://{request.host}"


def need(acc, perm, qc_id=None):
	if not acc.has(perm, qc_id):
		where = "on this channel" if qc_id is not None else "on this server"
		raise _http(web.HTTPForbidden, f"You don't have the '{PERM_LABELS[perm]}' permission {where}.")


def icon_url(guild, size=128):
	return str(guild.icon.with_size(size)) if guild.icon else None


def get_guild(request):
	try:
		guild = dc.get_guild(int(request.match_info["guild_id"]))
	except ValueError:
		guild = None
	if guild is None:
		raise _http(web.HTTPNotFound, "Guild not found.")
	acc = get_access(request, guild)
	if not acc.any():
		raise _http(web.HTTPForbidden, "You don't have access to this server.")
	return guild, acc


def get_qc(request, perm="view"):
	try:
		qc = bot.queue_channels.get(int(request.match_info["channel_id"]))
	except ValueError:
		qc = None
	if qc is None:
		raise _http(web.HTTPNotFound, "Queue channel not found.")
	guild = dc.get_guild(qc.guild_id)
	if guild is None:
		raise _http(web.HTTPNotFound, "Guild not found.")
	acc = get_access(request, guild)
	if not acc.visible(qc.id):
		raise _http(web.HTTPForbidden, "You don't have access to this channel.")
	need(acc, perm, qc.id)
	return qc, guild, acc


def get_queue(request, perm="view"):
	qc, guild, acc = get_qc(request, perm)
	try:
		qid = int(request.match_info["queue_id"])
	except ValueError:
		qid = None
	q = next((q for q in qc.queues if q.id == qid), None)
	if q is None:
		raise _http(web.HTTPNotFound, "Queue not found.")
	return q, qc, guild, acc


async def read_json(request):
	try:
		return await request.json()
	except Exception:
		raise web.HTTPBadRequest(text=json.dumps(dict(error="Invalid JSON body.")), content_type="application/json")


def member_dict(m):
	if m is None:
		return None
	avatar = getattr(m, "display_avatar", None)
	return dict(id=str(m.id), name=get_nick(m), avatar=str(avatar.with_size(64)) if avatar else None)


def queue_dict(q):
	return dict(id=str(q.id), name=q.name, size=q.cfg.size, players=len(q.queue))


def channel_dict(qc, guild, acc):
	channel = guild.get_channel(qc.id)
	return dict(
		id=str(qc.id),
		name=channel.name if channel else qc.cfg.cfg_info.get('channel_name', str(qc.id)),
		order=((channel.category.position + 1) * 10000 if channel and channel.category else 0) + (channel.position if channel else 9999),
		category=channel.category.name if channel and channel.category else None,
		queues=[queue_dict(q) for q in qc.queues],
		panel=bool(bot.panel.message_id(qc)),
		paused=qc.paused,
		perms=perm_list(acc.on(qc.id)),
	)


# ------------------------------------------------------------------ middleware

@web.middleware
async def middleware(request, handler):
	path = request.path
	if path.startswith(CONNECT + "/"):
		if not bot.bot_ready:
			return jerror(503, "The bot is still connecting to Discord, try again in a moment.")
	elif path.startswith("/api/"):
		user = auth.get_user(request)
		if user is None:
			return jerror(401, "Not logged in.")
		request["user"] = user
		if request.method not in ("GET", "HEAD", "OPTIONS"):
			# Cross-site requests can't set custom headers without a CORS preflight, which we never allow.
			if request.headers.get("X-FragQ") != "1":
				return jerror(403, "Missing request header.")
		if path != "/api/me" and not bot.bot_ready:
			return jerror(503, "The bot is still connecting to Discord, try again in a moment.")
	try:
		resp = await handler(request)
	except web.HTTPException as e:
		if path.startswith("/api/") and e.content_type != "application/json" and e.status >= 400:
			return jerror(e.status, e.text or e.reason)
		raise
	except Exception as e:
		log.error(f"WEBUI| {request.method} {path} failed: {e!r}")
		if path.startswith("/api/"):
			return jerror(500, "Internal error: " + schema.error_text(e))
		raise
	resp.headers.setdefault("X-Content-Type-Options", "nosniff")
	resp.headers.setdefault("Referrer-Policy", "same-origin")
	if path.startswith("/api/"):
		resp.headers.setdefault("Cache-Control", "no-store")
	return resp


# ------------------------------------------------------------------ pages

def _index_html():
	""" index.html with ?v= set to a hash of the static files, so browsers fetch them again after an update. """
	digest = hashlib.sha1()
	for name in sorted(os.listdir(STATIC)):
		path = os.path.join(STATIC, name)
		if os.path.isfile(path):
			with open(path, "rb") as f:
				digest.update(f.read())
	with open(os.path.join(STATIC, "index.html"), encoding="utf-8") as f:
		return re.sub(r"\?v=[\w.-]+", "?v=" + digest.hexdigest()[:12], f.read())


INDEX_HTML = _index_html()


async def index(request):
	resp = web.Response(text=INDEX_HTML, content_type="text/html")
	resp.headers["Cache-Control"] = "no-cache"
	resp.headers["X-Frame-Options"] = "DENY"
	return resp


async def healthz(request):
	return web.json_response(dict(ok=True, discord=bot.bot_ready))


# ------------------------------------------------------------------ api: session / bot

async def api_me(request):
	user = request["user"]
	me = dc.user
	return web.json_response(dict(
		user=dict(
			id=user["id"], name=user["name"], username=user.get("username"),
			avatar=auth.avatar_url(user["id"], user.get("avatar")),
			owner=is_owner(int(user["id"])),
			manage_users=any(get_access(request, g).can_manage_users() for g in dc.guilds),
			manage_connectors=any(get_access(request, g).has("manage_connectors") for g in dc.guilds),
			steam_review=steam_scope(request) is not False,
			steam_pending=len(reviewable_requests(request)),
		),
		bot=dict(
			name=me.name if me else "FragQ",
			avatar=str(me.display_avatar.with_size(128)) if me else None,
			ready=bot.bot_ready,
			version=__version__,
			invite=cfg.DC_INVITE_LINK,
			commands=cfg.COMMANDS_URL or "https://d00msdaydevice.github.io/fragq/reference/commands/",
		),
	))


async def api_logout(request):
	resp = web.json_response(dict(ok=True))
	resp.del_cookie(auth.COOKIE, path="/")
	return resp


async def api_schema(request):
	return web.json_response(dict(
		channel=schema.factory_schema(bot.QueueChannel.cfg_factory),
		queue=schema.factory_schema(bot.PickupQueue.cfg_factory),
	))


# ------------------------------------------------------------------ bot-wide settings (owner only)

def settings_dict():
	key = bot.steam.api_key()
	return dict(
		steam=dict(
			api_key_set=bool(key),
			api_key_hint=key[-4:] if key else None,  # the key itself never leaves the server
			require_link=bot.steam.required(),
			linked=len(bot.steam.links),
		),
	)


def owner_error(request):
	if not is_owner(user_id(request)):
		return jerror(403, "Only the bot owner can change bot settings.")


async def api_settings(request):
	if err := owner_error(request):
		return err
	return web.json_response(settings_dict())


async def api_settings_save(request):
	if err := owner_error(request):
		return err
	body = await read_json(request)
	steam = body.get("steam") or {}
	who = request["user"]["name"]
	if "api_key" in steam:
		key = str(steam["api_key"] or "").strip()
		if key:
			if not re.fullmatch(r"[0-9A-Fa-f]{32}", key):
				msg = "A Steam Web API key is 32 letters and digits (0-9, A-F)."
				return jerror(400, msg, fields=dict(api_key=msg))
			try:
				await bot.steam.test_key(key)
			except bot.Exc.PubobotException as e:
				return jerror(400, str(e), fields=dict(api_key=str(e)))
		await bot.settings.put("steam_api_key", key)
		log.info(f"WEBUI| {who} {'set' if key else 'removed'} the Steam API key.")
	if "require_link" in steam:
		await bot.settings.put("require_steam_link", bool(steam["require_link"]))
		log.info(f"WEBUI| {who} turned {'on' if steam['require_link'] else 'off'} 'Require linked Steam IDs'.")
	return web.json_response(settings_dict())


async def api_settings_steam_test(request):
	if err := owner_error(request):
		return err
	if not bot.steam.api_key():
		return jerror(400, "No Steam API key is saved.")
	try:
		await bot.steam.test_key(bot.steam.api_key())
	except bot.Exc.PubobotException as e:
		return jerror(400, str(e))
	return web.json_response(dict(ok=True))


async def api_backup(request):
	if err := owner_error(request):
		return err
	data = backup.build(include_steam_key=request.query.get("steam_key") == "1")
	name = "fragq-backup-" + time.strftime("%Y-%m-%d", time.localtime()) + ".json"
	log.info(f"WEBUI| {request['user']['name']} downloaded a settings backup{' (with the Steam API key)' if 'steam_api_key' in data['settings'] else ''}.")
	return web.json_response(data, dumps=lambda d: json.dumps(d, indent=1, ensure_ascii=False),
							 headers={"Content-Disposition": f'attachment; filename="{name}"'})


async def api_restore(request):
	if err := owner_error(request):
		return err
	body = await read_json(request)
	parts = [p for p in body.get("parts") or [] if p in backup.PARTS]
	if not parts:
		return jerror(400, "Choose what to restore.")
	try:
		report = await backup.restore(body.get("backup"), parts, dry_run=bool(body.get("dry_run")), who=request["user"]["name"])
	except ValueError as e:
		return jerror(400, str(e))
	return web.json_response(dict(report=report, dry_run=bool(body.get("dry_run"))))


# ------------------------------------------------------------------ Steam links and change approvals

def steam_scope(request):
	"""
	None: every player (bot owner). A set of guild ids: players who are members there (server admins and
	channel admin / moderator roles). False: no access.
	"""
	key = "steam_scope"
	if key not in request:
		uid = user_id(request)
		request[key] = None if is_owner(uid) else (access.moderated_guilds(uid) or False)
	return request[key]


def in_steam_scope(request, uid):
	scope = steam_scope(request)
	if scope is None:
		return True
	return bool(scope) and any(g.id in scope and g.get_member(uid) for g in dc.guilds)


def reviewable_requests(request):
	if steam_scope(request) is False:
		return []
	me = user_id(request)
	return [r for r in bot.steam.requests.values()
			if in_steam_scope(request, r["user_id"]) and (r["user_id"] != me or is_owner(me))]


def steam_row_dict(row):
	return dict(
		steam_id=row["steam_id"], persona=row.get("persona"), steam_avatar=row.get("avatar_url"),
		profile_url=row.get("profile_url") or bot.steam.profile_url(row["steam_id"]),
		verified_by=row.get("verified_by") or "",
	)


def steam_link_dict(request, uid):
	row, req = bot.steam.links.get(uid), bot.steam.requests.get(uid)
	user = dc.get_user(uid)
	me = user_id(request)
	base = row or req
	return dict(
		user_id=str(uid),
		name=(user.display_name if user else None) or base.get("nick") or str(uid),
		avatar=str(user.display_avatar.with_size(64)) if user else None,
		**(steam_row_dict(row) if row else dict(steam_id=None, persona=None, steam_avatar=None, profile_url=None, verified_by="")),
		linked_at=row.get("linked_at") if row else None,
		pending=dict(steam_row_dict(req), requested_at=req.get("requested_at")) if req else None,
		can_review=bool(req) and (uid != me or is_owner(me)),
	)


def steam_target(request):
	if steam_scope(request) is False:
		raise _http(web.HTTPForbidden, "Only moderators and admins can manage Steam links.")
	try:
		uid = int(request.match_info["user_id"])
	except ValueError:
		raise _http(web.HTTPBadRequest, "Bad user id.")
	if not in_steam_scope(request, uid):
		raise _http(web.HTTPForbidden, "This player isn't on a server you moderate.")
	return uid


async def api_steam_links(request):
	if steam_scope(request) is False:
		return jerror(403, "Only moderators and admins can see linked Steam accounts.")
	uids = [uid for uid in set(bot.steam.links) | set(bot.steam.requests) if in_steam_scope(request, uid)]
	rows = [steam_link_dict(request, uid) for uid in uids]
	rows.sort(key=lambda r: (r["pending"] is None, -((r["pending"] or {}).get("requested_at") or r["linked_at"] or 0)))
	return web.json_response(dict(links=rows, owner=steam_scope(request) is None))


async def api_steam_approve(request):
	uid = steam_target(request)
	if uid == user_id(request) and not is_owner(uid):
		return jerror(403, "Ask another moderator to approve your own change.")
	try:
		row = await bot.steam.approve(uid)
	except bot.Exc.PubobotException as e:
		return jerror(409, str(e))
	log.info(f"WEBUI| {request['user']['name']} approved the Steam account change of {row.get('nick') or uid} to {row['steam_id']}.")
	await bot.steam.notify(uid, f"Your Steam account change was approved: you are now linked to {row.get('persona') or row['steam_id']} ({row['steam_id']}).")
	return web.json_response(dict(ok=True))


async def api_steam_reject(request):
	uid = steam_target(request)
	if uid == user_id(request) and not is_owner(uid):
		return jerror(403, "Ask another moderator to review your own change.")
	req = await bot.steam.reject(uid)
	if req is None:
		return jerror(404, "This player has no pending Steam account change.")
	log.info(f"WEBUI| {request['user']['name']} rejected the Steam account change of {req.get('nick') or uid} to {req['steam_id']}.")
	old = bot.steam.links.get(uid)
	await bot.steam.notify(uid, "Your Steam account change was not approved." + (
		f" You stay linked to {old.get('persona') or old['steam_id']} ({old['steam_id']})." if old else ""))
	return web.json_response(dict(ok=True))


async def api_steam_unlink(request):
	uid = steam_target(request)
	row = await bot.steam.unlink(uid)
	if row is None:
		return jerror(404, "This player has no linked Steam account.")
	log.info(f"WEBUI| {request['user']['name']} unlinked Steam account {row['steam_id']} from {row.get('nick') or uid}.")
	return web.json_response(dict(ok=True))


async def api_status(request):
	uid = user_id(request)
	if not is_owner(uid):
		return jerror(403, "Only the bot owner can see the bot status.")
	return web.json_response(dict(
		uptime=int(time.time() - STARTED),
		latency=round(dc.latency * 1000) if dc.latency == dc.latency else None,
		guilds=len(dc.guilds),
		channels=len(bot.queue_channels),
		queues=sum(len(qc.queues) for qc in bot.queue_channels.values()),
		active_queues=len(bot.active_queues),
		active_matches=len(bot.active_matches),
		log=list(log.recent)[-200:],
	))


# ------------------------------------------------------------------ api: guilds

async def api_guilds(request):
	guilds = []
	for guild in sorted(dc.guilds, key=lambda g: g.name.lower()):
		acc = get_access(request, guild)
		if not acc.any():
			continue
		guilds.append(dict(
			id=str(guild.id), name=guild.name, icon=icon_url(guild),
			admin=acc.admin, perms=perm_list(acc.server), manage_users=acc.can_manage_users(),
			manage_connectors=acc.has("manage_connectors"),
			channels=sum(1 for qc in guild_channels(guild) if acc.visible(qc.id)),
		))
	return web.json_response(dict(guilds=guilds))


async def api_guild(request):
	guild, acc = get_guild(request)
	channels = sorted(
		(channel_dict(qc, guild, acc) for qc in guild_channels(guild) if acc.visible(qc.id)),
		key=lambda c: c["order"]
	)
	me = guild.me
	text_channels = [
		dict(
			id=str(c.id), name=c.name, category=c.category.name if c.category else None,
			enabled=c.id in bot.queue_channels,
			can_send=bool(me and c.permissions_for(me).send_messages),
		)
		for c in sorted(guild.text_channels, key=lambda c: (c.category.position if c.category else -1, c.position))
	]
	roles = [
		dict(id=str(r.id), name=r.name, color=f"#{r.color.value:06x}" if r.color.value else None, managed=r.managed)
		for r in reversed(guild.roles)
	]
	return web.json_response(dict(
		id=str(guild.id), name=guild.name, icon=icon_url(guild),
		admin=acc.admin, perms=perm_list(acc.server), manage_users=acc.can_manage_users(),
		members=guild.member_count,
		channels=channels, text_channels=text_channels, roles=roles,
	))


async def api_guild_overview(request):
	guild, acc = get_guild(request)
	qcs = [qc for qc in guild_channels(guild) if acc.visible(qc.id)]
	matches = [m for m in bot.active_matches if m.qc in qcs]
	active = [q for qc in qcs for q in qc.queues if q.length]
	return web.json_response(dict(
		channels=len(qcs),
		queues=sum(len(qc.queues) for qc in qcs),
		players_in_queue=len({m.id for q in active for m in q.queue}),
		active_queues=[dict(queue_dict(q), channel=str(q.qc.id), who=[member_dict(m) for m in q.queue]) for q in active],
		matches=[match_dict(m) for m in matches],
	))


async def api_add_channel(request):
	guild, acc = get_guild(request)
	need(acc, "manage_channels")
	body = await read_json(request)
	try:
		channel = guild.get_channel(int(body.get("channel_id")))
	except (TypeError, ValueError):
		channel = None
	if channel is None or channel.type != ChannelType.text:
		return jerror(400, "Text channel not found.")
	if channel.id in bot.queue_channels:
		return jerror(409, "The bot is already enabled on this channel.")
	qc = await bot.QueueChannel.create(channel)
	bot.queue_channels[channel.id] = qc
	await qc.update_info(channel)
	log.info(f"WEBUI| {request['user']['name']} enabled the bot on {guild.name}>#{channel.name}.")
	return web.json_response(channel_dict(qc, guild, acc), status=201)


# ------------------------------------------------------------------ api: users page (web panel access)

def _subject(guild, kind, sid):
	if kind == "role":
		role = guild.get_role(sid)
		return dict(type="role", id=str(sid), name=role.name if role else "Deleted role",
					color=f"#{role.color.value:06x}" if role and role.color.value else None, missing=role is None)
	user = guild.get_member(sid) or dc.get_user(sid)
	avatar = getattr(user, "display_avatar", None)
	return dict(type="user", id=str(sid), name=get_nick(user) if user else f"Unknown user ({sid})",
				avatar=str(avatar.with_size(64)) if avatar else None, missing=user is None)


def _grant_dict(guild, acc, g):
	return dict(
		id=g["id"], subject=_subject(guild, g["subject_type"], g["subject_id"]),
		channels=[str(c) for c in g["channels"]], perms=perm_list(g["perms"]),
		granted_by=g.get("granted_by_name"), granted_at=g.get("granted_at"), updated_at=g.get("updated_at"),
		editable=acc.covers(g["channels"], g["perms"]) and not (g["subject_type"] == "user" and g["subject_id"] == acc.uid),
	)


def _implicit(guild):
	""" Built-in access shown as locked rows. """
	rows = []
	if cfg.DC_OWNER_ID:
		rows.append(dict(subject=_subject(guild, "user", cfg.DC_OWNER_ID), why="Bot owner", channels=[], perms=list(access.PERMS)))
	if guild.owner_id and guild.owner_id != cfg.DC_OWNER_ID:
		rows.append(dict(subject=_subject(guild, "user", guild.owner_id), why="Server owner", channels=[], perms=list(access.PERMS)))
	for r in guild.roles:
		if getattr(getattr(r, "permissions", None), "administrator", False) and not r.managed:
			rows.append(dict(subject=_subject(guild, "role", r.id), why="Discord Administrator", channels=[], perms=list(access.PERMS)))
	for qc in guild_channels(guild):
		if qc.cfg.admin_role:
			rows.append(dict(subject=_subject(guild, "role", qc.cfg.admin_role.id), why="Channel admin role",
							 channels=[str(qc.id)], perms=perm_list(access.CHANNEL_ADMIN)))
	return rows


def _users_guild(request):
	guild, acc = get_guild(request)
	if not acc.can_manage_users():
		raise _http(web.HTTPForbidden, "You don't have the 'Manage users' permission on this server.")
	return guild, acc


def _check_grant(guild, acc, channels, perms):
	""" Validates a grant scope / permission set the user wants to save. Returns (channel ids, perms) or raises. """
	try:
		channels = sorted({int(c) for c in channels or []})
	except (TypeError, ValueError):
		raise _http(web.HTTPBadRequest, "Bad channel id.")
	qcs = {qc.id for qc in guild_channels(guild)}
	if any(c not in qcs for c in channels):
		raise _http(web.HTTPBadRequest, "One of the channels is not a queue channel on this server.")
	perms = set(perms or []) | {"view"}
	if not perms <= access.ALL:
		raise _http(web.HTTPBadRequest, "Unknown permission.")
	if channels and perms & access.SERVER_ONLY:
		raise _http(web.HTTPBadRequest, "'Manage channels' and 'Manage connectors' can only be given on the whole server.")
	if not acc.covers(channels, perms):
		raise _http(web.HTTPForbidden, "You can only grant permissions you have yourself, on servers or channels where you can manage users.")
	return channels, perms


async def api_access(request):
	guild, acc = _users_guild(request)
	shown = [g for g in access.guild_grants(guild.id)
			 if acc.has("manage_users") or any("manage_users" in acc.on(c) for c in g["channels"])]
	return web.json_response(dict(
		catalog=[dict(name=n, group=gr, label=l, description=d) for n, gr, l, d in access.CATALOG],
		presets=[dict(id=i, label=l, perms=p) for i, l, p in access.PRESETS],
		server_only=sorted(access.SERVER_ONLY),
		me=dict(admin=acc.admin, server=perm_list(acc.server),
				channels={str(c): perm_list(p) for c, p in acc.channels.items() if p}),
		channels=[dict(id=str(qc.id), name=(guild.get_channel(qc.id).name if guild.get_channel(qc.id) else str(qc.id)))
				  for qc in sorted(guild_channels(guild), key=lambda q: q.cfg.cfg_info.get("channel_name") or "")
				  if "manage_users" in acc.on(qc.id)],
		grants=sorted((_grant_dict(guild, acc, g) for g in shown), key=lambda g: g["subject"]["name"].lower()),
		implicit=_implicit(guild),
	))


async def api_access_members(request):
	guild, acc = _users_guild(request)
	term = request.query.get("q", "").strip().lower()
	found = []
	for m in guild.members:
		if m.bot:
			continue
		names = [m.name, getattr(m, "nick", None) or "", getattr(m, "global_name", None) or ""]
		if not term or any(term in n.lower() for n in names if n):
			found.append(m)
	found.sort(key=lambda m: get_nick(m).lower())
	return web.json_response(dict(members=[
		dict(member_dict(m), username=m.name) for m in found[:25]
	], more=len(found) > 25))


async def api_access_create(request):
	guild, acc = _users_guild(request)
	body = await read_json(request)
	kind = body.get("subject_type")
	try:
		sid = int(body.get("subject_id"))
	except (TypeError, ValueError):
		return jerror(400, "Pick a member or a role.")
	if kind == "user":
		member = guild.get_member(sid)
		if member is None or member.bot:
			return jerror(400, "That member isn't on this server.")
		if sid == acc.uid:
			return jerror(400, "You can't change your own access.")
	elif kind == "role":
		role = guild.get_role(sid)
		if role is None or role.is_default():
			return jerror(400, "Pick a role other than @everyone.")
	else:
		return jerror(400, "Pick a member or a role.")
	if (old := access.find(guild.id, kind, sid)) is not None:
		return jerror(409, "This member or role already has access. Edit their entry instead.", grant_id=old["id"])
	channels, perms = _check_grant(guild, acc, body.get("channels"), body.get("perms"))
	g = await access.save(guild.id, kind, sid, channels, perms, acc.uid, request["user"]["name"])
	log.info(f"WEBUI| {request['user']['name']} gave {kind} {sid} web access on {guild.name}: {', '.join(g['perms'])}"
			 f"{' (channels ' + ', '.join(map(str, channels)) + ')' if channels else ''}.")
	return web.json_response(_grant_dict(guild, acc, g), status=201)


def _existing_grant(request, guild, acc):
	try:
		g = access.grants.get(int(request.match_info["grant_id"]))
	except ValueError:
		g = None
	if g is None or g["guild_id"] != guild.id:
		raise _http(web.HTTPNotFound, "Access entry not found.")
	if g["subject_type"] == "user" and g["subject_id"] == acc.uid:
		raise _http(web.HTTPBadRequest, "You can't change your own access.")
	if not acc.covers(g["channels"], g["perms"]):
		raise _http(web.HTTPForbidden, "This entry has more access than you can manage.")
	return g


async def api_access_update(request):
	guild, acc = _users_guild(request)
	g = _existing_grant(request, guild, acc)
	body = await read_json(request)
	channels, perms = _check_grant(guild, acc, body.get("channels"), body.get("perms"))
	g = await access.save(guild.id, g["subject_type"], g["subject_id"], channels, perms, acc.uid, request["user"]["name"], grant_id=g["id"])
	log.info(f"WEBUI| {request['user']['name']} changed web access of {g['subject_type']} {g['subject_id']} on {guild.name}: {', '.join(g['perms'])}.")
	return web.json_response(_grant_dict(guild, acc, g))


async def api_access_delete(request):
	guild, acc = _users_guild(request)
	g = _existing_grant(request, guild, acc)
	await access.delete(g["id"])
	log.info(f"WEBUI| {request['user']['name']} revoked web access of {g['subject_type']} {g['subject_id']} on {guild.name}.")
	return web.json_response(dict(ok=True))


# ------------------------------------------------------------------ api: game connectors (web panel side)

def _connectors_guild(request):
	guild, acc = get_guild(request)
	need(acc, "manage_connectors")
	return guild, acc


def _get_connector(request, guild):
	try:
		c = bot.connectors.connectors.get(int(request.match_info["connector_id"]))
	except ValueError:
		c = None
	if c is None or c["guild_id"] != guild.id:
		raise _http(web.HTTPNotFound, "Connector not found.")
	return c


def connector_dict(c, counts=None):
	n, last = (counts or {}).get(c["id"], (0, 0))
	live = {q.id for q, _ in bot.connectors.queue_objects(c)}
	return dict(
		id=str(c["id"]), name=c["name"], game=c["game"], prefix=c["prefix"], state=bot.connectors.state(c),
		queues=[str(q) for q in c["queues"] if q in live], unmatched_queue=str(c["unmatched_queue"] or ""),
		can_results=c["can_results"], can_check=c["can_check"], can_link=c["can_link"], can_export=c["can_export"],
		allowed_ips=c["allowed_ips"].split() if c["allowed_ips"] else [], rate_limit=c["rate_limit"], expires_at=c["expires_at"],
		disabled=c["disabled"], requests=c["requests"], last_used_at=c["last_used_at"], last_used_ip=c["last_used_ip"],
		last_denied_at=c["last_denied_at"], last_denied_ip=c["last_denied_ip"], last_denied_reason=c["last_denied_reason"],
		created_at=c["created_at"], created_by=c["created_by_name"], results=n, last_result_at=last,
	)


async def _connector_body(request):
	body = await read_json(request)
	if not isinstance(body, dict):
		raise _http(web.HTTPBadRequest, "Invalid request.")
	return body


async def api_connectors(request):
	guild, acc = _connectors_guild(request)
	counts = await bot.connectors.summary(guild.id)
	queues = []
	for qc in sorted(guild_channels(guild), key=lambda q: q.cfg.cfg_info.get("channel_name") or ""):
		channel = guild.get_channel(qc.id)
		for q in qc.queues:
			queues.append(dict(id=str(q.id), name=q.name, channel=channel.name if channel else str(qc.id)))
	return web.json_response(dict(
		connectors=[connector_dict(c, counts) for c in bot.connectors.guild_connectors(guild.id)],
		games=[dict(id=k, label=label, emoji=emoji) for k, label, emoji, _ in bot.connectors.GAMES],
		queues=queues, public_url=public_url(request), api_url=public_url(request) + CONNECT, plugins=dict(quakelive="/downloads/minqlx/fragq.py"),
		default_rate=bot.connectors.DEFAULT_RATE, max_rate=bot.connectors.MAX_RATE,
	))


async def api_connector_create(request):
	guild, acc = _connectors_guild(request)
	body = await _connector_body(request)
	try:
		c, key = await bot.connectors.create(guild.id, body, acc.uid, request["user"]["name"])
	except ValueError as e:
		return jerror(400, str(e))
	log.info(f"WEBUI| {request['user']['name']} created connector '{c['name']}' on {guild.name}.")
	return web.json_response(dict(connector=connector_dict(c), key=key))


async def api_connector_update(request):
	guild, acc = _connectors_guild(request)
	c = _get_connector(request, guild)
	body = await _connector_body(request)
	try:
		await bot.connectors.update(c, body)
	except ValueError as e:
		return jerror(400, str(e))
	log.info(f"WEBUI| {request['user']['name']} changed connector '{c['name']}' on {guild.name}.")
	return web.json_response(dict(connector=connector_dict(c)))


async def api_connector_rotate(request):
	guild, acc = _connectors_guild(request)
	c, key = await bot.connectors.rotate(_get_connector(request, guild))
	log.info(f"WEBUI| {request['user']['name']} replaced the key of connector '{c['name']}' on {guild.name}.")
	return web.json_response(dict(connector=connector_dict(c), key=key))


async def api_connector_toggle(request):
	guild, acc = _connectors_guild(request)
	c = _get_connector(request, guild)
	await bot.connectors.set_disabled(c, not c["disabled"])
	log.info(f"WEBUI| {request['user']['name']} {'disabled' if c['disabled'] else 'enabled'} connector '{c['name']}' on {guild.name}.")
	return web.json_response(dict(connector=connector_dict(c)))


async def api_connector_delete(request):
	guild, acc = _connectors_guild(request)
	c = _get_connector(request, guild)
	await bot.connectors.delete(c)
	log.info(f"WEBUI| {request['user']['name']} deleted connector '{c['name']}' on {guild.name}.")
	return web.json_response(dict(ok=True))


async def api_connector_test(request):
	""" Post a made-up result in the connector's channel, to see what its results look like. """
	guild, acc = _connectors_guild(request)
	c = _get_connector(request, guild)
	queues = bot.connectors.queue_objects(c)
	if not queues:
		return jerror(400, "This connector has no queues.")
	q, qc = next(((q, qc) for q, qc in queues if q.id == c["unmatched_queue"]), queues[0])
	result = bot.connectors.normalize(bot.connectors.sample_result(c))
	if not await bot.connectors.post(c, result, queue_qc=qc, test=True):
		return jerror(502, "FragQ couldn't post in that channel. Check the bot's permissions there.")
	channel = guild.get_channel(qc.id)
	return web.json_response(dict(ok=True, channel=channel.name if channel else str(qc.id)))


# ------------------------------------------------------------------ connector API (game servers, connector keys)

def connect_api(handler, need=None):
	""" Checks the connector key and turns refusals into JSON errors for the game plugin. """
	async def wrapper(request):
		h = request.headers.get("Authorization", "")
		key = h[7:].strip() if h[:7].lower() == "bearer " else request.headers.get("X-FragQ-Key", "").strip()
		try:
			c = bot.connectors.authenticate(key, client_ip(request), need)
			body = None
			if request.method == "POST":
				raw = await request.content.read(MAX_RESULT_BYTES + 1)
				if len(raw) > MAX_RESULT_BYTES:
					raise bot.connectors.ConnectorError(413, f"The body can be at most {MAX_RESULT_BYTES // 1024} KB.")
				try:
					body = json.loads(raw.decode("utf-8"))
				except (UnicodeDecodeError, ValueError):
					raise bot.connectors.ConnectorError(400, "The body must be JSON.")
			return web.json_response(await handler(c, body))
		except bot.connectors.ConnectorError as e:
			return web.json_response(dict(ok=False, error=e.message), status=e.status, headers=e.headers)
	return wrapper


async def connect_status(c, body):
	return bot.connectors.status(c)


async def connect_results(c, body):
	return await bot.connectors.receive(c, body)


async def connect_linked(c, body):
	return bot.connectors.linked(c, body.get("steam_ids") if isinstance(body, dict) else None)


async def connect_link(c, body):
	return await bot.connectors.request_link(c, body)


async def connect_steam_links(c, body):
	return bot.connectors.steam_links(c)


async def download_plugin(request):
	path = os.path.join(PLUGINS, "minqlx", "fragq.py")
	if request.match_info["name"] != "fragq.py" or not os.path.isfile(path):
		raise web.HTTPNotFound()
	return web.FileResponse(path, headers={"Content-Type": "text/x-python; charset=utf-8",
										   "Content-Disposition": 'attachment; filename="fragq.py"'})


# ------------------------------------------------------------------ api: queue channels

async def api_channel(request):
	qc, guild, acc = get_qc(request)
	return web.json_response(dict(
		channel_dict(qc, guild, acc),
		values=schema.ui_values(qc.cfg),
		can_delete=acc.has("manage_channels"),
	))


async def api_channel_save(request):
	qc, guild, acc = get_qc(request, "edit_channel")
	body = await read_json(request)
	try:
		await schema.apply(qc.cfg, body.get("values", {}), guild)
	except schema.ConfigError as e:
		return jerror(400, "Some fields are invalid.", fields=e.errors)
	log.info(f"WEBUI| {request['user']['name']} updated #{guild.get_channel(qc.id) or qc.id} config: {', '.join(body.get('values', {}))}.")
	return web.json_response(dict(values=schema.ui_values(qc.cfg)))


async def api_channel_reset(request):
	qc, guild, acc = get_qc(request, "edit_channel")
	name = request.match_info["var"]
	if (v := qc.cfg_factory.variables.get(name)) is None:
		return jerror(404, "Unknown variable.")
	try:
		await schema.apply(qc.cfg, {name: schema.default_input(v)}, guild)
	except schema.ConfigError as e:
		return jerror(400, "Could not reset the field.", fields=e.errors)
	return web.json_response(dict(values=schema.ui_values(qc.cfg)))


async def api_channel_export(request):
	qc, guild, acc = get_qc(request)
	return web.json_response(schema.export_values(qc.cfg))


async def api_channel_delete(request):
	qc, guild, acc = get_qc(request)
	need(acc, "manage_channels")
	await bot.panel.remove(qc)
	for q in list(qc.queues):
		await q.reset()
		await q.cfg.delete()
		await bot.connectors.forget_queue(q.id)
	await qc.cfg.delete()
	bot.queue_channels.pop(qc.id, None)
	await access.forget_channel(qc.id)
	log.info(f"WEBUI| {request['user']['name']} disabled the bot on {guild.name}>#{qc.cfg.cfg_info.get('channel_name', qc.id)}.")
	return web.json_response(dict(ok=True))


async def api_create_queue(request):
	qc, guild, acc = get_qc(request, "manage_queues")
	body = await read_json(request)
	name = str(body.get("name", "")).strip()
	try:
		bot.PickupQueue.validate_name(name)
	except ValueError as e:
		return jerror(400, str(e), fields=dict(name=str(e)))
	if name.lower() in (q.name.lower() for q in qc.queues):
		return jerror(409, "A queue with this name already exists.", fields=dict(name="Already exists on this channel."))
	try:
		size = int(body.get("size", 8))
		if not 1 < size <= 1000:
			raise ValueError
	except (TypeError, ValueError):
		return jerror(400, "Queue size must be a number between 2 and 1000.", fields=dict(size="2 - 1000"))

	cfg_obj = await bot.PickupQueue.cfg_factory.spawn(guild, f_key=qc.id)
	try:
		await cfg_obj.update({"name": name, "size": str(size)})
	except Exception as e:
		await cfg_obj.delete()
		return jerror(400, schema.error_text(e))
	q = bot.PickupQueue(qc, cfg_obj)
	qc.queues.append(q)
	log.info(f"WEBUI| {request['user']['name']} created queue {name} on {guild.name}.")
	return web.json_response(queue_dict(q), status=201)


async def api_panel_post(request):
	qc, guild, acc = get_qc(request, "panel")
	try:
		await bot.panel.post(qc)
	except bot.Exc.PubobotException as e:
		return jerror(400, str(e))
	log.info(f"WEBUI| {request['user']['name']} posted the queue panel in #{qc.cfg.cfg_info.get('channel_name', qc.id)}.")
	return web.json_response(dict(ok=True, panel=True))


async def api_panel_delete(request):
	qc, guild, acc = get_qc(request, "panel")
	await bot.panel.remove(qc)
	return web.json_response(dict(ok=True, panel=False))


async def api_pause(request):
	qc, guild, acc = get_qc(request, "pause")
	body = await read_json(request)
	paused = bool(body.get("paused"))
	await qc.set_paused(paused)
	await bot.panel.refresh(qc, force=True)
	log.info(f"WEBUI| {request['user']['name']} {'paused' if paused else 'resumed'} the queues in #{qc.cfg.cfg_info.get('channel_name', qc.id)}.")
	return web.json_response(dict(ok=True, paused=paused))


async def api_channel_live(request):
	qc, guild, acc = get_qc(request)
	return web.json_response(dict(
		queues=[dict(queue_dict(q), who=[member_dict(m) for m in q.queue]) for q in qc.queues],
		matches=[match_dict(m) for m in bot.active_matches if m.qc is qc],
	))


MATCH_STATES = {0: "starting", 1: "check-in", 2: "draft", 3: "waiting report"}


def match_dict(m):
	return dict(
		id=m.id,
		queue=m.queue.name,
		channel=str(m.qc.id),
		state=MATCH_STATES.get(m.state, str(m.state)),
		ranked=bool(m.ranked),
		started=m.start_time,
		maps=list(m.maps),
		teams=[
			dict(name=t.name, emoji=t.emoji, players=[member_dict(p) for p in t])
			for t in m.teams if t.idx >= 0 or len(t)
		],
	)


# ------------------------------------------------------------------ api: stats

async def _players(qc):
	rows = await db.select(
		['user_id', 'nick', 'is_hidden', 'rating', 'deviation', 'wins', 'losses', 'draws', 'streak', 'last_ranked_match_at'],
		'qc_players', where={'channel_id': qc.rating.channel_id}, order_by='rating'
	)
	return rows or []


async def _matches(qc, limit=None):
	matches = await db.select(['*'], 'qc_matches', where={'channel_id': qc.id}, order_by='match_id', limit=limit) or []
	if not matches:
		return []
	players = await db.select(['match_id', 'user_id', 'nick', 'team'], 'qc_player_matches', where={'channel_id': qc.id}) or []
	ids = {m['match_id'] for m in matches}
	by_match = {}
	for p in players:
		if p['match_id'] in ids:
			by_match.setdefault(p['match_id'], []).append(p)
	for m in matches:
		m['players'] = by_match.get(m['match_id'], [])
	return matches


def _ts(value):
	return datetime.fromtimestamp(value, timezone.utc).strftime("%Y-%m-%d %H:%M:%S") if value else ""


async def api_leaderboard(request):
	qc, guild, acc = get_qc(request, "stats")
	rows = await _players(qc)
	ranks = sorted(qc._ranks_table, key=lambda r: r['rating'], reverse=True)

	def rank(rating):
		return next((r['rank'] for r in ranks if rating is not None and rating >= r['rating']), None)

	return web.json_response(dict(
		rating_system=qc.cfg.rating_system,
		players=[dict(
			user_id=str(r['user_id']), nick=r['nick'], hidden=bool(r['is_hidden']), rating=r['rating'],
			deviation=r['deviation'], wins=r['wins'], losses=r['losses'], draws=r['draws'], streak=r['streak'],
			last_match=r['last_ranked_match_at'], rank=rank(r['rating']),
		) for r in rows],
	))


async def api_matches(request):
	qc, guild, acc = get_qc(request, "stats")
	try:
		limit = max(1, min(500, int(request.query.get("limit", 50))))
	except ValueError:
		limit = 50
	matches = await _matches(qc, limit=limit)
	return web.json_response(dict(matches=[dict(
		id=m['match_id'], queue=m['queue_name'], at=m['at'], ranked=bool(m['ranked']),
		winner=m['winner'], alpha=m['alpha_name'], beta=m['beta_name'],
		alpha_score=m['alpha_score'], beta_score=m['beta_score'], maps=m['maps'],
		players=[dict(user_id=str(p['user_id']), nick=p['nick'], team=p['team']) for p in m['players']],
	) for m in matches]))


async def api_stats_csv(request):
	qc, guild, acc = get_qc(request, "stats")
	kind = request.match_info["kind"]
	out = io.StringIO()
	w = csv.writer(out)
	if kind == "players":
		w.writerow(['user_id', 'nick', 'rating', 'deviation', 'wins', 'losses', 'draws', 'streak', 'hidden', 'last_ranked_match'])
		for r in await _players(qc):
			w.writerow([r['user_id'], r['nick'], r['rating'], r['deviation'], r['wins'], r['losses'], r['draws'],
						r['streak'], int(bool(r['is_hidden'])), _ts(r['last_ranked_match_at'])])
	elif kind == "matches":
		w.writerow(['match_id', 'at', 'queue', 'ranked', 'winner', 'alpha_name', 'beta_name', 'alpha_score',
					'beta_score', 'maps', 'alpha_players', 'beta_players', 'other_players'])
		for m in await _matches(qc):
			teams = {0: [], 1: [], None: []}
			for p in m['players']:
				teams.get(p['team'], teams[None]).append(p['nick'] or str(p['user_id']))
			winner = {0: m['alpha_name'], 1: m['beta_name']}.get(m['winner'], 'draw' if m['ranked'] else '')
			w.writerow([m['match_id'], _ts(m['at']), m['queue_name'], int(bool(m['ranked'])), winner, m['alpha_name'],
						m['beta_name'], m['alpha_score'], m['beta_score'], m['maps'], " ".join(teams[0]),
						" ".join(teams[1]), " ".join(teams[None])])
	else:
		return jerror(404, "Unknown export.")
	name = (guild.get_channel(qc.id).name if guild.get_channel(qc.id) else str(qc.id))
	safe = "".join(c for c in name if c.isalnum() or c in "-_") or str(qc.id)
	return web.Response(
		body=("﻿" + out.getvalue()).encode("utf-8"), content_type="text/csv", charset="utf-8",
		headers={"Content-Disposition": f'attachment; filename="{safe}-{kind}.csv"'}
	)


# ------------------------------------------------------------------ api: queues

async def api_queue(request):
	q, qc, guild, acc = get_queue(request)
	return web.json_response(dict(queue_dict(q), channel=str(qc.id), values=schema.ui_values(q.cfg)))


async def api_queue_save(request):
	q, qc, guild, acc = get_queue(request, "edit_queue")
	body = await read_json(request)
	values = body.get("values", {})
	if isinstance(values, dict) and "name" in values:
		new = str(values["name"] or "").strip()
		if new.lower() != q.name.lower() and new.lower() in (i.name.lower() for i in qc.queues):
			return jerror(400, "Some fields are invalid.", fields=dict(name="A queue with this name already exists."))
	try:
		await schema.apply(q.cfg, values, guild)
	except schema.ConfigError as e:
		return jerror(400, "Some fields are invalid.", fields=e.errors)
	log.info(f"WEBUI| {request['user']['name']} updated queue {q.name} config: {', '.join(values)}.")
	return web.json_response(dict(queue_dict(q), values=schema.ui_values(q.cfg)))


async def api_queue_reset(request):
	q, qc, guild, acc = get_queue(request, "edit_queue")
	name = request.match_info["var"]
	if (v := q.cfg_factory.variables.get(name)) is None:
		return jerror(404, "Unknown variable.")
	if name == "name":
		return jerror(400, "The queue name has no default.")
	try:
		await schema.apply(q.cfg, {name: schema.default_input(v)}, guild)
	except schema.ConfigError as e:
		return jerror(400, "Could not reset the field.", fields=e.errors)
	return web.json_response(dict(values=schema.ui_values(q.cfg)))


async def api_queue_export(request):
	q, qc, guild, acc = get_queue(request)
	return web.json_response(schema.export_values(q.cfg))


async def api_queue_delete(request):
	q, qc, guild, acc = get_queue(request, "manage_queues")
	await q.reset()
	await q.cfg.delete()
	qc.queues.remove(q)
	await bot.connectors.forget_queue(q.id)
	log.info(f"WEBUI| {request['user']['name']} deleted queue {q.name} on {guild.name}.")
	return web.json_response(dict(ok=True))


async def api_queue_clear(request):
	""" Remove everybody from the queue (same as !reset <queue>). """
	q, qc, guild, acc = get_queue(request, "clear_queues")
	await q.reset()
	return web.json_response(dict(ok=True))


# ------------------------------------------------------------------ app

def make_app():
	app = web.Application(middlewares=[middleware], client_max_size=2 * 1024 * 1024)
	r = app.router
	r.add_get("/", index)
	r.add_get("/g/{tail:.*}", index)
	r.add_get("/status", index)
	r.add_get("/healthz", healthz)
	r.add_get("/auth/login", auth.login)
	r.add_get("/auth/callback", auth.callback)
	r.add_get("/verify", verify.page)
	r.add_get("/verify/steam", verify.start)
	r.add_get("/verify/steam/callback", verify.callback)

	r.add_get("/api/me", api_me)
	r.add_post("/api/logout", api_logout)
	r.add_get("/api/schema", api_schema)
	r.add_get("/api/status", api_status)
	r.add_get("/settings", index)
	r.add_get("/api/settings", api_settings)
	r.add_put("/api/settings", api_settings_save)
	r.add_post("/api/settings/steam/test", api_settings_steam_test)
	r.add_get("/api/settings/backup", api_backup)
	r.add_post("/api/settings/restore", api_restore)
	r.add_get("/api/steam/links", api_steam_links)
	r.add_post("/api/steam/links/{user_id}/approve", api_steam_approve)
	r.add_post("/api/steam/links/{user_id}/reject", api_steam_reject)
	r.add_delete("/api/steam/links/{user_id}", api_steam_unlink)
	r.add_get("/api/guilds", api_guilds)
	r.add_get("/api/guilds/{guild_id}", api_guild)
	r.add_get("/api/guilds/{guild_id}/overview", api_guild_overview)
	r.add_post("/api/guilds/{guild_id}/channels", api_add_channel)
	r.add_get("/users", index)
	r.add_get("/users/{tail:.*}", index)
	r.add_get("/api/guilds/{guild_id}/access", api_access)
	r.add_get("/api/guilds/{guild_id}/access/members", api_access_members)
	r.add_post("/api/guilds/{guild_id}/access", api_access_create)
	r.add_put("/api/guilds/{guild_id}/access/{grant_id}", api_access_update)
	r.add_delete("/api/guilds/{guild_id}/access/{grant_id}", api_access_delete)

	r.add_get("/api/channels/{channel_id}", api_channel)
	r.add_put("/api/channels/{channel_id}", api_channel_save)
	r.add_delete("/api/channels/{channel_id}", api_channel_delete)
	r.add_post("/api/channels/{channel_id}/reset/{var}", api_channel_reset)
	r.add_get("/api/channels/{channel_id}/export", api_channel_export)
	r.add_post("/api/channels/{channel_id}/queues", api_create_queue)
	r.add_get("/api/channels/{channel_id}/live", api_channel_live)
	r.add_post("/api/channels/{channel_id}/panel", api_panel_post)
	r.add_delete("/api/channels/{channel_id}/panel", api_panel_delete)
	r.add_post("/api/channels/{channel_id}/pause", api_pause)
	r.add_get("/api/channels/{channel_id}/leaderboard", api_leaderboard)
	r.add_get("/api/channels/{channel_id}/matches", api_matches)
	r.add_get("/api/channels/{channel_id}/stats/{kind}.csv", api_stats_csv)

	r.add_get("/api/channels/{channel_id}/queues/{queue_id}", api_queue)
	r.add_put("/api/channels/{channel_id}/queues/{queue_id}", api_queue_save)
	r.add_delete("/api/channels/{channel_id}/queues/{queue_id}", api_queue_delete)
	r.add_post("/api/channels/{channel_id}/queues/{queue_id}/reset/{var}", api_queue_reset)
	r.add_post("/api/channels/{channel_id}/queues/{queue_id}/clear", api_queue_clear)
	r.add_get("/api/channels/{channel_id}/queues/{queue_id}/export", api_queue_export)

	r.add_get("/connectors", index)
	r.add_get("/connectors/{tail:.*}", index)
	r.add_get("/api/guilds/{guild_id}/connectors", api_connectors)
	r.add_post("/api/guilds/{guild_id}/connectors", api_connector_create)
	r.add_put("/api/guilds/{guild_id}/connectors/{connector_id}", api_connector_update)
	r.add_delete("/api/guilds/{guild_id}/connectors/{connector_id}", api_connector_delete)
	r.add_post("/api/guilds/{guild_id}/connectors/{connector_id}/rotate", api_connector_rotate)
	r.add_post("/api/guilds/{guild_id}/connectors/{connector_id}/toggle", api_connector_toggle)
	r.add_post("/api/guilds/{guild_id}/connectors/{connector_id}/test", api_connector_test)
	r.add_get(CONNECT + "/status", connect_api(connect_status))
	r.add_post(CONNECT + "/results", connect_api(connect_results, "can_results"))
	r.add_post(CONNECT + "/players/linked", connect_api(connect_linked, "can_check"))
	r.add_post(CONNECT + "/link", connect_api(connect_link, "can_link"))
	r.add_get(CONNECT + "/steam/links", connect_api(connect_steam_links, "can_export"))
	r.add_get("/downloads/minqlx/{name}", download_plugin)

	r.add_static("/static", STATIC, append_version=False)
	return app


async def start():
	global runner
	runner = web.AppRunner(make_app(), access_log=None)
	await runner.setup()
	site = web.TCPSite(runner, cfg.WS_HOST, cfg.WS_PORT)
	await site.start()
	log.info(f"Web interface listening on {cfg.WS_HOST}:{cfg.WS_PORT}" + (f" ({cfg.WS_ROOT_URL})" if cfg.WS_ROOT_URL else ""))


async def stop():
	if runner:
		await runner.cleanup()
