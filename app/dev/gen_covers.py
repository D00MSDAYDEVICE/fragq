#!/usr/bin/env python3
"""
Draws FragQ's default cover images for QueueGen's Discord scheduled events (bot/queuegen.py COVERS).

    cd app && python dev/gen_covers.py

Writes webui/static/covers/<name>.png at 1600x640: Discord's 2.5:1 event cover, twice its recommended 800x320.
Everything is drawn at twice that size and scaled down, for smooth edges. Uses the web panel's Chakra Petch font.
"""
import math
import os
import random

from PIL import Image, ImageDraw, ImageFilter, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.dirname(HERE)
OUT = os.path.join(APP, "webui", "static", "covers")
FONTS = os.path.join(APP, "webui", "static", "fonts")

W, H = 1600, 640
S = 2                      # supersampling
BG, BG2 = (11, 15, 20), (14, 20, 27)
PANEL = (21, 30, 40)
LINE = (44, 56, 70)
TEXT = (230, 237, 243)
MUTED = (135, 148, 165)
ACCENT = (31, 242, 162)
RED, BLUE = (242, 73, 92), (64, 140, 255)


def font(weight, size):
	return ImageFont.truetype(os.path.join(FONTS, f"ChakraPetch-{weight}-latin.woff2"), size * S)


def mono(size):
	return ImageFont.truetype(os.path.join(FONTS, "JetBrainsMono-latin.woff2"), size * S)


def canvas():
	im = Image.new("RGB", (W * S, H * S), BG)
	px = ImageDraw.Draw(im)
	for y in range(0, H * S, 4):   # top-to-bottom gradient
		t = y / (H * S)
		px.rectangle([0, y, W * S, y + 4], fill=tuple(int(a + (b - a) * t) for a, b in zip(BG2, BG)))
	return im


def glow(im, xy, radius, color, strength=0.55):
	""" A soft coloured light at xy. """
	layer = Image.new("RGB", im.size, (0, 0, 0))
	d = ImageDraw.Draw(layer)
	x, y = xy
	d.ellipse([x - radius, y - radius, x + radius, y + radius], fill=color)
	layer = layer.filter(ImageFilter.GaussianBlur(radius * 0.6))
	return Image.blend(im, Image.composite(layer, im, layer.convert("L")), strength)


def grid(d, step, color, x0=0, y0=0, x1=None, y1=None):
	x1, y1 = x1 or W * S, y1 or H * S
	for x in range(x0, x1, step * S):
		d.line([x, y0, x, y1], fill=color, width=S)
	for y in range(y0, y1, step * S):
		d.line([x0, y, x1, y], fill=color, width=S)


def reticle(d, cx, cy, r, color, width, ticks=True, inner=True):
	""" The FragQ mark: a ring, four ticks and two lines (docs/assets/logo.svg, r = 8 of 32). """
	u = r / 8
	w = max(1, int(width))
	d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=color, width=w)
	def seg(x0, y0, x1, y1):
		d.line([x0, y0, x1, y1], fill=color, width=w)
		for x, y in ((x0, y0), (x1, y1)):   # round caps
			d.ellipse([x - w / 2, y - w / 2, x + w / 2, y + w / 2], fill=color)
	if ticks:
		seg(cx, cy - 11.5 * u, cx, cy - 5.5 * u)
		seg(cx, cy + 5.5 * u, cx, cy + 11.5 * u)
		seg(cx - 11.5 * u, cy, cx - 5.5 * u, cy)
		seg(cx + 5.5 * u, cy, cx + 11.5 * u, cy)
	if inner:
		seg(cx - 3.2 * u, cy - 1.7 * u, cx + 3.2 * u, cy - 1.7 * u)
		seg(cx - 3.2 * u, cy + 1.7 * u, cx + 0.6 * u, cy + 1.7 * u)


def slanted(text_parts, size, slant=0.22):
	"""
	Heavy slanted text like the FragQ wordmark: [(text, colour), ...] -> RGBA image (supersampled).
	"""
	f = font(700, size)
	widths = [f.getlength(t) for t, _ in text_parts]
	asc, desc = f.getmetrics()
	w, h = int(sum(widths) + size * S * 0.6), int(asc + desc + size * S * 0.2)
	im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
	d = ImageDraw.Draw(im)
	x = size * S * 0.1
	for (t, c), tw in zip(text_parts, widths):
		d.text((x, size * S * 0.05), t, font=f, fill=c)
		x += tw
	shift = int(h * slant)
	im = im.transform((w + shift, h), Image.AFFINE, (1, slant, -shift, 0, 1, 0), resample=Image.BICUBIC)
	return im.crop(im.getbbox())


