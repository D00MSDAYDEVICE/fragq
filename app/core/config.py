# -*- coding: utf-8 -*-
"""
FragQ configuration.

Settings come from environment variables (set in .env for docker compose). A legacy PUBobot2
config.cfg in the working directory is still honoured: any value it defines is used unless the
matching environment variable is set.
"""
import os
from types import SimpleNamespace
from importlib.machinery import SourceFileLoader

_legacy = None
if os.path.isfile('config.cfg'):
	try:
		_legacy = SourceFileLoader('cfg', 'config.cfg').load_module()
	except Exception as e:
		print("Failed to load config.cfg file!")
		raise e


def _env(name, legacy=None, default=None):
	value = os.environ.get(name)
	if value is not None and value != "":
		return value
	if _legacy is not None and legacy and hasattr(_legacy, legacy):
		return getattr(_legacy, legacy)
	return default


def _int(value, default=0):
	try:
		return int(value)
	except (TypeError, ValueError):
		return default


def _id_list(value):
	if isinstance(value, (list, tuple)):
		return [int(i) for i in value]
	return [int(i) for i in str(value or "").replace(",", " ").split()]


def _bool(value):
	if isinstance(value, bool):
		return value
	return str(value).strip().lower() in ("1", "true", "yes", "on")


def _db_uri():
	if uri := _env('DB_URI', 'DB_URI'):
		return uri
	return "mysql://{user}:{password}@{host}:{port}/{db}".format(
		user=os.environ.get('MYSQL_USER', 'fragq'),
		password=os.environ.get('MYSQL_PASSWORD', ''),
		host=os.environ.get('MYSQL_HOST', 'db'),
		port=os.environ.get('MYSQL_PORT', '3306'),
		db=os.environ.get('MYSQL_DATABASE', 'fragq')
	)


DATA_DIR = os.environ.get('DATA_DIR', '.')
PUBLIC_URL = str(_env('PUBLIC_URL', 'WS_ROOT_URL', '')).rstrip('/')

cfg = SimpleNamespace(
	# Discord credentials
	DC_BOT_TOKEN=_env('DISCORD_BOT_TOKEN', 'DC_BOT_TOKEN', ''),
	DC_CLIENT_ID=_int(_env('DISCORD_CLIENT_ID', 'DC_CLIENT_ID')),
	DC_CLIENT_SECRET=_env('DISCORD_CLIENT_SECRET', 'DC_CLIENT_SECRET', ''),
	DC_INVITE_LINK=_env('DISCORD_INVITE_LINK', 'DC_INVITE_LINK', ''),
	DC_OWNER_ID=_int(_env('DISCORD_OWNER_ID', 'DC_OWNER_ID')),
	DC_SLASH_SERVERS=_id_list(_env('DISCORD_SLASH_SERVERS', 'DC_SLASH_SERVERS', '')),

	DB_URI=_db_uri(),
	LOG_LEVEL=str(_env('LOG_LEVEL', 'LOG_LEVEL', 'INFO')).upper(),
	COMMANDS_URL=_env('COMMANDS_URL', 'COMMANDS_URL', 'https://d00msdaydevice.github.io/fragq/reference/commands/'),
	HELP=_env('BOT_HELP', 'HELP', "\n".join(filter(None, (
		"FragQ is a discord bot for pickup games organisation.",
		f"Web interface: <{PUBLIC_URL}>." if PUBLIC_URL else None
	)))),
	STATUS=_env('BOT_STATUS', 'STATUS', 'pickup games'),

	# Web interface
	WS_ENABLE=_bool(_env('WEB_ENABLE', 'WS_ENABLE', True)),
	WS_HOST=_env('WEB_HOST', None, '0.0.0.0'),
	WS_PORT=_int(_env('WEB_PORT', None, 8000), 8000),
	WS_ROOT_URL=PUBLIC_URL,
	WS_OAUTH_REDIRECT_URL=_env('OAUTH_REDIRECT_URL', 'WS_OAUTH_REDIRECT_URL', PUBLIC_URL + '/auth/callback'),
	WS_SESSION_SECRET=_env('SESSION_SECRET', None, ''),
	WS_SESSION_DAYS=_int(_env('SESSION_DAYS', None, 7), 7),

	DATA_DIR=DATA_DIR,
)

if not cfg.DC_INVITE_LINK and cfg.DC_CLIENT_ID:
	# Manage Channels, Add Reactions, Send Messages, Manage Messages, Embed Links, Attach Files (queue panel
	# avatar image), Read Message History, Manage Roles
	cfg.DC_INVITE_LINK = (
		"https://discord.com/oauth2/authorize?client_id={}&scope=bot+applications.commands"
		"&permissions=268560464".format(cfg.DC_CLIENT_ID)
	)


def data_path(*parts):
	""" Path inside the persistent data directory (created on demand). """
	path = os.path.join(DATA_DIR, *parts)
	os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
	return path


_version_file = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.version')
with open(_version_file, 'r') as f:
	__version__ = f.read().strip()
