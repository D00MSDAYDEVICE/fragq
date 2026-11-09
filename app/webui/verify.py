# -*- coding: utf-8 -*-
"""
Public /verify pages: a player proves they own a Steam account by signing in through Steam.

Plain server-rendered pages outside /api, for players who have no reason to open the web panel. The
player signs in with Discord, then Steam says which account they signed in with (OpenID 2.0). FragQ
never sees a Steam password. bot.steam.verify decides what the proof does to the player's link.

return_to and realm are built from PUBLIC_URL only, never from request headers, so without it the
pages do nothing.
"""
import hmac
import html
import re
import secrets
import time
from urllib.parse import urlencode

import aiohttp
from aiohttp import web

import bot
from core.config import cfg
from core.console import log

from webui import auth

OPENID = "https://steamcommunity.com/openid/login"
OPENID_NS = "http://specs.openid.net/auth/2.0"
IDENTIFIER_SELECT = "http://specs.openid.net/auth/2.0/identifier_select"
CLAIMED_ID = re.compile(r"https://steamcommunity\.com/openid/id/(7656\d{13})")
SIGNED_NEEDED = {"op_endpoint", "claimed_id", "return_to"}  # Steam's signature must cover what FragQ relies on
STATE_COOKIE = "fragq_verify_state"
STATE_TTL = 600
PATH = "/verify"
PROOF_LABEL = {"steam": "proved with Steam sign-in", "game": "confirmed from a game server", "": "claimed, not proved yet"}

STYLE = """
:root { color-scheme: dark; }
* { box-sizing: border-box; }
body { margin: 0; min-height: 100vh; display: flex; align-items: center; justify-content: center; padding: 16px;
       background: #0b0f14; color: #e6edf3; font: 15px/1.55 system-ui, sans-serif; }
main { width: 100%; max-width: 520px; padding: 28px; background: #10171f; border: 1px solid #212b37; border-radius: 10px; }
h1 { margin: 0 0 12px; font-size: 22px; }
p { margin: 0 0 14px; color: #8794a5; }
p.who, p.link { color: #e6edf3; }
p.warn { color: #f5b942; }
p.ok { padding: 10px 14px; color: #34e39a; background: rgba(31, 242, 162, .09); border: 1px solid rgba(31, 242, 162, .28); border-radius: 6px; }
code { font-size: 13px; overflow-wrap: anywhere; }
.btn { display: inline-block; padding: 9px 16px; border-radius: 6px; background: #1ff2a2; color: #04150e; font-weight: 600; text-decoration: none; }
"""


def _esc(value):
	return html.escape(str(value), quote=True)


def _page(title, body, status=200):
	resp = web.Response(status=status, content_type="text/html", text=(
		'<!doctype html><html lang="en"><head><meta charset="utf-8">'
		'<meta name="viewport" content="width=device-width, initial-scale=1"><meta name="robots" content="noindex, nofollow">'
		f"<title>{_esc(title)} · FragQ</title><style>{STYLE}</style></head>"
		f"<body><main><h1>{_esc(title)}</h1>{body}</main></body></html>"
	))
	resp.headers["Cache-Control"] = "no-store"
	resp.headers["X-Frame-Options"] = "DENY"
	resp.headers["Content-Security-Policy"] = "default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'"
	return resp


def _button(href, label):
	return f'<a class="btn" href="{_esc(href)}">{_esc(label)}</a>'


def _problem(message, status=400):
	""" A failed attempt: says what went wrong and links nothing. """
	return _page("Steam verification failed", f"<p>{_esc(message)}</p>" + _button(cfg.WS_ROOT_URL + PATH, "Try again"), status)


def _unavailable():
	""" The reason the pages can't work right now, or None. """
	if not bot.steam.verify_url():
		return _page("Steam verification is off", "<p>This FragQ has no public address (<code>PUBLIC_URL</code>) set, so it can't "
													"ask Steam to sign you in. Ask the server admin to set it.</p>", 503)
	if not bot.bot_ready:
		return _page("FragQ is starting", "<p>The bot is still connecting to Discord. Try again in a moment.</p>", 503)
	return None


def _return_to(state):
	return f"{cfg.WS_ROOT_URL}{PATH}/steam/callback?{urlencode(dict(state=state))}"


def _describe(row):
	return f'<strong>{_esc(row.get("persona") or row["steam_id"])}</strong> (<code>{_esc(row["steam_id"])}</code>)'


