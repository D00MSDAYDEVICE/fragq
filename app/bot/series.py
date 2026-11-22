# -*- coding: utf-8 -*-
"""
Series (per queue, off by default): one pickup plays several games on the game server before the queue opens again.

With "Series length" above 1, the first match that starts from the queue starts a series. Until the series ends,
the queue is closed to everyone. Each result a game server posts for the match counts one game (bot.connectors).
The series ends with the last game's result, /endseries (or End series in the web panel), the match being
canceled (or, for an unranked match, ended), or when no result has come in for the queue's match lifetime.

An unranked match in a series stays active until the series ends, so its players can't add anywhere meanwhile; a
ranked one waits for /report as usual, and a report doesn't end the series. Between games FragQ leaves the players
in their team channels; when the series ends they go back to the Lobby ("Back to the lobby after the match").
"""
import time

from nextcord import DiscordException

from core.console import log

import bot

DEFAULT_TIMEOUT = 3 * 60 * 60


def length(q):
	""" The queue's series length: 1 (off) or more games. """
	try:
		return max(1, int(q.cfg.series_length or 1))
	except (TypeError, ValueError):
		return 1


def of(q):
	""" The queue's series in progress, or None. """
	return getattr(q, "series", None)


def for_match(match):
	""" The series a match is playing, or None. """
	s = of(match.queue)
	return s if s and s["match_id"] == match.id else None


def text(q):
	""" 'series game 2 of 3 (match #123)' """
	s = of(q)
	return q.qc.gt("series game {n} of {total} (match #{id})").format(
		n=min(s["played"] + 1, s["length"]), total=s["length"], id=s["match_id"]
	)


def held_message(q):
	return q.qc.gt("**{queue}** is held: {series}. It opens again when the series ends.").format(queue=q.name, series=text(q))


def started(match):
	""" The match message went out (at the start, or again after a substitution): start or update its series. """
	q = match.queue
	s = of(q)
	if s and s["match_id"] == match.id:
		s["players"] = [p.id for p in match.players]
		return
	if s or length(q) < 2:
		return   # another match's series (a split queue) keeps the queue
	now = int(time.time())
	q.series = dict(match_id=match.id, played=0, length=length(q), started=now, last=now, players=[p.id for p in match.players])
	log.info(f"Series of {q.name} started with match #{match.id}, {q.series['length']} games.")
	bot.panel.bump(q.qc)


def count(q, match_id):
	""" A game server result for this match came in: (game number, series length), or None if it isn't the series'. """
	s = of(q)
	if not s or s["match_id"] != match_id:
		return None
	s["played"] += 1
	s["last"] = int(time.time())
	log.info(f"Series of {q.name}: game {s['played']} of {s['length']} played (match #{match_id}).")
	bot.panel.bump(q.qc)
	return s["played"], s["length"]


def done(q):
	s = of(q)
	return bool(s and s["played"] >= s["length"])


async def end(q, why, ctx=None):
	""" End the queue's series: the queue opens again. Returns False if it had none. """
	s = of(q)
	if not s:
		return False
	q.series = None
	ctx = ctx or bot.SystemContext(q.qc)
	log.info(f"Series of {q.name} (match #{s['match_id']}) ended: {why}, {s['played']} of {s['length']} games played.")
	try:
		await ctx.notice(q.qc.gt("Series of **{queue}** is over ({why}): {played} of {total} games played. The queue is open again.").format(
			queue=q.name, why=why, played=s["played"], total=s["length"]
		))
	except DiscordException:
		pass
	match = next((m for m in bot.active_matches if m.id == s["match_id"] and m.queue is q), None)
	if match is not None and match.held and match.state == match.WAITING_REPORT:
		await match.finish_match(ctx)   # moves its players back to the Lobby
	elif match is None or match.state == match.WAITING_REPORT:
		bot.voice.start(bot.voice.series_ended(q, s["players"], s["match_id"]))
	bot.panel.bump(q.qc)
	return True


async def match_over(match, canceled=False):
	""" The match was canceled, or an unranked match in its series was ended: the series ends with it. """
	if for_match(match):
		await end(match.queue, match.qc.gt("match canceled") if canceled else match.qc.gt("match ended"))


def last_activity(match):
	""" When the match's series last heard from the game server (for the match lifetime), else None. """
	s = for_match(match)
	return s["last"] if s else None


async def think(frame_time):
	for qc in list(bot.queue_channels.values()):
		for q in qc.queues:
			s = of(q)
			if s and frame_time > s["last"] + (q.cfg.match_lifetime or DEFAULT_TIMEOUT):
				await end(q, qc.gt("no result from the game server for {time}").format(
					time=_duration(q.cfg.match_lifetime or DEFAULT_TIMEOUT)))


def _duration(seconds):
	h, m = divmod(int(seconds) // 60, 60)
	return f"{h}h{m:02}m" if h and m else f"{h}h" if h else f"{m}m"


def serialize():
	return [dict(channel_id=q.qc.id, queue_id=q.id, **q.series)
			for qc in bot.queue_channels.values() for q in qc.queues if of(q)]


def load(data):
	for d in data or []:
		qc = bot.queue_channels.get(d.get("channel_id"))
		q = next((x for x in qc.queues if x.id == d.get("queue_id")), None) if qc else None
		if q is None:
			log.error(f"Failed to load the series of queue {d.get('queue_id')}: queue not found.")
			continue
		q.series = {k: d[k] for k in ("match_id", "played", "length", "started", "last", "players") if k in d}


def match_renumbered(queue, old_id, new_id):
	""" A match restored after a restart gets a new number; its series follows it. """
	s = of(queue)
	if s and s["match_id"] == old_id:
		s["match_id"] = new_id
