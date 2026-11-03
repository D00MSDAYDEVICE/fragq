# -*- coding: utf-8 -*-
"""
Steam account links: Discord user -> SteamID64, with the Steam profile name and avatar.

When "Require linked Steam IDs" is on (web Settings page), players without a link are asked for
their Steam ID when they try to join: a Discord pop-up form for buttons and /add, or a message with
a Link Steam button for !add / ++. Players can also link it any time with !steam / /steam.

The first link is immediate. Changing an existing link to another Steam account is a request that a
moderator or admin approves (or rejects) on the web Settings page; the old link stays until then.

Profile names, avatars and custom profile names (steamcommunity.com/id/...) come from the Steam Web API
when a key is set on the Settings page, and from the public Steam Community profile pages otherwise
(slower and rate limited, so background refreshes are smaller). Links are stored in the database, so
they survive updates and restarts.
"""
import asyncio
import re
import time
from xml.etree import ElementTree

import aiohttp
from nextcord import Embed, Colour, ButtonStyle
from nextcord.ui import View, Button, Modal, TextInput

from core.client import dc
from core.console import log
from core.database import db
from core.utils import get_nick, error_embed, ok_embed

import bot
from bot import settings

db.ensure_table(dict(
	tname="fragq_steam_links",
	columns=[
		dict(cname="user_id", ctype=db.types.int),
		dict(cname="steam_id", ctype=db.types.str),
		dict(cname="nick", ctype=db.types.str),
		dict(cname="persona", ctype=db.types.str),
		dict(cname="avatar_url", ctype=db.types.str),
		dict(cname="profile_url", ctype=db.types.str),
		dict(cname="linked_at", ctype=db.types.int),
		dict(cname="updated_at", ctype=db.types.int),
	],
	primary_keys=["user_id"]
))

db.ensure_table(dict(
	tname="fragq_steam_requests",  # pending changes of an existing link, one per player
	columns=[
		dict(cname="user_id", ctype=db.types.int),
		dict(cname="steam_id", ctype=db.types.str),
		dict(cname="nick", ctype=db.types.str),
		dict(cname="persona", ctype=db.types.str),
		dict(cname="avatar_url", ctype=db.types.str),
		dict(cname="profile_url", ctype=db.types.str),
		dict(cname="requested_at", ctype=db.types.int),
	],
	primary_keys=["user_id"]
))

API = "https://api.steampowered.com"
ID64_BASE = 76561197960265728
PREFIX = "fragq:"
REFRESH_AFTER = 3 * 86400   # re-read Steam names / avatars this often
RETRY_MISSING = 3600        # links without an avatar yet (Steam was unreachable) are retried sooner
REFRESH_EVERY = 1800
KEYLESS_BATCH = 10          # profile pages read per refresh without an API key

links = {}     # user_id -> row
requests = {}  # user_id -> pending change (same columns as a link, plus requested_at)
_next_refresh = 0
_refreshing = False


async def load():
	links.clear()
	for row in await db.select(["*"], "fragq_steam_links"):
		links[row["user_id"]] = row
	requests.clear()
	for row in await db.select(["*"], "fragq_steam_requests"):
		requests[row["user_id"]] = row


def api_key():
	return settings.get("steam_api_key") or ""


def required():
	return bool(settings.get("require_steam_link"))


def get_link(user_id):
	return links.get(user_id)


# ------------------------------------------------------------------ Steam ids and the Web API

def parse(text):
	""" Returns (steam_id64, vanity_name); either can be None. """
	s = (text or "").strip().strip("<>")
	if m := re.fullmatch(r"(?:https?://)?(?:www\.)?steamcommunity\.com/profiles/(\d{17})(?:/.*)?", s, re.I):
		return m.group(1), None
	if m := re.fullmatch(r"(?:https?://)?(?:www\.)?steamcommunity\.com/id/([\w-]{2,32})(?:/.*)?", s, re.I):
		return None, m.group(1)
	if re.fullmatch(r"7656\d{13}", s):
		return s, None
	if m := re.fullmatch(r"STEAM_[0-5]:([01]):(\d{1,10})", s, re.I):
		return str(ID64_BASE + int(m.group(2)) * 2 + int(m.group(1))), None
	if m := re.fullmatch(r"\[?U:1:(\d{1,10})]?", s, re.I):
		return str(ID64_BASE + int(m.group(1))), None
	if re.fullmatch(r"[\w-]{2,32}", s):
		return None, s
	return None, None


