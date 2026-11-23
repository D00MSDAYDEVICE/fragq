# -*- coding: utf-8 -*-
"""
Slipgate (slipgate.gg, Quake Live ratings): the only part of FragQ that talks to the Slipgate API. Set up on the
web Settings page with the bot owner's Slipgate API key (sg_...), and off until that key passed a test.

What uses it:
- team balancing: a queue with Pick teams "matchmaking", a Slipgate game type and "Balance teams with Slipgate"
  on gets its teams from POST /balance when a match starts (balance_match, used by bot.match.Match.new);
- starting ratings: with the channel's "Start new players at their Slipgate rating" on, a ranked match gives
  players who have no FragQ rating yet one from their place on the Slipgate ladder (seed_ratings);
- !slipgate / /slipgate: a player's Slipgate ratings (player_ratings, a public endpoint that works without a key);
- results: a Quake Live connector with "Add Slipgate details to results" on gets a link to the Slipgate match, its
  highlights and its demos added to each posted result (watch_result, at the end of this file).

Everything goes by the Steam accounts players linked in FragQ (bot.steam). A match start never waits long on
Slipgate (TIMEOUT): when Slipgate is slow, refuses, or rate limits, FragQ uses its own ratings and logs why.
After a 429, Slipgate is left alone for exactly the Retry-After seconds it asked for.
"""
import asyncio
import hashlib
import json
import os
import re
import time
from statistics import NormalDist

import aiohttp
from nextcord import DiscordException, NotFound

from core.client import dc
from core.console import log
from core.database import db
from core.utils import get_nick

import bot

API = (os.environ.get("SLIPGATE_URL") or "https://slipgate.gg").rstrip("/") + "/api/v1"
SITE = API[:-len("/api/v1")]
GAME_TYPES = ["ca", "duel", "ctf", "ft", "tdm", "ffa", "ad", "domination", "harvester", "1flag", "redrover"]
GAME_NAMES = {
	"ca": "Clan Arena", "duel": "Duel", "ctf": "Capture the Flag", "ft": "Freeze Tag", "tdm": "Team Deathmatch",
	"ffa": "Free For All", "ad": "Attack and Defend", "domination": "Domination", "harvester": "Harvester",
	"1flag": "One Flag CTF", "redrover": "Red Rover",
}

TIMEOUT = 2.5           # seconds a match start may wait on Slipgate
TEST_TIMEOUT = 10
COMMAND_TIMEOUT = 6
CACHE_TTL = 600         # !slipgate answers are kept this long
CACHE_MAX = 2000
TEST_STEAM_ID = "76561197960287930"   # any valid SteamID64 will do: an unknown one still proves the key works
MIN_LADDER = 20         # starting ratings need a ladder at least this big to mean anything

_cache = {}             # steam_id -> (GET /players/{id}/ratings answer or None, at)
_inflight = {}          # request key -> asyncio.Task, so concurrent asks for the same thing share one call
_paused_until = 0       # after a 429: no calls before this time
last_error = None       # (message, at), shown on the Settings page
_counts = dict(balanced=0, fallback=0, seeded=0)


class SlipgateError(Exception):
	pass


class RateLimited(SlipgateError):
	pass


def _sig(api_key):
	""" Which key passed the last test, without storing it twice. """
	return hashlib.sha256(f"{API}\n{api_key}".encode()).hexdigest()[:16]


def key():
	return bot.settings.get("slipgate_key") or ""


def connected():
	""" A key is saved and passed a test. Every Slipgate feature waits for this. """
	ok = bot.settings.get("slipgate_ok") or {}
	return bool(key() and ok.get("sig") == _sig(key()))


def forget():
	""" The key changed: ask again. """
	global _paused_until, last_error
	_cache.clear()
	_paused_until = 0
	last_error = None


def _note_error(e):
	global last_error
	now = int(time.time())
	if not last_error or last_error[0] != str(e) or now - last_error[1] > 300:
		log.error(f"Slipgate: {e}")
	last_error = (str(e), now)