async def page(request):
	if (stop := _unavailable()) is not None:
		return stop
	body = ("<p>Sign in through Steam to prove a Steam account is yours. FragQ then links it to your Discord account, "
			"marked as proved. Steam only tells FragQ your account's ID: your password stays with Steam.</p>")
	if request.query.get("login_error"):
		body += '<p class="warn">Discord sign-in didn\'t finish. Try again.</p>'
	user = auth.get_user(request)
	if user is None:
		return _page("Verify your Steam account", body + _button(f"/auth/login?{urlencode(dict(next=PATH))}", "Sign in with Discord"))
	body += f'<p class="who">Signed in to Discord as <strong>{_esc(user["name"])}</strong> (<code>{_esc(user["username"])}</code>).</p>'
	uid = int(user["id"])
	row, req = bot.steam.links.get(uid), bot.steam.requests.get(uid)
	proved = bool(row) and row.get("verified_by") == "steam"
	done = request.query.get("done")  # only shown when the link says the same, so the address can't fake it
	if done == "linked" and proved:
		body = f'<p class="ok">✓ Verified. Steam {_describe(row)} is now linked to your Discord account.</p>' + body
	elif done == "pending" and req and req.get("verified_by") == "steam":
		body = (f'<p class="ok">✓ Steam sign-in worked for {_describe(req)}. You are linked to a different Steam account, '
				"so a moderator has to approve the change.</p>") + body
	if row:
		body += f'<p class="link">Linked to Steam {_describe(row)}: {_esc(PROOF_LABEL[row.get("verified_by") or ""])}.</p>'
	if req:
		body += f'<p class="link">Waiting for a moderator to approve a change to {_describe(req)}.</p>'
	return _page("Steam account verified" if proved else "Verify your Steam account",
				 body + _button(f"{PATH}/steam", "Sign in with a different Steam account" if proved else "Sign in through Steam"))


async def start(request):
	if (stop := _unavailable()) is not None:
		return stop
	user = auth.get_user(request)
	if user is None:
		return _problem("Sign in with Discord first.", 401)
	state = secrets.token_urlsafe(24)
	query = urlencode({
		"openid.ns": OPENID_NS,
		"openid.mode": "checkid_setup",
		"openid.return_to": _return_to(state),
		"openid.realm": cfg.WS_ROOT_URL,
		"openid.identity": IDENTIFIER_SELECT,
		"openid.claimed_id": IDENTIFIER_SELECT,
	})
	resp = web.HTTPFound(f"{OPENID}?{query}")
	resp.set_cookie(
		STATE_COOKIE, auth.sign(dict(state=state, id=user["id"], exp=int(time.time() + STATE_TTL))),
		max_age=STATE_TTL, httponly=True, samesite="Lax", secure=auth._secure(request), path=PATH
	)
	resp.headers["Cache-Control"] = "no-store"
	return resp


async def _steam_confirms(fields):
	""" Ask Steam whether it really issued this sign-in. """
	try:
		async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as http:
			async with http.post(OPENID, data=dict(fields, **{"openid.mode": "check_authentication"}), allow_redirects=False) as r:
				text = (await r.text())[:4096] if r.status == 200 else ""
	except Exception as e:
		log.error(f"WEBUI| Steam sign-in check failed: {e!r}")
		return False
	return "is_valid:true" in (line.strip() for line in text.splitlines())


async def _proved_steam_id(request, user):
	""" The SteamID64 this request proves, or None with `reason` for the player. Returns (steam_id, reason). """
	saved = auth.unsign(request.cookies.get(STATE_COOKIE, "")) or {}
	state = request.query.get("state", "")
	if not state or not hmac.compare_digest(state.encode(), str(saved.get("state", "")).encode()) or saved.get("id") != user["id"]:
		return None, "This sign-in has expired or wasn't started here."

	query = request.query
	fields = {k: query[k] for k in query if k.startswith("openid.")}
	if any(len(query.getall(k)) > 1 for k in fields):  # the check and the id must be reading the same value
		return None, "Steam's answer couldn't be read."
	if fields.get("openid.mode") == "cancel":
		return None, "The Steam sign-in was cancelled."
	if (fields.get("openid.mode") != "id_res"
		or fields.get("openid.return_to") != _return_to(state)
		or fields.get("openid.op_endpoint") != OPENID
		or not SIGNED_NEEDED <= set(fields.get("openid.signed", "").split(","))):
		return None, "Steam's answer couldn't be read."
	if (m := CLAIMED_ID.fullmatch(fields.get("openid.claimed_id", ""))) is None:
		return None, "Steam's answer didn't name a Steam account."
	if not await _steam_confirms(fields):
		return None, "Steam didn't confirm this sign-in."
	return m.group(1), None


async def callback(request):
	if (stop := _unavailable()) is not None:
		stop.del_cookie(STATE_COOKIE, path=PATH)
		return stop
	user = auth.get_user(request)
	if user is None:
		resp = _problem("Sign in with Discord first.", 401)
		resp.del_cookie(STATE_COOKIE, path=PATH)
		return resp
	steam_id, reason = await _proved_steam_id(request, user)
	if steam_id is None:
		log.info(f"WEBUI| Steam verification failed for {user['username']} ({user['id']}): {reason}")
		resp = _problem(reason)
	else:
		status, _ = await bot.steam.verify(int(user["id"]), user["name"], steam_id)
		if status == "taken":
			resp = _problem("Another Discord member has already proved this Steam account. Ask a server admin if this is a mistake.", 409)
		else:  # the page shows the result; going through a redirect keeps Steam's answer out of a reload
			resp = web.HTTPFound(f"{PATH}?done={status}")
	resp.del_cookie(STATE_COOKIE, path=PATH)
	return resp