async def _call(method, key, **params):
	try:
		async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=8)) as session:
			async with session.get(f"{API}/{method}", params=dict(params, key=key)) as resp:
				if resp.status in (401, 403):
					raise bot.Exc.ValueError("Steam rejected the Steam API key.")
				if resp.status != 200:
					raise bot.Exc.ValueError(f"The Steam API returned HTTP {resp.status}, try again later.")
				return await resp.json(content_type=None)
	except (aiohttp.ClientError, asyncio.TimeoutError):
		raise bot.Exc.ValueError("Couldn't reach the Steam API, try again later.")


async def resolve_vanity(name, key=None):
	data = await _call("ISteamUser/ResolveVanityURL/v1/", key or api_key(), vanityurl=name)
	resp = data.get("response") or {}
	return resp.get("steamid") if resp.get("success") == 1 else None


async def summaries(steam_ids, key=None):
	""" {steam_id: player} from GetPlayerSummaries. Empty without an API key. """
	key = key or api_key()
	out = {}
	if not key:
		return out
	ids = list(dict.fromkeys(steam_ids))
	for i in range(0, len(ids), 100):
		data = await _call("ISteamUser/GetPlayerSummaries/v2/", key, steamids=",".join(ids[i:i + 100]))
		for p in (data.get("response") or {}).get("players", []):
			out[p["steamid"]] = p
	return out


async def community_profile(steam_id=None, vanity=None):
	"""
	Public Steam Community profile, no API key needed. Returns a dict shaped like a GetPlayerSummaries
	player, or None if there is no such profile.
	"""
	url = f"https://steamcommunity.com/profiles/{steam_id}/" if steam_id else f"https://steamcommunity.com/id/{vanity}/"
	try:
		async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=8)) as session:
			async with session.get(url, params=dict(xml="1")) as resp:
				if resp.status != 200:
					raise bot.Exc.ValueError(f"Steam returned HTTP {resp.status}, try again later.")
				text = (await resp.text())[:200_000]
	except (aiohttp.ClientError, asyncio.TimeoutError):
		raise bot.Exc.ValueError("Couldn't reach Steam, try again later.")
	try:
		root = ElementTree.fromstring(text)
	except ElementTree.ParseError:
		raise bot.Exc.ValueError("Steam returned an unexpected response, try again later.")
	sid = (root.findtext("steamID64") or "").strip()
	if root.tag != "profile" or not re.fullmatch(r"\d{17}", sid):
		return None
	return dict(
		steamid=sid,
		personaname=(root.findtext("steamID") or "").strip() or None,
		avatarmedium=(root.findtext("avatarMedium") or "").strip() or None,
		profileurl=profile_url(sid),
	)


async def test_key(key):
	""" Raises bot.Exc.ValueError if the key doesn't work. """
	players = await summaries(["76561197960287930"], key=key)  # a long-lived public profile
	if not players:
		raise bot.Exc.ValueError("The key was accepted, but Steam returned no profile data.")


# ------------------------------------------------------------------ links

def profile_url(steam_id):
	return f"https://steamcommunity.com/profiles/{steam_id}"


def _taken(steam_id, user_id):
	return any(r["steam_id"] == steam_id and r["user_id"] != user_id for r in links.values())


async def lookup(user, text):
	""" Resolve what a player typed to a Steam account; returns a link row (not stored yet). """
	steam_id, vanity = parse(text)
	key = api_key()
	player = None
	if vanity and not steam_id:
		if key:
			steam_id = await resolve_vanity(vanity, key)
		elif player := await community_profile(vanity=vanity):
			steam_id = player["steamid"]
		if not steam_id:
			raise bot.Exc.ValueError(f"No Steam profile named `{vanity}` was found.")
	if not steam_id:
		raise bot.Exc.ValueError("That doesn't look like a Steam ID. Paste your SteamID64 or your Steam profile link.")

	if _taken(steam_id, user.id):
		raise bot.Exc.ValueError(
			"This Steam account is already linked to another Discord member. Ask a server admin if this is a mistake."
		)

	if player is None:
		if key:
			player = (await summaries([steam_id], key)).get(steam_id)
		else:
			try:
				player = await community_profile(steam_id=steam_id)
			except bot.Exc.ValueError:  # Steam unreachable: link now, the name and picture are fetched later
				player = {}
		if player is None:
			raise bot.Exc.ValueError("Steam profile not found. Check the ID or link.")

	now = int(time.time())
	old = links.get(user.id)
	same = old if old and old["steam_id"] == steam_id else {}
	return dict(
		user_id=user.id,
		steam_id=steam_id,
		nick=get_nick(user)[:191],
		persona=player.get("personaname") if player else same.get("persona"),
		avatar_url=player.get("avatarmedium") if player else same.get("avatar_url"),
		profile_url=(player or {}).get("profileurl") or profile_url(steam_id),
		linked_at=same.get("linked_at") or now,
		updated_at=now,
	)


