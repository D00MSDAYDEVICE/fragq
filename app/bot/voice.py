# -*- coding: utf-8 -*-
"""
Voice moves (per queue, off by default): FragQ moves a match's players between the queue's voice channels.

A queue names three voice channels, with any names: a Lobby and one per team. When a match starts, players
waiting in the Lobby are moved into their team's channel; when it is reported or canceled (with "Back to the
lobby" on), they are moved back. Game servers can move players too, for substitutes and team changes, through
a connector with "Move players in voice" (POST /voice).

FragQ never pulls anyone into voice or out of another voice channel. It only moves members who are already in
one of the queue's three channels: into a team channel from the Lobby (or from the other team's channel, for a
team change), and into the Lobby from a team channel.

A game names its teams its own way (Quake Live: red and blue). Each game team goes to the team channel with that
name in its channel name; otherwise to the channel most of its players are already in, or that the FragQ match
put them in; otherwise at random. The choice is kept for the rest of the match, so teams don't swap channels.
"""
import asyncio
import random
import re
import time

from nextcord import Forbidden, HTTPException

from core.client import dc
from core.console import log
from core.utils import get_nick

import bot

MAX_PLAYERS = 64
MAP_TTL = 6 * 3600          # a game team -> channel choice is forgotten after this long without a call
LABEL_RE = re.compile(r"^[\w .-]{1,40}$")

_slots = {}  # queue id -> dict(match_id, labels={label: 0 | 1}, at)


def channels(q):
	return q.cfg.voice_lobby, q.cfg.voice_team1, q.cfg.voice_team2


def enabled(q):
	""" Voice moves are on and three different voice channels are set. """
	chans = channels(q)
	return bool(q.cfg.voice_moves) and all(chans) and len({c.id for c in chans}) == 3


async def move(guild, q, member, target, reason):
	""" Move a member to `target`, one of the queue's channels. Returns what happened, as a status. """
	if member is None:
		return "not_member"
	lobby, team1, team2 = channels(q)
	current = member.voice.channel if member.voice else None
	if current is None:
		return "not_in_voice"
	if current.id == target.id:
		return "already_there"
	sources = (team1, team2) if target.id == lobby.id else (lobby, team2 if target.id == team1.id else team1)
	if current.id not in {c.id for c in sources}:
		return "other_channel"
	me = guild.me
	there, here = target.permissions_for(me), current.permissions_for(me)
	if not (there.view_channel and there.connect and there.move_members and here.move_members):
		return "no_permission"
	try:
		await member.move_to(target, reason=reason)
	except Forbidden:
		return "no_permission"
	except HTTPException as e:
		log.error(f"Voice move of {get_nick(member)} to {target.name} failed: {e}")
		return "failed"
	return "moved"


async def _move_all(q, guild, moves, reason):
	""" [(member, target)] -> {status: count} """
	counts = {}
	for member, target in moves:
		status = await move(guild, q, member, target, reason)
		counts[status] = counts.get(status, 0) + 1
	return counts


def _summary(counts):
	return ", ".join(f"{n} {status.replace('_', ' ')}" for status, n in sorted(counts.items())) or "nobody to move"


async def match_started(match):
	""" The teams are final: move each team from the Lobby into its channel. """
	q = match.queue
	if not enabled(q) or not (match.teams[0] and match.teams[1]):
		return
	try:
		guild = dc.get_guild(match.qc.guild_id)
		lobby, team1, team2 = channels(q)
		_slots.pop(q.id, None)   # a new match: game teams are matched to channels again
		moves = [(guild.get_member(p.id), team1) for p in match.teams[0]] + [(guild.get_member(p.id), team2) for p in match.teams[1]]
		counts = await _move_all(q, guild, moves, f"FragQ match #{match.id}")
		log.info(f"Voice moves for match #{match.id} ({q.name}): {_summary(counts)}.")
	except Exception as e:
		log.error(f"Voice moves for match #{match.id} failed: {e!r}")