def logo(size):
	"""
	Ring and slanted wordmark, like webui/static/logo.png: a big ring with ticks above and below, the word across
	it, and the ring broken where the letters cross it. RGBA (supersampled).
	"""
	word = slanted([("Frag", TEXT), ("Q", ACCENT)], size)
	r = int(word.width * 0.37)
	w = max(2, int(r * 0.085))
	im = Image.new("RGBA", (max(word.width, 2 * r) + 4 * w, int(2 * r * 1.5) + 4 * w), (0, 0, 0, 0))
	cx, cy = im.width // 2, im.height // 2
	ring = Image.new("RGBA", im.size, (0, 0, 0, 0))
	d = ImageDraw.Draw(ring)
	d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=ACCENT, width=w)
	for sign in (-1, 1):
		y0, y1 = cy + sign * r * 1.42, cy + sign * r * 0.74
		d.line([cx, y0, cx, y1], fill=ACCENT, width=w)
		for y in (y0, y1):
			d.ellipse([cx - w / 2, y - w / 2, cx + w / 2, y + w / 2], fill=ACCENT)
	pos = (cx - word.width // 2, cy - word.height // 2 + int(word.height * 0.04))
	knock = Image.new("L", im.size, 0)   # the letters, a little fatter: the ring stops short of them
	knock.paste(word.getchannel("A"), pos)
	knock = knock.filter(ImageFilter.GaussianBlur(w * 0.9)).point(lambda v: 255 if v > 8 else 0)
	alpha = ring.getchannel("A")
	ring.putalpha(Image.composite(Image.new("L", im.size, 0), alpha, knock))
	im.alpha_composite(ring)
	im.alpha_composite(word, pos)
	return im.crop(im.getbbox())


def label(d, xy, text, size, color, anchor="la", spacing=0.18):
	""" Letter-spaced capitals in the mono font. """
	f = mono(size)
	text = text.upper()
	total = sum(f.getlength(ch) for ch in text) + size * S * spacing * (len(text) - 1)
	x, y = xy
	if anchor[0] == "m":
		x -= total / 2
	elif anchor[0] == "r":
		x -= total
	for ch in text:
		d.text((x, y), ch, font=f, fill=color, anchor="l" + anchor[1])
		x += f.getlength(ch) + size * S * spacing


def brackets(d, box, length, color, width):
	""" HUD corner brackets around box. """
	x0, y0, x1, y1 = box
	for (x, y, dx, dy) in ((x0, y0, 1, 1), (x1, y0, -1, 1), (x0, y1, 1, -1), (x1, y1, -1, -1)):
		d.line([x, y, x + dx * length, y], fill=color, width=width)
		d.line([x, y, x, y + dy * length], fill=color, width=width)


def noise(im, amount=6, seed=1):
	""" A little film grain, so gradients don't band. """
	rnd = random.Random(seed)
	n = Image.effect_noise(im.size, 18).convert("RGB")
	return Image.blend(im, n, amount / 255 * rnd.uniform(0.9, 1.1))


def save(im, name):
	im = noise(im).resize((W, H), Image.LANCZOS)
	os.makedirs(OUT, exist_ok=True)
	path = os.path.join(OUT, name + ".png")
	im.save(path, optimize=True)
	print(f"{path}  {os.path.getsize(path) // 1024} KB")


# ------------------------------------------------------------------ the covers

def cover_crosshair():
	""" The default: the logo on the left, a big faint reticle on the right, on a fine grid. """
	im = canvas()
	im = glow(im, (int(W * S * 0.3), int(H * S * 0.5)), 420 * S, (10, 70, 50), 0.6)
	d = ImageDraw.Draw(im)
	grid(d, 40, (17, 24, 32))
	reticle(d, W * S * 0.78, H * S * 0.5, 230 * S, (24, 64, 52), 6 * S, inner=False)
	reticle(d, W * S * 0.78, H * S * 0.5, 110 * S, (20, 44, 38), 3 * S, ticks=False)
	lg = logo(104)
	im.paste(lg, (int(W * S * 0.3 - lg.width / 2), int(H * S * 0.46 - lg.height / 2)), lg)
	d = ImageDraw.Draw(im)
	label(d, (W * S * 0.3, H * S * 0.86), "Scheduled match", 26, MUTED, anchor="mm")
	d.line([W * S * 0.3 - 60 * S, H * S * 0.79, W * S * 0.3 + 60 * S, H * S * 0.79], fill=ACCENT, width=3 * S)
	save(im, "crosshair")


def cover_versus():
	""" Red against blue, split on a slant, with VS in the middle. """
	im = canvas()
	split = Image.new("L", im.size, 0)
	ImageDraw.Draw(split).polygon([(0, 0), (W * S * 0.56, 0), (W * S * 0.44, H * S), (0, H * S)], fill=255)
	left = glow(canvas(), (int(W * S * 0.2), int(H * S * 0.5)), 520 * S, (90, 18, 30), 0.85)
	right = glow(canvas(), (int(W * S * 0.8), int(H * S * 0.5)), 520 * S, (18, 44, 100), 0.85)
	im = Image.composite(left, right, split)
	d = ImageDraw.Draw(im)
	grid(d, 48, (26, 31, 40))
	for i, c in enumerate((RED, BLUE)):   # the dividing edge
		off = (-5 + 10 * i) * S
		d.line([W * S * 0.56 + off, 0, W * S * 0.44 + off, H * S], fill=c, width=4 * S)
	for cx, c in ((W * S * 0.22, RED), (W * S * 0.78, BLUE)):
		reticle(d, cx, H * S * 0.5, 150 * S, tuple(int(v * 0.45) for v in c), 5 * S)
	vs = slanted([("VS", TEXT)], 170)
	pad = 40 * S
	pos = (int(W * S / 2 - vs.width / 2), int(H * S * 0.47 - vs.height / 2))
	shadow = Image.new("L", im.size, 0)   # soft dark halo, so VS reads over the dividing lines
	shadow.paste(vs.getchannel("A"), (pos[0], pos[1] + 8 * S))
	shadow = shadow.filter(ImageFilter.GaussianBlur(pad / 2)).point(lambda v: min(255, v * 6))
	im.paste(BG, (0, 0), shadow)
	im.paste(vs, pos, vs)
	lg = logo(30)
	m = 48 * S
	im.paste(lg, (m, m), lg)
	save(im, "versus")


def cover_grid():
	""" A green perspective floor under the logo, like an arena. """
	im = canvas()
	d = ImageDraw.Draw(im)
	horizon, vx = H * S * 0.66, W * S / 2
	for i in range(-24, 25):   # lines to the vanishing point
		x = vx + i * 140 * S
		d.line([vx + i * 6 * S, horizon, x, H * S], fill=(16, 78, 58), width=2 * S)
	y, gap = horizon, 6 * S
	while y < H * S:   # cross lines, closer together near the horizon
		d.line([0, y, W * S, y], fill=(16, 78, 58), width=2 * S)
		gap *= 1.32
		y += gap
	fade = Image.new("L", im.size, 0)
	fd = ImageDraw.Draw(fade)
	for yy in range(int(horizon), H * S, 2):
		fd.line([0, yy, W * S, yy], fill=int(255 * min(1, (yy - horizon) / (H * S - horizon) * 1.6)))
	im = Image.composite(im, canvas(), fade)
	im = glow(im, (int(vx), int(horizon)), 380 * S, (12, 90, 64), 0.7)
	d = ImageDraw.Draw(im)
	d.line([0, horizon, W * S, horizon], fill=ACCENT, width=2 * S)
	lg = logo(104)
	im.paste(lg, (int(vx - lg.width / 2), int(H * S * 0.33 - lg.height / 2)), lg)
	save(im, "grid")


def cover_hud():
	""" Minimal: the logo framed by HUD corner brackets, with a match-day tag. """
	im = canvas()
	im = glow(im, (int(W * S / 2), int(H * S / 2)), 360 * S, (10, 60, 44), 0.5)
	d = ImageDraw.Draw(im)
	for y in range(0, H * S, 6 * S):   # scanlines
		d.line([0, y, W * S, y], fill=(14, 19, 25), width=S)
	m = 56 * S
	brackets(d, (m, m, W * S - m, H * S - m), 70 * S, ACCENT, 4 * S)
	lg = logo(100)
	im.paste(lg, (int(W * S / 2 - lg.width / 2), int(H * S * 0.45 - lg.height / 2)), lg)
	d = ImageDraw.Draw(im)
	label(d, (W * S / 2, H * S * 0.85), "Match day", 28, ACCENT, anchor="mm", spacing=0.35)
	dot = (m + 44 * S, m + 44 * S)
	d.ellipse([dot[0] - 7 * S, dot[1] - 7 * S, dot[0] + 7 * S, dot[1] + 7 * S], fill=RED)
	label(d, (dot[0] + 20 * S, dot[1]), "Live", 18, MUTED, anchor="lm")
	label(d, (W * S - m - 40 * S, H * S - m - 44 * S), "FragQ event", 18, MUTED, anchor="rm")
	save(im, "hud")


if __name__ == "__main__":
	cover_crosshair()
	cover_versus()
	cover_grid()
	cover_hud()
