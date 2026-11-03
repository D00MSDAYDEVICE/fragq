# -*- coding: utf-8 -*-
"""
Player avatars for the queue panel: one row of profile pictures per queue (filled and empty
slots), drawn into a single PNG that sits at the bottom of the panel embed, right above the buttons.

Pictures come from the player's linked Steam profile, or their Discord avatar without a link.
Downloads are cached in DATA_DIR/avatars on the persistent data volume. Steam and Discord avatar
URLs change whenever the picture changes, so entries are keyed by URL and never go stale; files
unused for 30 days are pruned.
"""
import asyncio
import hashlib
import io
import os
import time

import aiohttp
from PIL import Image, ImageDraw, ImageFont

from core.client import dc
from core.config import data_path
from core.console import log
from core.utils import get_nick

import bot

AV = 44            # avatar diameter in px
GAP = 6
RING = 2
PER_ROW = 8        # slots per line: queues over 8 get another row of 8
MAX_SLOTS = 24
MAX_QUEUES = 5
LABEL_H = 22
QUEUE_GAP = 10
SS = 3             # supersampling, for smooth circles

ACCENT = (31, 242, 162, 255)
EMPTY_RING = (128, 132, 142, 150)
EMPTY_FILL = (128, 132, 142, 40)
INITIALS_BG = (64, 68, 75, 255)
TEXT = (181, 186, 193, 255)
WHITE = (240, 242, 245, 255)

PRUNE_AFTER = 30 * 86400
RETRY_FAILED = 600

_failed = {}       # url -> time of the failed download
_rendered = {}     # signature -> png bytes
_next_prune = 0


def cache_dir():
	return os.path.dirname(data_path("avatars", "x"))


def avatar_url(member):
	""" Steam avatar if the player linked one, else their Discord avatar. """
	row = bot.steam.get_link(member.id)
	if row and row.get("avatar_url"):
		return row["avatar_url"]
	av = getattr(member, "display_avatar", None)
	if av is None:
		return None
	try:
		return str(av.with_format("png").with_size(64))
	except Exception:
		return str(av)


async def fetch(url):
	""" Avatar image bytes, from the cache or downloaded. None if unavailable. """
	if not url:
		return None
	path = os.path.join(cache_dir(), hashlib.sha1(url.encode()).hexdigest()[:24] + ".img")
	if os.path.exists(path):
		try:
			os.utime(path)
			with open(path, "rb") as f:
				return f.read()
		except OSError:
			pass
	if time.time() - _failed.get(url, 0) < RETRY_FAILED:
		return None
	try:
		async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=4)) as session:
			async with session.get(url) as resp:
				if resp.status != 200:
					raise ValueError(f"HTTP {resp.status}")
				data = await resp.read()
		if len(data) > 2_000_000:
			raise ValueError("too large")
		Image.open(io.BytesIO(data)).verify()
		tmp = path + ".tmp"
		with open(tmp, "wb") as f:
			f.write(data)
		os.replace(tmp, path)
		return data
	except Exception as e:
		_failed[url] = time.time()
		log.info(f"Couldn't download avatar {url}: {e}")
		return None


def _font(size):
	try:
		return ImageFont.load_default(size=size)  # scalable font bundled with Pillow
	except (TypeError, OSError):
		return None


def _paste_circle(canvas, data, x, y, d):
	im = Image.open(io.BytesIO(data)).convert("RGBA").resize((d, d), Image.LANCZOS)
	mask = Image.new("L", (d, d), 0)
	ImageDraw.Draw(mask).ellipse((0, 0, d - 1, d - 1), fill=255)
	canvas.paste(im, (x, y), mask)