async def match_ended(match):
	""" The match was reported or canceled: move its players from the team channels back to the Lobby. """
	q = match.queue
	if not enabled(q) or not q.cfg.voice_return:
		return
	try:
		guild = dc.get_guild(match.qc.guild_id)
		lobby = channels(q)[0]
		counts = await _move_all(q, guild, [(guild.get_member(p.id), lobby) for p in match.teams[0] + match.teams[1]],
								 f"FragQ match #{match.id} ended")
		log.info(f"Voice moves after match #{match.id} ({q.name}): {_summary(counts)}.")
	except Exception as e:
		log.error(f"Voice moves after match #{match.id} failed: {e!r}")


def start(coro):
	""" Run voice moves without holding up the match messages. """
	asyncio.create_task(coro)


# ------------------------------------------------------------------ game servers (connector API)

def _slot_by_name(label, team1, team2):
	""" 0 or 1 when exactly one team channel has the game team's name in its name, else None. """
	low = label.lower()
	a, b = low in team1.name.lower(), low in team2.name.lower()
	return 0 if a and not b else 1 if b and not a else None


def team_slots(q, teams, match=None, guild=None, owners=None):
	"""
	{game team label: 0 for the first team channel, 1 for the second}. By channel name first, then the choice
	already made in this match, then where the players are (in the FragQ match's teams and in the channels),
	then at random.
	"""
	lobby, team1, team2 = channels(q)
	labels = list(teams)
	named = {label: _slot_by_name(label, team1, team2) for label in labels}
	if all(s is not None for s in named.values()) and len(set(named.values())) == len(labels):
		return named

	now = time.time()
	match_id = match.id if match else None
	saved = _slots.get(q.id)
	if saved and now - saved["at"] < MAP_TTL and saved["match_id"] == match_id and set(labels) <= set(saved["labels"]):
		saved["at"] = now
		return {label: saved["labels"][label] for label in labels}

	options = [{labels[0]: 0}, {labels[0]: 1}] if len(labels) == 1 else [{labels[0]: 0, labels[1]: 1}, {labels[0]: 1, labels[1]: 0}]
	options = [o for o in options if all(named[k] is None or named[k] == v for k, v in o.items())] or options
	match_teams = [{p.id for p in match.teams[0]}, {p.id for p in match.teams[1]}] if match else [set(), set()]
	chan_ids = [team1.id, team2.id]

	def score(option):
		n = 0
		for label, slot in option.items():
			for sid in teams[label]:
				uid = (owners or {}).get(sid)
				if uid is None:
					continue
				n += uid in match_teams[slot]
				member = guild.get_member(uid) if guild else None
				n += bool(member and member.voice and member.voice.channel and member.voice.channel.id == chan_ids[slot])
		return n

	best = max(score(o) for o in options)
	choice = random.choice([o for o in options if score(o) == best])
	old = saved["labels"] if saved and saved["match_id"] == match_id else {}
	_slots[q.id] = dict(match_id=match_id, labels=dict(old, **choice), at=now)
	return choice


def _steam_list(value, what):
	ConnectorError = bot.connectors.ConnectorError
	if value is None:
		return []
	if not isinstance(value, list) or not all(isinstance(s, str) and bot.connectors.STEAM_RE.match(s) for s in value):
		raise ConnectorError(400, f"{what} must be a list of SteamID64 strings.")
	return value


