# -*- coding: utf-8 -*-
"""
Settings page backup: everything FragQ is configured with, in one JSON file that restores onto
another (fresh) FragQ install of the same Discord servers.

Included: bot settings, every enabled channel with its config, pause state and queues, Steam links,
web panel access grants and game connectors (with their key hashes, so game servers keep working). Not included: ratings, match history and player stats (that is what a
database backup is for), queue panels (post them again) and pending Steam account changes.

Channel, role and member references are kept as Discord ids, which are the same for any bot on the
same servers. Restoring never deletes anything: channels and queues are created or updated, links and
grants are added or replaced.
"""
import time

from core.client import dc
from core.config import cfg, __version__
from core.console import log

import bot
from webui import schema, access

FORMAT = "fragq-backup"
VERSION = 1
PARTS = ("settings", "channels", "steam_links", "web_access", "connectors")


def build(include_steam_key=False):
	settings = {name: bot.settings.get(name) for name in bot.settings.BACKUP}
	if include_steam_key and bot.steam.api_key():
		settings["steam_api_key"] = bot.steam.api_key()
	channels = []
	for qc in bot.queue_channels.values():
		guild = dc.get_guild(qc.guild_id)
		channel = dc.get_channel(qc.id)
		channels.append(dict(
			guild_id=str(qc.guild_id),
			guild_name=guild.name if guild else qc.cfg.cfg_info.get("guild_name"),
			channel_id=str(qc.id),
			channel_name=channel.name if channel else qc.cfg.cfg_info.get("channel_name"),
			paused=qc.paused,
			config=schema.ui_values(qc.cfg),
			queues=[dict(name=q.name, config=schema.ui_values(q.cfg)) for q in qc.queues],
		))
	links = [dict(
		user_id=str(r["user_id"]), steam_id=r["steam_id"], nick=r.get("nick"), persona=r.get("persona"),
		avatar_url=r.get("avatar_url"), profile_url=r.get("profile_url"), linked_at=r.get("linked_at"),
		verified_by=r.get("verified_by") or "", verified_at=r.get("verified_at"),
	) for r in bot.steam.links.values()]
	grants = [dict(
		guild_id=str(g["guild_id"]), subject_type=g["subject_type"], subject_id=str(g["subject_id"]),
		channels=[str(c) for c in g["channels"]], perms=g["perms"],
		granted_by=str(g.get("granted_by") or ""), granted_by_name=g.get("granted_by_name"),
	) for g in access.grants.values()]
	queue_ref = {q.id: dict(channel_id=str(qc.id), name=q.name) for qc in bot.queue_channels.values() for q in qc.queues}
	connectors = [dict(
		guild_id=str(c["guild_id"]), name=c["name"], game=c["game"],
		queues=[queue_ref[q] for q in c["queues"] if q in queue_ref],
		unmatched_queue=queue_ref.get(c["unmatched_queue"]),
		**{k: c[k] for k in ("prefix", "key_hash", "can_results", "can_check", "can_link", "can_export", "allowed_ips", "rate_limit",
							 "expires_at", "disabled", "created_by_name", "created_at")},
		created_by=str(c.get("created_by") or ""),
	) for c in bot.connectors.connectors.values()]
	return dict(
		format=FORMAT, version=VERSION, fragq_version=__version__, created_at=int(time.time()),
		source=cfg.WS_ROOT_URL or None,
		settings=settings, channels=channels, steam_links=links, web_access=grants, connectors=connectors,
	)


def validate(data):
	""" Raises ValueError unless `data` looks like a FragQ backup this version can read. """
	if not isinstance(data, dict) or data.get("format") != FORMAT:
		raise ValueError("This is not a FragQ backup file.")
	if not isinstance(data.get("version"), int) or data["version"] > VERSION:
		raise ValueError("This backup was made by a newer FragQ version. Update FragQ first.")
	for key, kind in (("settings", dict), ("channels", list), ("steam_links", list), ("web_access", list), ("connectors", list)):
		if not isinstance(data.get(key, kind()), kind):
			raise ValueError(f"The backup's '{key}' section is damaged.")