async def _store(row):
	await db.insert("fragq_steam_links", row, on_dublicate="replace")
	links[row["user_id"]] = row


async def link(user, text):
	"""
	Link a Discord user to a Steam account. Returns (status, row):
	  "linked"    - first link, or the same account again (refreshes the name and picture);
	  "pending"   - a change to another account, waiting for a moderator's approval;
	  "cancelled" - the player's current account again while a change was pending: the request is dropped.
	"""
	row = await lookup(user, text)
	old = links.get(user.id)
	if old and old["steam_id"] != row["steam_id"]:
		req = {k: row[k] for k in ("user_id", "steam_id", "nick", "persona", "avatar_url", "profile_url")}
		req["requested_at"] = int(time.time())
		await db.insert("fragq_steam_requests", req, on_dublicate="replace")
		requests[user.id] = req
		log.info(f"{get_nick(user)} ({user.id}) asked to change their Steam account {old['steam_id']} -> {row['steam_id']}.")
		return "pending", req
	await _store(row)
	if requests.pop(user.id, None):
		await db.delete("fragq_steam_requests", where=dict(user_id=user.id))
		log.info(f"{get_nick(user)} ({user.id}) cancelled their Steam account change.")
		return "cancelled", row
	log.info(f"{get_nick(user)} ({user.id}) linked Steam account {row['steam_id']}.")
	return "linked", row


async def approve(user_id):
	""" Apply a pending change. Returns the new link row; raises ValueError if it can't be applied. """
	req = requests.get(user_id)
	if req is None:
		raise bot.Exc.ValueError("This player has no pending Steam account change.")
	if _taken(req["steam_id"], user_id):
		raise bot.Exc.ValueError(
			"That Steam account is now linked to another Discord member. Reject the request, or unlink the other member first."
		)
	now = int(time.time())
	row = {k: req[k] for k in ("user_id", "steam_id", "nick", "persona", "avatar_url", "profile_url")}
	row.update(linked_at=now, updated_at=now)
	await _store(row)
	await reject(user_id)
	return row


async def reject(user_id):
	await db.delete("fragq_steam_requests", where=dict(user_id=user_id))
	return requests.pop(user_id, None)


async def unlink(user_id):
	await db.delete("fragq_steam_links", where=dict(user_id=user_id))
	await reject(user_id)
	return links.pop(user_id, None)


async def restore(rows):
	""" Links from a Settings page backup. Returns (added, skipped): accounts linked to someone else here are skipped. """
	added = skipped = 0
	for r in rows:
		try:
			uid, sid = int(r["user_id"]), str(r["steam_id"])
		except (KeyError, TypeError, ValueError):
			skipped += 1
			continue
		if not re.fullmatch(r"\d{17}", sid) or _taken(sid, uid):
			skipped += 1
			continue
		now = int(time.time())
		await _store(dict(
			user_id=uid, steam_id=sid, nick=str(r.get("nick") or "")[:191] or None,
			persona=r.get("persona"), avatar_url=r.get("avatar_url"), profile_url=r.get("profile_url") or profile_url(sid),
			linked_at=int(r.get("linked_at") or now), updated_at=0,  # 0: re-read the name and picture soon
		))
		added += 1
	return added, skipped


async def notify(user_id, text):
	""" Best-effort direct message to a player. """
	user = dc.get_user(user_id)
	if user is None:
		return
	try:
		await user.send(text)
	except Exception:
		pass


def result_text(status, row, gt=lambda text: text):
	""" The reply to a link attempt; `gt` translates (QueueChannel.gt). """
	if status == "pending":
		old = links.get(row["user_id"])
		return gt("Your change to Steam {steam} is waiting for a moderator's approval. Until then you stay linked to {old}.").format(
			steam=describe(row), old=describe(old) if old else "—")
	if status == "cancelled":
		return gt("Your Steam account change was cancelled. You stay linked to {steam}.").format(steam=describe(row))
	return gt("Linked to Steam {steam}.").format(steam=describe(row))


def describe(row):
	name = row.get("persona") or row["steam_id"]
	return f"[{name}]({row.get('profile_url') or profile_url(row['steam_id'])}) (`{row['steam_id']}`)"


