# -*- coding: utf-8 -*-
"""
Fragdex lookups: find the Discord member of a SteamID that FragQ has no link for, by asking a Fragdex
server (its API, POST /players/lookup) with an API key of its own. Set up on the web Settings page.

A convenience only, and off until the bot owner turns it on after a successful connection test:
- FragQ's own links always come first; Fragdex is only asked about SteamIDs nobody linked in FragQ.
- What Fragdex says is never stored as a FragQ link and never counts as verified. It is kept in memory
  for a while (CACHE_TTL) so game servers don't wait on Fragdex for every request.
- It is used where a game server sends SteamIDs: the names on posted results, the linked-player check and
  voice moves. It never decides which FragQ match a result belongs to, and never touches ratings.
- An answer counts only if it is a numeric Discord ID of a member of the server the request is for.
"""
import asyncio
import hashlib
import re
import time

import aiohttp

from core.console import log

import bot

TIMEOUT = 3             # seconds a game server request may wait on Fragdex
TEST_TIMEOUT = 10
CHUNK = 100             # Fragdex answers up to 100 SteamIDs per lookup
CACHE_TTL = 600         # a SteamID Fragdex knows is asked again after this long
MISS_TTL = 300          # one it doesn't know (or has no Discord ID for)
CACHE_MAX = 5000
ID_RE = re.compile(r"^\d{15,21}$")

_cache = {}             # steam_id -> (discord_id or None, at)
last_error = None       # (message, at) of the last failed lookup, shown on the Settings page
_found = set()          # SteamIDs Fragdex found a member for since the start


class FragdexError(Exception):
	pass


def api_base(url):
	""" The API address from what the owner typed: the site, or its API base URL (…/api/v1). """
	url = (url or "").strip().rstrip("/")
	return url if url.endswith("/api/v1") else url + "/api/v1"


def _sig(url, key):
	""" Which address and key a successful test was for, without storing the key twice. """
	return hashlib.sha256(f"{api_base(url)}\n{key}".encode()).hexdigest()[:16]


def url():
	return bot.settings.get("fragdex_url") or ""


def key():
	return bot.settings.get("fragdex_key") or ""


def connected():
	""" The saved address and key passed a test, and haven't changed since. """
	ok = bot.settings.get("fragdex_ok") or {}
	return bool(url() and key() and ok.get("sig") == _sig(url(), key()))


def enabled():
	return bool(bot.settings.get("fragdex_lookup")) and connected()


async def _request(base, api_key, method, path, body=None, timeout=TIMEOUT):
	try:
		async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=timeout)) as session:
			async with session.request(method, base + path, json=body, headers={
				"Authorization": "Bearer " + api_key, "Accept": "application/json", "User-Agent": "FragQ",
			}) as resp:
				try:
					data = await resp.json(content_type=None)
				except ValueError:
					data = None
				if resp.status != 200:
					msg = data.get("error") if isinstance(data, dict) and data.get("error") else f"HTTP {resp.status}"
					if resp.status == 401:
						msg = "Fragdex refused the API key."
					elif resp.status == 404 and not isinstance(data, dict):
						msg = "No Fragdex API at this address (HTTP 404). Use the Base URL from Fragdex's Settings → Fragdex API."
					raise FragdexError(msg)
				if not isinstance(data, dict):
					raise FragdexError("The answer isn't from a Fragdex API. Check the address.")
				return data
	except aiohttp.InvalidURL:
		raise FragdexError("That isn't a valid address.")
	except asyncio.TimeoutError:
		raise FragdexError("Fragdex didn't answer in time.")
	except aiohttp.ClientError as e:
		raise FragdexError(f"Couldn't reach Fragdex: {e.__class__.__name__}.")


async def test(address, api_key):
	""" GET /status with these settings. Returns dict(version, players, key_name); raises FragdexError. """
	if not re.match(r"^https?://[^\s/]+", address or ""):
		raise FragdexError("Enter the address, starting with https:// (or http://).")
	if not api_key:
		raise FragdexError("Enter the API key.")
	data = await _request(api_base(address), api_key, "GET", "/status", timeout=TEST_TIMEOUT)
	if data.get("app") != "fragdex":
		raise FragdexError("The answer isn't from a Fragdex server. Check the address.")
	return dict(version=str(data.get("version") or "?"), players=data.get("players"),
				key_name=(data.get("key") or {}).get("name"))


async def record_test(address, api_key, info):
	""" Remember that these settings passed a test. """
	await bot.settings.put("fragdex_ok", dict(sig=_sig(address, api_key), at=int(time.time()), **info))


def _remember(steam_id, discord_id, now):
	if len(_cache) >= CACHE_MAX:
		for sid in sorted(_cache, key=lambda s: _cache[s][1])[:CACHE_MAX // 5]:
			del _cache[sid]
	_cache[steam_id] = (discord_id, now)


def forget():
	""" Settings changed: ask again. """
	_cache.clear()


async def owners(steam_ids, guild):
	"""
	{steam_id: discord user id} for the SteamIDs nobody linked in FragQ that Fragdex has a Discord member
	of `guild` for. Empty when lookups are off, Fragdex can't be reached, or there's no guild.
	"""
	global last_error
	if not enabled() or guild is None:
		return {}
	known = {r["steam_id"] for r in bot.steam.links.values()}
	wanted = list(dict.fromkeys(str(s) for s in steam_ids if str(s) not in known))
	now = time.time()
	ask = [s for s in wanted if s not in _cache or now - _cache[s][1] > (CACHE_TTL if _cache[s][0] else MISS_TTL)]
	for i in range(0, len(ask), CHUNK):
		chunk = ask[i:i + CHUNK]
		try:
			data = await _request(api_base(url()), key(), "POST", "/players/lookup", dict(steam_ids=chunk))
		except FragdexError as e:
			if not last_error or now - last_error[1] > 300:
				log.error(f"Fragdex lookup failed: {e}")
			last_error = (str(e), int(now))
			break
		answers = {str(p.get("steam_id")): p for p in data.get("players") or [] if isinstance(p, dict)}
		for sid in chunk:
			p = answers.get(sid) or {}
			did = str(p.get("discord_id") or "") if p.get("known") else ""
			_remember(sid, did if ID_RE.match(did) else None, now)
		last_error = None
	out = {}
	for sid in wanted:
		did = (_cache.get(sid) or (None, 0))[0]
		if did and guild.get_member(int(did)) is not None:
			out[sid] = int(did)
	_found.update(out)
	return out


def status():
	ok = bot.settings.get("fragdex_ok") or {}
	return dict(
		url=url(),
		key_set=bool(key()),
		key_hint=key()[-4:] if key() else None,   # the key itself never leaves the server
		connected=connected(),
		tested_at=ok.get("at") if connected() else None,
		version=ok.get("version") if connected() else None,
		key_name=ok.get("key_name") if connected() else None,
		lookup=bool(bot.settings.get("fragdex_lookup")),
		active=enabled(),
		found=len(_found),
		last_error=dict(message=last_error[0], at=last_error[1]) if last_error and enabled() else None,
	)