def _int(value):
	try:
		return int(value)
	except (TypeError, ValueError):
		return None


async def _check(factory, values, guild):
	""" (inputs, skipped): the valid part of a config, and {variable: error} for what can't be restored. """
	try:
		return await schema.check(factory, values or {}, guild), {}
	except schema.ConfigError as e:
		skipped = dict(e.errors)
		rest = {k: v for k, v in (values or {}).items() if k not in skipped}
		try:
			return await schema.check(factory, rest, guild), skipped
		except schema.ConfigError as e2:
			skipped.update(e2.errors)
			return {}, skipped


async def restore(data, parts, dry_run=False, who="?"):
	"""
	Restore the chosen `parts` of a backup. With dry_run nothing is changed; the report says what
	would happen. Returns a report: {part: {counts..., notes: [...]}}.
	"""
	validate(data)
	report = {}

	if "settings" in parts:
		allowed = bot.settings.BACKUP + bot.settings.LEGACY + ("steam_api_key",)
		values = {k: v for k, v in (data.get("settings") or {}).items() if k in allowed}
		if not dry_run:
			for k, v in values.items():
				await bot.settings.put(k, v)
		report["settings"] = dict(restored=sorted(values), steam_key="steam_api_key" in values, notes=[])

	if "channels" in parts:
		r = report["channels"] = dict(created=0, updated=0, missing=0, queues_created=0, queues_updated=0, notes=[])
		for c in data.get("channels") or []:
			cid = _int(c.get("channel_id"))
			name = f"#{c.get('channel_name') or cid}"
			channel = dc.get_channel(cid) if cid else None
			if channel is None or getattr(channel, "guild", None) is None:
				r["missing"] += 1
				r["notes"].append(f"{name} ({c.get('guild_name') or 'unknown server'}): the bot can't see this channel, skipped.")
				continue
			guild = channel.guild
			qc = bot.queue_channels.get(cid)
			inputs, skipped = await _check(bot.QueueChannel.cfg_factory, c.get("config"), guild)
			for var, err in skipped.items():
				r["notes"].append(f"#{channel.name}: setting '{var}' not restored ({err}).")
			if qc is None:
				r["created"] += 1
				if not dry_run:
					qc = await bot.QueueChannel.create(channel)
					bot.queue_channels[cid] = qc
					await qc.update_info(channel)
			else:
				r["updated"] += 1
			if not dry_run:
				if inputs:
					await qc.cfg.update(inputs)
				await qc.set_paused(bool(c.get("paused")))
			existing = {q.name.lower(): q for q in qc.queues} if qc else {}
			for qd in c.get("queues") or []:
				qname = str(qd.get("name") or (qd.get("config") or {}).get("name") or "").strip()
				try:
					bot.PickupQueue.validate_name(qname)
				except ValueError as e:
					r["notes"].append(f"#{channel.name}: queue '{qname}' skipped ({e}).")
					continue
				qvalues = dict(qd.get("config") or {}, name=qname)
				qinputs, qskipped = await _check(bot.PickupQueue.cfg_factory, qvalues, guild)
				for var, err in qskipped.items():
					r["notes"].append(f"#{channel.name} > {qname}: setting '{var}' not restored ({err}).")
				q = existing.get(qname.lower())
				if q is None:
					if "size" not in qinputs:
						r["notes"].append(f"#{channel.name}: queue '{qname}' skipped (no valid size).")
						continue
					r["queues_created"] += 1
					if not dry_run:
						cfg_obj = await bot.PickupQueue.cfg_factory.spawn(guild, f_key=qc.id)
						await cfg_obj.update(qinputs)
						qc.queues.append(bot.PickupQueue(qc, cfg_obj))
				else:
					r["queues_updated"] += 1
					if not dry_run and qinputs:
						await q.cfg.update(qinputs)
			if not dry_run:
				await bot.panel.refresh(qc, force=True)

	if "steam_links" in parts:
		rows = data.get("steam_links") or []
		if dry_run:
			taken = sum(1 for x in rows if any(
				link["steam_id"] == str(x.get("steam_id")) and link["user_id"] != _int(x.get("user_id"))
				for link in bot.steam.links.values()))
			report["steam_links"] = dict(added=len(rows) - taken, skipped=taken, notes=[])
		else:
			added, skipped = await bot.steam.restore(rows)
			report["steam_links"] = dict(added=added, skipped=skipped, notes=[])
		if report["steam_links"]["skipped"]:
			report["steam_links"]["notes"].append(
				f"{report['steam_links']['skipped']} link(s) skipped: that Steam account is already linked to another member here.")

	if "web_access" in parts:
		r = report["web_access"] = dict(added=0, replaced=0, missing=0, notes=[])
		for g in data.get("web_access") or []:
			gid, sid = _int(g.get("guild_id")), _int(g.get("subject_id"))
			kind = g.get("subject_type")
			if dc.get_guild(gid or 0) is None or sid is None or kind not in ("user", "role"):
				r["missing"] += 1
				continue
			perms = [p for p in (g.get("perms") or []) if p in access.ALL]
			channels = [c for c in (_int(x) for x in g.get("channels") or []) if c]
			if channels:
				perms = [p for p in perms if p not in access.SERVER_ONLY]
			old = access.find(gid, kind, sid)
			r["replaced" if old else "added"] += 1
			if not dry_run:
				await access.save(gid, kind, sid, channels, perms, _int(g.get("granted_by")) or 0,
								  str(g.get("granted_by_name") or who), grant_id=old["id"] if old else None)
		if r["missing"]:
			r["notes"].append(f"{r['missing']} grant(s) skipped: the bot isn't on that server.")

	if "connectors" in parts:
		r = report["connectors"] = dict(added=0, replaced=0, missing=0, notes=[])
		for x in data.get("connectors") or []:
			gid = _int(x.get("guild_id"))
			name = str(x.get("name") or "?")[:60]
			if dc.get_guild(gid or 0) is None:
				r["missing"] += 1
				r["notes"].append(f"Connector '{name}': the bot isn't on that server, skipped.")
				continue
			if not isinstance(x.get("key_hash"), str) or len(x["key_hash"]) != 64:
				r["missing"] += 1
				r["notes"].append(f"Connector '{name}': damaged key, skipped.")
				continue

			def queue_id(ref):
				qc = bot.queue_channels.get(_int((ref or {}).get("channel_id")) or 0)
				q = next((q for q in qc.queues if q.name.lower() == str((ref or {}).get("name") or "").lower()), None) if qc else None
				return q.id if q else None

			queues = [qid for qid in (queue_id(ref) for ref in x.get("queues") or []) if qid]
			lost = len(x.get("queues") or []) - len(queues)
			if dry_run and "channels" in parts and lost:
				lost = 0  # the queues may be created by the channel part of this restore
			export_only = x.get("can_export") and not (x.get("can_results") or x.get("can_check") or x.get("can_link"))
			if not queues and not export_only and not (dry_run and "channels" in parts):
				r["missing"] += 1
				r["notes"].append(f"Connector '{name}': none of its queues exist here, skipped. Restore the channels and queues first.")
				continue
			if lost:
				r["notes"].append(f"Connector '{name}': {lost} of its queues don't exist here and were left out.")
			old = next((c for c in bot.connectors.connectors.values() if c["guild_id"] == gid and c["key_hash"] == x["key_hash"]), None)
			r["replaced" if old else "added"] += 1
			if not dry_run:
				unmatched = queue_id(x.get("unmatched_queue")) if x.get("unmatched_queue") else 0
				await bot.connectors.restore(gid, x, queues, unmatched if unmatched in queues else 0, old)

	if not dry_run:
		log.info(f"WEBUI| {who} restored a backup ({', '.join(parts)}) made {time.strftime('%Y-%m-%d', time.gmtime(data.get('created_at') or 0))}.")
	return report