async def _request(method, path, body=None, timeout=TIMEOUT, api_key=None, params=None, not_found=False):
	"""
	One API call. Returns the JSON object, or None for a 404 when not_found is set.
	Raises RateLimited (and pauses all calls) on a 429, SlipgateError on anything else that went wrong.
	"""
	global _paused_until
	if time.time() < _paused_until:
		raise RateLimited(f"Slipgate asked FragQ to wait, for {int(_paused_until - time.time()) + 1} more seconds.")
	headers = {"Accept": "application/json", "User-Agent": "FragQ"}
	if api_key:
		headers["Authorization"] = "Bearer " + api_key
	try:
		async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=timeout)) as session:
			async with session.request(method, API + path, json=body, params=params, headers=headers) as resp:
				try:
					data = await resp.json(content_type=None)
				except ValueError:
					data = None
				if resp.status == 429:
					try:
						wait = max(1, int(float(resp.headers.get("Retry-After") or 60)))
					except ValueError:
						wait = 60
					_paused_until = time.time() + wait
					raise RateLimited(f"Slipgate's rate limit was reached; FragQ waits {wait} seconds, as Slipgate asked.")
				if resp.status == 404 and not_found:
					return None
				if resp.status in (401, 403):
					raise SlipgateError("Slipgate refused the API key.")
				if resp.status != 200:
					detail = data.get("detail") if isinstance(data, dict) else None
					raise SlipgateError(f"Slipgate answered HTTP {resp.status}" + (f": {detail}" if isinstance(detail, str) else "."))
				if not isinstance(data, dict):
					raise SlipgateError("Slipgate's answer wasn't JSON.")
				return data
	except asyncio.TimeoutError:
		raise SlipgateError("Slipgate didn't answer in time.")
	except aiohttp.ClientError as e:
		raise SlipgateError(f"Couldn't reach Slipgate: {e.__class__.__name__}.")


async def _shared(name, make):
	""" Run make() once for everyone asking for `name` at the same time. """
	task = _inflight.get(name)
	if task is None:
		task = _inflight[name] = asyncio.ensure_future(make())
		task.add_done_callback(lambda _: _inflight.pop(name, None))
	return await asyncio.shield(task)


# ------------------------------------------------------------------ settings

async def test(api_key):
	""" One bulk lookup with this key. Returns dict(rating_set); raises SlipgateError. """
	if not api_key:
		raise SlipgateError("Enter the API key.")
	data = await _request("POST", "/ratings/bulk", dict(steam_ids=[TEST_STEAM_ID], game_type="ca"),
						  timeout=TEST_TIMEOUT, api_key=api_key)
	if not isinstance(data.get("players"), list):
		raise SlipgateError("That answer isn't from the Slipgate API.")
	return dict(rating_set=data.get("rating_set"))


async def record_test(api_key):
	await bot.settings.put("slipgate_ok", dict(sig=_sig(api_key), at=int(time.time())))


def status():
	ok = bot.settings.get("slipgate_ok") or {}
	return dict(
		key_set=bool(key()),
		key_hint=key()[-4:] if key() else None,   # the key itself never leaves the server
		connected=connected(),
		tested_at=ok.get("at") if connected() else None,
		paused_until=int(_paused_until) if _paused_until > time.time() else None,
		last_error=dict(message=last_error[0], at=last_error[1]) if last_error and connected() else None,
		site=SITE,
		**_counts,
	)


# ------------------------------------------------------------------ lookups

def steam_id_of(member):
	row = bot.steam.get_link(member.id)
	return str(row["steam_id"]) if row and row.get("steam_id") else None


