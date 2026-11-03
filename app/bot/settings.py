# -*- coding: utf-8 -*-
"""
Bot-wide FragQ settings (queue panel auto-repost, Steam API key, ...) edited on the web Settings page.

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
	panel_autorepost=False,         # move buried queue panels back to the bottom of their channel
	panel_autorepost_minutes=5,
	steam_api_key="",
	require_steam_link=False,
)
# Restored by the Settings page backup; the API key only when the backup includes it.
BACKUP = ("panel_autorepost", "panel_autorepost_minutes", "require_steam_link")

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


async def put(name, value):
	_values[name] = value
	await db.insert("fragq_settings", dict(name=name, value=json.dumps(value)), on_dublicate="replace")


@dc.event
async def on_init():
	await load()