async def _refresh_stale():
	""" Re-read names and avatars of links older than REFRESH_AFTER (or still missing an avatar). """
	global _refreshing
	_refreshing = True
	try:
		now = int(time.time())
		stale = [
			r for r in links.values()
			if (r.get("updated_at") or 0) < now - REFRESH_AFTER
			or (not r.get("avatar_url") and (r.get("updated_at") or 0) < now - RETRY_MISSING)
		]
		if not stale:
			return
		if api_key():
			stale = stale[:100]
			players = await summaries([r["steam_id"] for r in stale])
		else:  # one profile page per player, gently
			stale, players = stale[:KEYLESS_BATCH], {}
			for r in stale:
				if p := await community_profile(steam_id=r["steam_id"]):
					players[r["steam_id"]] = p
				await asyncio.sleep(1)
		now = int(time.time())
		for r in stale:
			p = players.get(r["steam_id"])
			if p:
				r.update(persona=p.get("personaname"), avatar_url=p.get("avatarmedium"), profile_url=p.get("profileurl") or r["profile_url"])
			r["updated_at"] = now
			await db.update("fragq_steam_links", dict(
				persona=r["persona"], avatar_url=r["avatar_url"], profile_url=r["profile_url"], updated_at=now
			), keys=dict(user_id=r["user_id"]))
	except Exception as e:
		log.error(f"Steam profile refresh failed: {e}")
	finally:
		_refreshing = False


# ------------------------------------------------------------------ Discord prompt

def link_modal(queues=None):
	""" Pop-up form asking for the Steam ID. `queues` is what the player tried to join. """
	# Answered by panel.on_interaction (custom_id routing); auto_defer would race it.
	modal = Modal("Link your Steam account", custom_id=f"{PREFIX}steam_link:{(queues or '')[:60]}", timeout=600, auto_defer=False)
	modal.add_item(TextInput(
		"SteamID64 or Steam profile link", custom_id="steam", min_length=2, max_length=200, required=True,
		placeholder="76561198000000000 or steamcommunity.com/id/yourname",
	))
	return modal


def prompt_view(queues=None):
	view = View(timeout=None, auto_defer=False)
	view.add_item(Button(
		style=ButtonStyle.primary, label="Link Steam", emoji="🔗", custom_id=f"{PREFIX}steam_prompt:{(queues or '')[:60]}"
	))
	return view


async def prompt(ctx, queues=None):
	""" Ask a player who tried to join for their Steam ID. """
	inter = getattr(ctx, "interaction", None)
	if inter is not None and not inter.response.is_done():
		await inter.response.send_modal(link_modal(queues))
		return
	embed = Embed(
		colour=Colour(0x66c0f4),
		title="🔗 " + ctx.qc.gt("Link your Steam account"),
		description=ctx.qc.gt(
			"You need a linked Steam account to join queues here. Press **Link Steam** and paste your "
			"SteamID64 or Steam profile link, or type `{cmd} <id or link>`."
		).format(cmd=f"{ctx.qc.cfg.prefix}steam"),
	)
	if inter is not None:
		await inter.followup.send(embed=embed, view=prompt_view(queues), ephemeral=True)
	else:
		await ctx.channel.send(content=ctx.author.mention, embed=embed, view=prompt_view(queues), delete_after=300)


def _modal_value(data, custom_id):
	for row in data.get("components") or []:
		for c in row.get("components") or []:
			if c.get("custom_id") == custom_id:
				return c.get("value") or ""
	return ""


async def on_modal(interaction):
	"""
	Steam ID form submitted. Links the account and returns (True, queues) so the caller can finish
	the join the player started, or (False, None) after showing the error.
	"""
	queues = interaction.data["custom_id"][len(f"{PREFIX}steam_link:"):] or None
	# with_message: a plain defer() would mean "update the message", and forms opened by /add have none.
	await interaction.response.defer(ephemeral=True, with_message=True)
	try:
		status, row = await link(interaction.user, _modal_value(interaction.data, "steam"))
	except bot.Exc.PubobotException as e:
		await interaction.followup.send(embed=error_embed(str(e), title="Steam link failed"), view=prompt_view(queues), ephemeral=True)
		return False, None
	await interaction.followup.send(embed=ok_embed(result_text(status, row), title=None), ephemeral=True)
	return True, queues


@dc.event
async def on_init():
	await load()


@dc.event
async def on_think(frame_time):
	global _next_refresh
	if frame_time > _next_refresh and not _refreshing and links:
		_next_refresh = frame_time + REFRESH_EVERY
		asyncio.create_task(_refresh_stale())