def _compose(queues):
	"""
	queues: [(label or None, slots, [(initial, image bytes or None), ...])]
	Drawn at SS times the size and scaled down, so the circles come out anti-aliased.
	"""
	s = SS
	av, gap, ring = AV * s, GAP * s, RING * s
	font = _font(14 * s)
	cols = max(min(slots, PER_ROW) for _, slots, _ in queues)
	width = cols * av + (cols - 1) * gap
	if font:
		width = max([width] + [int(font.getlength(label)) + 2 for label, _, _ in queues if label])
	height = 0
	for label, slots, _ in queues:
		lines = -(-slots // PER_ROW)
		height += (LABEL_H * s if label and font else 0) + lines * av + (lines - 1) * gap + QUEUE_GAP * s
	height -= QUEUE_GAP * s

	canvas = Image.new("RGBA", (width, height), (0, 0, 0, 0))
	draw = ImageDraw.Draw(canvas)
	y = 0
	for label, slots, players in queues:
		if label and font:
			draw.text((0, y + 2 * s), label, font=font, fill=TEXT)
			y += LABEL_H * s
		for i in range(slots):
			x = (i % PER_ROW) * (av + gap)
			cy = y + (i // PER_ROW) * (av + gap)
			box = (x, cy, x + av - 1, cy + av - 1)
			if i < len(players):
				initial, data = players[i]
				inner = av - 2 * (ring + s)
				try:
					if data is None:
						raise ValueError
					_paste_circle(canvas, data, x + ring + s, cy + ring + s, inner)
				except Exception:
					draw.ellipse((x + ring + s, cy + ring + s, x + ring + s + inner - 1, cy + ring + s + inner - 1), fill=INITIALS_BG)
					f = _font(18 * s)
					if f:
						draw.text((x + av / 2, cy + av / 2), initial, font=f, fill=WHITE, anchor="mm")
				draw.ellipse(box, outline=ACCENT, width=ring)
			else:
				draw.ellipse(box, fill=EMPTY_FILL, outline=EMPTY_RING, width=ring)
		lines = -(-slots // PER_ROW)
		y += lines * av + (lines - 1) * gap + QUEUE_GAP * s

	out = canvas.resize((width // s, height // s), Image.LANCZOS)
	buf = io.BytesIO()
	out.save(buf, "PNG", optimize=True)
	return buf.getvalue()


def signature(qc):
	return tuple(
		(q.name, q.cfg.size, tuple((m.id, avatar_url(m)) for m in q.queue))
		for q in qc.queues[:20] if q.queue
	)[:MAX_QUEUES]


async def queue_image(qc):
	""" PNG with the players of every queue that has someone in it, or None when all are empty. """
	queues = [q for q in qc.queues[:20] if q.queue][:MAX_QUEUES]
	if not queues:
		return None
	labelled = len(qc.queues) > 1
	sig = (labelled, signature(qc))
	if sig in _rendered:
		return _rendered[sig]

	urls = {m.id: avatar_url(m) for q in queues for m in q.queue}
	pictures = dict(zip(urls.keys(), await asyncio.gather(*(fetch(u) for u in urls.values()))))
	rows = []
	for q in queues:
		slots = max(len(q.queue), min(q.cfg.size, MAX_SLOTS))
		players = [((get_nick(m)[:1] or "?").upper(), pictures.get(m.id)) for m in q.queue[:MAX_SLOTS]]
		label = f"{q.name}  {len(q.queue)}/{q.cfg.size}" if labelled else None
		rows.append((label, min(slots, MAX_SLOTS), players))
	png = _compose(rows)

	_rendered[sig] = png
	while len(_rendered) > 32:
		_rendered.pop(next(iter(_rendered)))
	return png


def prune():
	cutoff = time.time() - PRUNE_AFTER
	removed = 0
	for entry in os.scandir(cache_dir()):
		try:
			if entry.is_file() and entry.stat().st_mtime < cutoff:
				os.remove(entry.path)
				removed += 1
		except OSError:
			pass
	if removed:
		log.info(f"Pruned {removed} unused cached avatars.")


@dc.event
async def on_think(frame_time):
	global _next_prune
	if frame_time > _next_prune:
		_next_prune = frame_time + 86400
		prune()