def _remember(k, value, at):
	if len(_cache) >= CACHE_MAX:
		for old in sorted(_cache, key=lambda x: _cache[x][1])[:CACHE_MAX // 5]:
			del _cache[old]
	_cache[k] = (value, at)


async def player_ratings(steam_id):
	"""
	GET /players/{id}/ratings (public, works without a key): dict(name, ratings=[...]), or None if Slipgate
	doesn't know the player. Kept CACHE_TTL, so a busy !slipgate doesn't run into Slipgate's rate limit.
	"""
	steam_id = str(steam_id)
	hit = _cache.get(steam_id)
	if hit and time.time() - hit[1] < CACHE_TTL:
		return hit[0]

	async def fetch():
		data = await _request("GET", f"/players/{steam_id}/ratings", timeout=COMMAND_TIMEOUT,
							  api_key=key() if connected() else None, not_found=True)
		_remember(steam_id, data, time.time())
		return data

	return await _shared(("ratings", steam_id), fetch)


RATING_SETS = {"standard": "A", "modified": "B"}   # a queue's Slipgate ladder -> Slipgate's rating_set
_rating_cache = {}      # (steam_id, game type, rating set) -> (bulk item or None, at)


def rating_set(ladder):
	return RATING_SETS.get(ladder or "standard", "A")


async def ladder_rating(steam_id, game_type, ladder="standard"):
	""" One rating with its place on the ladder (include_rank), or None if the player has none in this game type. """
	return await _request("GET", f"/players/{steam_id}/ratings/{game_type}",
						  params=dict(include_rank="true", rating_set=rating_set(ladder)), api_key=key(), not_found=True)


async def player_rating(steam_id, game_type, ladder="standard"):
	"""
	A player's rating in one game type and ladder from POST /ratings/bulk (display, tier_name, provisional, games ...),
	or None if Slipgate doesn't know them there. Kept CACHE_TTL. Raises SlipgateError when Slipgate can't be asked.
	"""
	if not connected():
		raise SlipgateError("Slipgate isn't connected.")
	k = (str(steam_id), game_type, rating_set(ladder))
	hit = _rating_cache.get(k)
	if hit and time.time() - hit[1] < CACHE_TTL:
		return hit[0]

	async def fetch():
		data = await _request("POST", "/ratings/bulk", dict(steam_ids=[k[0]], game_type=game_type, rating_set=k[2]),
							  api_key=key())
		item = next((p for p in data.get("players") or [] if isinstance(p, dict) and str(p.get("steam_id")) == k[0]), None)
		item = item if item and item.get("found") else None
		if len(_rating_cache) >= CACHE_MAX:
			for old in sorted(_rating_cache, key=lambda x: _rating_cache[x][1])[:CACHE_MAX // 5]:
				del _rating_cache[old]
		_rating_cache[k] = (item, time.time())
		return item

	return await _shared(("rating",) + k, fetch)


def profile_url(steam_id):
	return f"{SITE}/players/{steam_id}"


# ------------------------------------------------------------------ rating limits

def limits(q):
	""" (minimum, maximum) Slipgate display rating of a queue, or None when it has no limit (or no game type). """
	lo, hi = q.cfg.slipgate_min_rating, q.cfg.slipgate_max_rating
	if not q.cfg.slipgate_game_type or (lo is None and hi is None):
		return None
	return lo, hi


def limits_text(q):
	""" '1200–1800', '≤1800' or '≥1200' for the queue panel, or None. """
	lim = limits(q)
	if not lim:
		return None
	lo, hi = lim
	return f"{lo}–{hi}" if lo is not None and hi is not None else f"≤{hi}" if hi is not None else f"≥{lo}"


async def check_limits(member, queues, gt):
	"""
	Which of `queues` a member may not join because of their Slipgate rating limits: (refused {queue: reason},
	needs_link [queues that need a linked Steam account first]). When Slipgate can't be asked, nobody is refused.
	"""
	refused, needs_link = {}, []
	limited = [q for q in queues if limits(q)]
	if not limited:
		return refused, needs_link
	steam_id = steam_id_of(member)
	for q in limited:
		lo, hi = limits(q)
		name = GAME_NAMES.get(q.cfg.slipgate_game_type, q.cfg.slipgate_game_type)
		if not steam_id:
			if not q.cfg.slipgate_allow_unrated:
				needs_link.append(q)
			continue
		try:
			r = await player_rating(steam_id, q.cfg.slipgate_game_type, q.cfg.slipgate_ladder)
		except SlipgateError as e:
			_note_error(e)
			log.info(f"Slipgate rating limit of {q.name} not checked for {get_nick(member)}: {e}")
			continue   # let them in rather than lock everyone out while Slipgate is unavailable
		if r is None:
			if not q.cfg.slipgate_allow_unrated:
				refused[q] = gt("**{queue}** needs a Slipgate {game} rating, and you don't have one yet.").format(queue=q.name, game=name)
			continue
		if r.get("provisional"):
			if not q.cfg.slipgate_allow_provisional:
				refused[q] = gt("**{queue}** needs a settled Slipgate {game} rating; yours is still provisional.").format(queue=q.name, game=name)
			continue
		display = r.get("display")
		if display is None:
			continue
		if lo is not None and display < lo:
			refused[q] = gt("Your Slipgate {game} rating ({rating}) is below the minimum for **{queue}** ({limit}).").format(
				game=name, rating=display, queue=q.name, limit=lo)
		elif hi is not None and display > hi:
			refused[q] = gt("Your Slipgate {game} rating ({rating}) is above the maximum for **{queue}** ({limit}).").format(
				game=name, rating=display, queue=q.name, limit=hi)
	return refused, needs_link


# ------------------------------------------------------------------ team balancing

def wants_balance(cfg):
	return bool(cfg.get("slipgate_balance") and cfg.get("slipgate_game_type") and cfg.get("pick_teams") == "matchmaking")


async def balance_match(match):
	"""
	For a match whose queue balances with Slipgate: dict(source="slipgate", teams=[[user ids], [user ids]],
	quality, win=[p0, p1]) to use, or dict(source="fragq", reason=...) when FragQ's own matchmaking has to do.
	None when the queue doesn't use Slipgate.
	"""
	cfg = match.cfg
	if not wants_balance(cfg):
		return None
	result = await _balance(match)
	_counts["balanced" if result["source"] == "slipgate" else "fallback"] += 1
	if result["source"] == "fragq":
		log.info(f"Match #{match.id} ({match.queue.name}): balanced with FragQ ratings, {result['reason']}.")
	return result


async def _balance(match):
	gt = match.qc.gt
	if not connected():
		return dict(source="fragq", reason=gt("Slipgate isn't connected"))
	steam = {p.id: steam_id_of(p) for p in match.players}
	unlinked = [p for p in match.players if not steam[p.id]]
	if unlinked:
		return dict(source="fragq", reason=gt("{n} not linked to Steam").format(
			n=", ".join(get_nick(p) for p in unlinked[:3]) + (f" +{len(unlinked) - 3}" if len(unlinked) > 3 else "")))
	if len(set(steam.values())) != len(steam):
		return dict(source="fragq", reason=gt("two players share a Steam account"))
	team_size = min(match.cfg["team_size"], len(match.players) // 2)
	if team_size < 1:
		return dict(source="fragq", reason=gt("not enough players"))
	try:
		data = await _request("POST", "/balance", dict(
			steam_ids=list(steam.values()), game_type=match.cfg["slipgate_game_type"], team_size=team_size,
			rating_set=rating_set(match.cfg.get("slipgate_ladder")),
		), api_key=key())
	except SlipgateError as e:
		_note_error(e)
		return dict(source="fragq", reason=gt("Slipgate unavailable"))
	by_steam = {sid: uid for uid, sid in steam.items()}
	teams = []
	for t in (data.get("teams") or [])[:2]:
		ids = [by_steam.get(str(s)) for s in (t.get("steam_ids") or []) if isinstance(t, dict)]
		teams.append(ids)
	flat = [uid for t in teams for uid in t]
	if (len(teams) != 2 or None in flat or len(set(flat)) != len(flat)
			or any(not t or len(t) > team_size for t in teams)):
		_note_error(SlipgateError("Slipgate's teams didn't match the players of the match."))
		return dict(source="fragq", reason=gt("Slipgate's answer didn't fit the match"))
	win = [float(x) for x in (data.get("win_probabilities") or [])[:2]]
	return dict(
		source="slipgate", teams=teams, quality=float(data.get("quality") or 0),
		win=win if len(win) == 2 else None, rating_set=data.get("rating_set"),
	)


def balance_line(match):
	""" The line under the teams of the match message, or None. """
	b = getattr(match, "balance", None)
	if not b:
		return None
	gt = match.qc.gt
	if b["source"] == "slipgate":
		line = gt("Balanced by Slipgate · fairness {q}%").format(q=round(b["quality"] * 100))
		if b.get("win"):
			line += " · " + " / ".join(
				f"{t.name} {round(p * 100)}%" for t, p in zip(match.teams[:2], b["win"]))
		return line
	return gt("Balanced by FragQ ratings ({reason})").format(reason=b["reason"])


# ------------------------------------------------------------------ starting ratings

def _starting_rating(rating_obj, ladder, provisional):
	"""
	(rating, deviation) on the channel's own scale from a place on the Slipgate ladder: the player's percentile
	becomes a normal score around the channel's initial rating, one initial deviation per standard deviation.
	Scale-free, so it doesn't matter how Slipgate's own numbers run.
	"""
	rank, total = int(ladder["rank"]), int(ladder["total"])
	pct_below = min(0.99, max(0.01, 1 - (rank - 0.5) / total))
	z = NormalDist().inv_cdf(pct_below)
	rating = round(rating_obj.init_rp + z * rating_obj.init_deviation)
	if type(rating_obj).__name__ == "FlatRating":
		return max(1, rating), None
	deviation = rating_obj.init_deviation if provisional else round(rating_obj.init_deviation * 0.6)
	return max(1, rating), max(deviation, rating_obj.min_deviation or 0)


async def seed_ratings(qc, players, game_type, ladder="standard"):
	"""
	Players of a ranked match who have no FragQ rating in this channel yet get one from their place on the
	Slipgate ladder of `game_type`. Once per player: afterwards they have a rating, and Slipgate isn't asked again.
	"""
	if not (connected() and qc.cfg.slipgate_seed and game_type):
		return
	rating = qc.rating
	known = await _rated_users(rating, [p.id for p in players])
	new = [p for p in players if p.id not in known and steam_id_of(p)]
	if not new:
		return

	async def one(member):
		try:
			r = await ladder_rating(steam_id_of(member), game_type, ladder)
		except SlipgateError as e:
			_note_error(e)
			return
		ladder = (r or {}).get("ladder") or {}
		if not r or not ladder.get("rank") or int(ladder.get("total") or 0) < MIN_LADDER:
			return
		value, deviation = _starting_rating(rating, ladder, bool(r.get("provisional")))
		await rating.set_rating(member, rating=value, deviation=deviation, reason="Slipgate starting rating")
		_counts["seeded"] += 1
		log.info(f"{get_nick(member)} starts at {value} in #{qc.id} from Slipgate {game_type} "
				 f"(rank {ladder['rank']} of {ladder['total']}).")

	try:
		await asyncio.wait_for(asyncio.gather(*(one(p) for p in new)), timeout=TIMEOUT)
	except asyncio.TimeoutError:
		_note_error(SlipgateError("Slipgate didn't answer in time for starting ratings."))


async def _rated_users(rating, user_ids):
	ids = set(user_ids)
	data = await db.select(["user_id", "rating"], rating.table, where={"channel_id": rating.channel_id})
	return {d["user_id"] for d in data if d["user_id"] in ids and d["rating"] is not None}


# ------------------------------------------------------------------ Slipgate details on posted results
#
# A Quake Live connector with "Add Slipgate details to results" on: after FragQ posted a game server's result,
# it looks the match up on Slipgate by its match GUID (the plugin sends Quake Live's MATCH_GUID as match_uid) and
# adds a link, the top highlights and whether demos exist to the posted message. Slipgate only has the match once
# its own plugin uploaded it, so FragQ asks a few times (RESULT_TRIES after the result) and keeps where it is in
# fragq_match_results.slipgate, so a restart picks up where it left off. Public endpoints: no key needed.

RESULT_TRIES = (30, 120, 300, 900)   # seconds after the result was posted
if os.environ.get("SLIPGATE_RESULT_TRIES"):   # development and tests only: shorter waits
	RESULT_TRIES = tuple(int(x) for x in os.environ["SLIPGATE_RESULT_TRIES"].split(","))
RESUME_WINDOW = 1800                 # after a restart, pick up results this recent that are still waiting
END_WINDOW = 300                     # the search by player: a Slipgate match that ended this close to the result
MOMENTS = {
	"midair_rail": ("🎯", "Midair rail"), "multikill": ("💥", "Multikill"), "clutch": ("🔥", "Clutch"),
	"first_blood": ("🩸", "First blood"), "revenge": ("😤", "Revenge"), "gauntlet": ("🥊", "Gauntlet kill"),
	"streak_end": ("🛑", "Streak ended"), "streak_ender": ("🛑", "Streak ended"),
}
REASONS = {"min_players": "too few players", "aborted": "aborted", "unrated_factory": "non-standard settings"}

_waiting = {}            # result id -> (next try at, try number)
_working = set()
_counts["results"] = 0


def match_url(guid):
	return f"{SITE}/matches/{guid}"


def _plain(nick):
	""" A Quake Live nick without its ^colour codes. """
	return re.sub(r"\^[0-9a-zA-Z]", "", str(nick or "")).strip() or "?"


async def match_details(guid):
	""" dict(match, moments, demos) for a Slipgate match GUID, or None while Slipgate doesn't have it. """
	auth = key() if connected() else None
	match = await _request("GET", f"/matches/{guid}", api_key=auth, not_found=True, timeout=COMMAND_TIMEOUT)
	if match is None:
		return None
	out = dict(match=match, moments=[], demos={})
	for name, path, params in (("moments", f"/matches/{guid}/moments", dict(limit="3")), ("demos", f"/matches/{guid}/demos", None)):
		try:
			data = await _request("GET", path, api_key=auth, params=params, not_found=True, timeout=COMMAND_TIMEOUT)
		except RateLimited:
			raise
		except SlipgateError as e:
			_note_error(e)
			continue
		if data:
			out[name] = data.get("moments") or [] if name == "moments" else data
	return out


async def _search(result, at):
	"""
	The Slipgate match of a result whose GUID Slipgate doesn't know: one of its players' matches on the same map
	that ended within END_WINDOW of the result and has most of its players. None if there's no such match.
	"""
	steam = [str(p["id"]) for p in result["players"] if p.get("id_type") == "steam"]
	if not steam:
		return None
	params = dict(player=steam[0], within="1", limit="10")
	if result.get("map"):
		params["map"] = str(result["map"]).lower()
	auth = key() if connected() else None
	data = await _request("GET", "/matches", api_key=auth, params=params, timeout=COMMAND_TIMEOUT)
	near = []
	for m in data.get("matches") or []:
		try:
			ended = dt_parse(m.get("ended_at"))
		except (TypeError, ValueError):
			continue
		if abs(ended - at) <= END_WINDOW:
			near.append((abs(ended - at), m.get("match_guid")))
	for _, guid in sorted(near)[:2]:
		details = await match_details(guid)
		if details:
			theirs = {str(p.get("steam_id")) for p in details["match"].get("players") or []}
			if len(theirs & set(steam)) * 2 >= len(steam):
				return details
	return None


def dt_parse(value):
	from datetime import datetime
	return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()


def details_field(details, names):
	""" (name, value) of the field added to a posted result. names: {steam_id: shown name}. """
	m, guid = details["match"], details["match"].get("match_guid")
	url = match_url(guid)
	head = [f"[Full stats on Slipgate]({url})"]
	if m.get("rated"):
		head.append("rated")
	elif m.get("reject_reason") or m.get("rated") is False:
		why = REASONS.get(m.get("reject_reason"), str(m.get("reject_reason") or "").replace("_", " "))
		head.append("not rated" + (f" ({why})" if why else ""))
	povs = [d for d in (details["demos"] or {}).get("povs") or [] if isinstance(d, dict)]
	merged = (details["demos"] or {}).get("merged")
	if povs or merged:
		parts = [f"{len(povs)} player demo" + ("" if len(povs) == 1 else "s")] if povs else []
		if merged:
			parts.append("merged demo")
		head.append(f"[{' · '.join(parts)}]({url})")
	lines = [" · ".join(head)]
	for x in (details["moments"] or [])[:3]:
		kind = str(x.get("kind") or "")
		emoji, label = MOMENTS.get(kind, ("⭐", kind.replace("_", " ").capitalize() or "Highlight"))
		mag = x.get("magnitude")
		if kind == "clutch" and mag:
			label += f" 1v{mag}"
		elif kind == "multikill" and mag:
			label += f" ×{mag}"
		who = names.get(str(x.get("steam_id"))) or _plain(x.get("nick"))
		lines.append(f"{emoji} {label}: **{who}**")
	return "🔎 Slipgate", "\n".join(lines)[:1024]


async def watch_result(result_id):
	""" A result was posted by a connector with Slipgate details on: start looking for it on Slipgate. """
	await db.update("fragq_match_results", dict(slipgate=json.dumps(dict(state="waiting", tries=0))), keys=dict(id=result_id))
	_waiting[result_id] = (time.time() + RESULT_TRIES[0], 0)


async def resume_results():
	""" After a restart: results posted in the last RESUME_WINDOW that were still being looked up. """
	since = time.time() - RESUME_WINDOW
	for row in await db.select(["id", "at", "slipgate"], "fragq_match_results"):
		s = row.get("slipgate")
		if isinstance(s, str):
			try:
				s = json.loads(s)
			except ValueError:
				s = None
		if isinstance(s, dict) and s.get("state") == "waiting" and (row.get("at") or 0) >= since:
			tries = int(s.get("tries") or 0)
			if tries < len(RESULT_TRIES):
				_waiting[row["id"]] = (max(time.time() + 5, row["at"] + RESULT_TRIES[tries]), tries)


async def _finish(result_id, state, **extra):
	_waiting.pop(result_id, None)
	await db.update("fragq_match_results", dict(slipgate=json.dumps(dict(state=state, **extra))), keys=dict(id=result_id))


async def _look_up(result_id, tries):
	row = await db.select(["id", "connector_id", "channel_id", "queue_id", "message_id", "match_uid", "at", "data"],
						  "fragq_match_results", where=dict(id=result_id), one=True)
	c = bot.connectors.connectors.get(row["connector_id"]) if row else None
	if not row or not c or not row["message_id"] or not row["match_uid"] or not c["slipgate_details"]:
		return await _finish(result_id, "skipped")
	qc = bot.queue_channels.get(row["channel_id"])
	queue = next((q for q in qc.queues if q.id == row["queue_id"]), None) if qc else None
	if queue is not None and queue.cfg.slipgate_results_off:   # turned off for the queue since the result came in
		return await _finish(result_id, "disabled")
	result = row["data"] if isinstance(row["data"], dict) else json.loads(row["data"])
	last = tries + 1 >= len(RESULT_TRIES)
	try:
		details = await match_details(row["match_uid"])
		if details is None and last:
			details = await _search(result, row["at"])
	except RateLimited:
		_waiting[result_id] = (max(_paused_until, time.time()) + 1, tries)   # not a try: ask again after the pause
		return
	except SlipgateError as e:
		_note_error(e)
		details = None
	if details is None:
		if last:
			log.info(f"Slipgate: no match {row['match_uid']} (result {result_id}) after {len(RESULT_TRIES)} tries.")
			return await _finish(result_id, "not_found")
		_waiting[result_id] = (row["at"] + RESULT_TRIES[tries + 1], tries + 1)
		await db.update("fragq_match_results", dict(slipgate=json.dumps(dict(state="waiting", tries=tries + 1))), keys=dict(id=result_id))
		return

	guid = details["match"].get("match_guid") or row["match_uid"]
	channel = dc.get_channel(row["channel_id"])
	try:
		msg = await channel.fetch_message(row["message_id"]) if channel else None
	except NotFound:
		msg = None
	except DiscordException as e:
		log.error(f"Slipgate: couldn't read result message {row['message_id']}: {e}")
		msg = None
	if msg is None or not msg.embeds:
		return await _finish(result_id, "gone", guid=guid)
	extra = await bot.fragdex.owners([p["id"] for p in result["players"] if p.get("id_type") == "steam"], channel.guild)
	names = bot.connectors._shown_names(result, channel.guild, extra)
	name, value = details_field(details, names)
	embed = msg.embeds[0]
	embed.url = match_url(guid)
	if len(embed.fields) < 25 and len(embed) + len(name) + len(value) <= 6000:
		embed.add_field(name=name, value=value, inline=False)
	try:
		await msg.edit(embed=embed)
	except DiscordException as e:
		log.error(f"Slipgate: couldn't edit result message {row['message_id']}: {e}")
		return await _finish(result_id, "gone", guid=guid)
	_counts["results"] += 1
	log.info(f"Slipgate: added match {guid} to result {result_id}.")
	await _finish(result_id, "found", guid=guid, url=match_url(guid), rated=bool(details["match"].get("rated")))


async def _run(result_id, tries):
	try:
		await _look_up(result_id, tries)
	except Exception as e:
		log.error(f"Slipgate: looking up result {result_id} failed: {e!r}")
		_waiting.pop(result_id, None)
	finally:
		_working.discard(result_id)


async def think(frame_time):
	for result_id, (when, tries) in list(_waiting.items()):
		if when <= frame_time and result_id not in _working:
			_working.add(result_id)
			asyncio.ensure_future(_run(result_id, tries))


@dc.event
async def on_init():
	try:
		await resume_results()
	except Exception as e:
		log.error(f"Slipgate: couldn't resume result lookups: {e!r}")


@dc.event
async def on_think(frame_time):
	await think(frame_time)