async def _queue_for(c, steam_ids, data):
	""" The queue (and the FragQ match, if one is found) a voice request is for. """
	ConnectorError = bot.connectors.ConnectorError
	queues = bot.connectors.queue_objects(c)
	on = [(q, qc) for q, qc in queues if enabled(q)]
	if not on:
		raise ConnectorError(409, "None of this connector's queues has voice moves turned on, with its three voice channels set.")
	name = data.get("queue")
	if name is not None:
		if not isinstance(name, str):
			raise ConnectorError(400, "'queue' must be a queue name.")
		found = next(((q, qc) for q, qc in queues if q.name.lower() == name.lower()), None)
		if found is None:
			raise ConnectorError(400, f"This connector has no queue named '{name[:60]}'.")
		if not enabled(found[0]):
			raise ConnectorError(409, f"Voice moves aren't turned on for the queue {found[0].name}.")
	else:
		found = None
	result = dict(players=[dict(id=sid, id_type="steam") for sid in steam_ids], queue=found[0].name if found else None,
				  fragq_match_id=data.get("fragq_match_id") if isinstance(data.get("fragq_match_id"), int) else None)
	m = await bot.connectors.find_match(c, result)
	match = next((x for x in bot.active_matches if m and x.id == m["match_id"]), None)
	if found is None and m and enabled(m["queue"]):
		found = (m["queue"], m["qc"])
	if found is None:
		if len(on) > 1:
			raise ConnectorError(400, "Several of this connector's queues have voice moves on, and no FragQ match was found "
									  "for these players. Send the queue's name in 'queue'.")
		found = on[0]
	if match and match.queue.id != found[0].id:
		match = None
	return found[0], found[1], match


async def from_game(c, data):
	""" POST /voice: {"teams": {"red": [steam ids], "blue": [...]}, "lobby": [steam ids], "queue": "name"} """
	ConnectorError = bot.connectors.ConnectorError
	if not isinstance(data, dict):
		raise ConnectorError(400, "The body must be a JSON object.")
	teams = data.get("teams") or {}
	if not isinstance(teams, dict) or len(teams) > 2:
		raise ConnectorError(400, "'teams' must be an object with at most two teams, such as {\"red\": [...], \"blue\": [...]}.")
	for label in teams:
		if not LABEL_RE.match(label):
			raise ConnectorError(400, "Team names can be up to 40 letters, digits, spaces, dots, dashes or underscores.")
	teams = {label: _steam_list(ids, f"Team '{label}'") for label, ids in teams.items()}
	lobby_ids = _steam_list(data.get("lobby"), "'lobby'")
	every = [sid for ids in teams.values() for sid in ids] + lobby_ids
	if not every:
		raise ConnectorError(400, "Send at least one player in 'teams' or 'lobby'.")
	if len(every) > MAX_PLAYERS:
		raise ConnectorError(400, f"At most {MAX_PLAYERS} players per request.")
	if len(set(every)) != len(every):
		raise ConnectorError(400, "A player can only be in one team, or in 'lobby'.")
	guild = dc.get_guild(c["guild_id"])
	if guild is None or guild.unavailable:
		raise ConnectorError(503, "The bot can't see this connector's Discord server right now.")

	q, qc, match = await _queue_for(c, every, data)
	owners = bot.connectors._steam_owners()
	found = await bot.fragdex.owners([sid for sid in every if sid not in owners], guild)   # Fragdex, if turned on
	owners.update(found)
	lobby, team1, team2 = channels(q)
	slots = team_slots(q, {k: v for k, v in teams.items() if v}, match, guild, owners) if any(teams.values()) else {}
	plan = [(sid, (team1, team2)[slots[label]]) for label, ids in teams.items() if ids for sid in ids]
	plan += [(sid, lobby) for sid in lobby_ids]
	players = []
	for sid, target in plan:
		uid = owners.get(sid)
		member = guild.get_member(uid) if uid else None
		status = "not_linked" if uid is None else await move(guild, q, member, target, f"{c['name']} (FragQ connector)")
		players.append(dict(steam_id=sid, discord_name=member.name if member else None, status=status, channel=target.name,
							fragdex=sid in found))
	moved = sum(p["status"] == "moved" for p in players)
	log.info(f"Connector '{c['name']}': voice request for {q.name}, {moved} of {len(players)} moved.")
	return dict(ok=True, queue=q.name, match_id=match.id if match else None,
				teams={label: (team1, team2)[slot].name for label, slot in slots.items()}, players=players)
