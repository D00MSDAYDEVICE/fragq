# -*- coding: utf-8 -*-
"""
Discord OAuth2 login and signed-cookie sessions.

Sessions are stateless (HMAC-signed JSON in a cookie), so logins survive container restarts.
The signing key comes from SESSION_SECRET or is generated once and kept in the data volume.
"""
import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from urllib.parse import quote, urlencode

import aiohttp
from aiohttp import web

from core.config import cfg, data_path
from core.console import log

COOKIE = "fragq_session"
STATE_COOKIE = "fragq_oauth_state"
DISCORD_API = "https://discord.com/api/v10"
RETURN_PATHS = ("/verify",)   # where /auth/login?next= may send someone back to, besides /


def _load_secret() -> bytes:
	if cfg.WS_SESSION_SECRET:
		return cfg.WS_SESSION_SECRET.encode()
	path = data_path("session_secret")
	if os.path.isfile(path):
		with open(path, "r") as f:
			if secret := f.read().strip():
				return secret.encode()
	secret = secrets.token_urlsafe(48)
	with open(path, "w") as f:
		f.write(secret)
	try:
		os.chmod(path, 0o600)
	except OSError:
		pass
	return secret.encode()


SECRET = _load_secret()


def _b64(data: bytes) -> str:
	return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(data: str) -> bytes:
	return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))


def sign(payload: dict) -> str:
	body = _b64(json.dumps(payload, separators=(",", ":")).encode())
	sig = _b64(hmac.new(SECRET, body.encode(), hashlib.sha256).digest())
	return f"{body}.{sig}"


def unsign(token: str):
	try:
		body, sig = token.split(".", 1)
		expected = _b64(hmac.new(SECRET, body.encode(), hashlib.sha256).digest())
		if not hmac.compare_digest(sig, expected):
			return None
		payload = json.loads(_unb64(body))
	except Exception:
		return None
	if payload.get("exp", 0) < time.time():
		return None
	return payload


def get_user(request: web.Request):
	""" Returns the session payload {id, name, avatar, exp} or None. """
	token = request.cookies.get(COOKIE)
	return unsign(token) if token else None


def _secure(request: web.Request) -> bool:
	return request.headers.get("X-Forwarded-Proto", request.scheme) == "https"


def base_url(request: web.Request) -> str:
	if cfg.WS_ROOT_URL:
		return cfg.WS_ROOT_URL
	proto = request.headers.get("X-Forwarded-Proto", request.scheme)
	host = request.headers.get("X-Forwarded-Host", request.host)
	return f"{proto}://{host}"


def redirect_uri(request: web.Request) -> str:
	if cfg.WS_ROOT_URL and cfg.WS_OAUTH_REDIRECT_URL:
		return cfg.WS_OAUTH_REDIRECT_URL
	return base_url(request) + "/auth/callback"


def avatar_url(user_id, avatar_hash, size=64):
	if avatar_hash:
		ext = "gif" if str(avatar_hash).startswith("a_") else "png"
		return f"https://cdn.discordapp.com/avatars/{user_id}/{avatar_hash}.{ext}?size={size}"
	return f"https://cdn.discordapp.com/embed/avatars/{(int(user_id) >> 22) % 6}.png"


async def login(request: web.Request):
	if not (cfg.DC_CLIENT_ID and cfg.DC_CLIENT_SECRET):
		raise web.HTTPServiceUnavailable(text="Discord OAuth is not configured: set DISCORD_CLIENT_ID and DISCORD_CLIENT_SECRET.")
	state = secrets.token_urlsafe(24)
	target = request.query.get("next")
	saved = dict(state=state, next=target if target in RETURN_PATHS else "/", exp=int(time.time() + 600))
	query = urlencode(dict(
		client_id=cfg.DC_CLIENT_ID,
		redirect_uri=redirect_uri(request),
		response_type="code",
		scope="identify",
		state=state,
		prompt="none",
	))
	resp = web.HTTPFound(f"https://discord.com/oauth2/authorize?{query}")
	resp.set_cookie(STATE_COOKIE, sign(saved), max_age=600, httponly=True, samesite="Lax", secure=_secure(request), path="/auth")
	return resp


async def callback(request: web.Request):
	state = request.query.get("state")
	code = request.query.get("code")
	saved = unsign(request.cookies.get(STATE_COOKIE, "")) or {}
	target = saved.get("next") if saved.get("next") in RETURN_PATHS else "/"
	if request.query.get("error"):
		raise web.HTTPFound(f"{target}?login_error=" + quote(request.query.get("error")))
	if not state or not code or not hmac.compare_digest(state.encode(), str(saved.get("state", "")).encode()):
		raise web.HTTPFound(f"{target}?login_error=state")

	try:
		async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as http:
			async with http.post(f"{DISCORD_API}/oauth2/token", data=dict(
				client_id=str(cfg.DC_CLIENT_ID),
				client_secret=cfg.DC_CLIENT_SECRET,
				grant_type="authorization_code",
				code=code,
				redirect_uri=redirect_uri(request),
			)) as r:
				token = await r.json()
				if r.status != 200:
					raise ValueError(token.get("error_description") or token.get("error") or r.status)
			async with http.get(f"{DISCORD_API}/users/@me", headers={
				"Authorization": f"Bearer {token['access_token']}"
			}) as r:
				me = await r.json()
				if r.status != 200:
					raise ValueError(me.get("message") or r.status)
	except Exception as e:
		log.error(f"WEBUI| OAuth login failed: {e}")
		raise web.HTTPFound(f"{target}?login_error=discord")

	payload = dict(
		id=str(me["id"]),
		name=me.get("global_name") or me["username"],
		username=me["username"],
		avatar=me.get("avatar"),
		exp=int(time.time() + cfg.WS_SESSION_DAYS * 86400),
	)
	log.info(f"WEBUI| {payload['username']} ({payload['id']}) logged in.")
	resp = web.HTTPFound(target)
	resp.set_cookie(
		COOKIE, sign(payload), max_age=cfg.WS_SESSION_DAYS * 86400,
		httponly=True, samesite="Lax", secure=_secure(request), path="/"
	)
	resp.del_cookie(STATE_COOKIE, path="/auth")
	return resp

