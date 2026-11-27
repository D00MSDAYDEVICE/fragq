# -*- coding: utf-8 -*-
"""
Bot-wide FragQ settings (Steam API key, ...) edited on the web Settings page.

Stored in the database next to the channel configs, so they survive updates and are part of
database backups.
"""
import json

from core.client import dc
from core.database import db

db.ensure_table(dict(
	tname="fragq_settings",
	columns=[
		dict(cname="name", ctype=db.types.str),
		dict(cname="value", ctype=db.types.text),
	],
	primary_keys=["name"]
))

DEFAULTS = dict(
	panel_autorepost=False,         # FragQ 1.0.0 only: now the channel setting panel_autorefresh (bot.panel._migrate)
	panel_autorepost_minutes=5,
	steam_api_key="",
	require_steam_link=False,       # up to FragQ 1.4 only: now the queue setting require_steam_link (bot.steam.migrate_required)
	fragdex_url="",          # Fragdex lookups (bot.fragdex): the address, a Fragdex API key,
	fragdex_key="",
	fragdex_ok={},           # which address and key passed the last test,
	fragdex_lookup=False,    # and the switch, off until the owner turns it on
	slipgate_key="",         # Slipgate (bot.slipgate): the owner's Slipgate API key (sg_...),
	slipgate_ok={},          # and which key passed the last test
)
# Restored by the Settings page backup; the API key only when the backup includes it.
BACKUP = ("fragdex_url",)
# Still read from older backups: turned into each channel's panel_autorefresh (1.0.0) and each queue's
# require_steam_link (up to 1.4) after the restore.
LEGACY = ("panel_autorepost", "panel_autorepost_minutes", "require_steam_link")

_values = dict(DEFAULTS)


async def load():
	_values.clear()
	_values.update(DEFAULTS)
	for row in await db.select(["name", "value"], "fragq_settings"):
		try:
			_values[row["name"]] = json.loads(row["value"])
		except (TypeError, ValueError):
			pass


def get(name):
	return _values.get(name, DEFAULTS.get(name))


def names(prefix=""):
	""" The stored setting names starting with prefix (per-server settings such as queuegen:<guild id>). """
	return [n for n in _values if n.startswith(prefix)]


async def put(name, value):
	_values[name] = value
	await db.insert("fragq_settings", dict(name=name, value=json.dumps(value)), on_dublicate="replace")


@dc.event
async def on_init():
	await load()
