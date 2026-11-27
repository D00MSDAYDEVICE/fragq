#!/usr/bin/env python3
"""
FragQ demo / development server.

Runs the real bot modules and web interface against an in-memory fake Discord server, so the
web UI can be developed and tested without a bot token or Discord connection. Needs a MySQL or
MariaDB database (use a throwaway one, demo data is written to it):

    docker run -d --name fragq-dev-db -p 3307:3306 -e MARIADB_DATABASE=fragq \
        -e MARIADB_USER=fragq -e MARIADB_PASSWORD=fragq -e MARIADB_ROOT_PASSWORD=root mariadb:11.4
    cd app && DB_URI=mysql://fragq:fragq@127.0.0.1:3307/fragq python dev/demo.py

Then open http://127.0.0.1:8000/dev-login (logs you in as the bot owner).
"""
import asyncio
import os
import sys
import base64
import time
from types import SimpleNamespace

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.dirname(HERE)
os.chdir(APP)
sys.path.insert(0, APP)

os.environ.setdefault("DATA_DIR", os.path.join(APP, ".dev"))
os.environ.setdefault("DISCORD_BOT_TOKEN", "demo")
os.environ.setdefault("DISCORD_CLIENT_ID", "100000000000000001")
os.environ.setdefault("DISCORD_OWNER_ID", "200000000000000001")
os.environ.setdefault("WEB_HOST", "127.0.0.1")
os.environ.setdefault("LOG_LEVEL", "INFO")

loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)

from nextcord import ChannelType, Embed, InteractionType, NotFound, Forbidden, HTTPException, ScheduledEventStatus  # noqa: E402
from core import config, console, database, locales, cfg_factory  # noqa: E402,F401
from core.client import dc  # noqa: E402

loop.run_until_complete(database.db.connect())

import bot  # noqa: E402
from webui import webserver, auth  # noqa: E402
from aiohttp import web  # noqa: E402

OWNER = config.cfg.DC_OWNER_ID


# ------------------------------------------------------------------ fake discord objects

class Asset:
	def __init__(self, url):
		self.url = url

	def with_size(self, size):
		return self

	def __str__(self):
		return self.url


class Color:
	def __init__(self, value):
		self.value = value


class Perms:
	def __init__(self, administrator=False, send_messages=True):
		self.administrator = administrator
		self.send_messages = send_messages
		self.view_channel = self.connect = self.move_members = True
		self.embed_links = self.read_message_history = self.add_reactions = self.speak = True
		self.manage_channels = self.manage_roles = self.manage_events = administrator
		self.value = (1 << 44) if administrator else 0   # Create Events

	@property
	def read_messages(self):   # nextcord's old name for View Channels (PermissionOverwrite lists both)
		return self.view_channel

	@property
	def manage_permissions(self):
		return self.manage_roles


def _forbidden():
	return Forbidden(SimpleNamespace(status=403, reason="Forbidden"), {"code": 50013, "message": "Missing Permissions"})


def _no_access():
	""" Discord's answer in a channel the bot can't see. """
	return Forbidden(SimpleNamespace(status=403, reason="Forbidden"), {"code": 50001, "message": "Missing Access"})


def _check_overwrites(guild, overwrites):
	""" Like Discord: a bot can't allow or deny in a channel a permission it doesn't have itself (50013). """
	p = guild.me.guild_permissions
	if p.administrator:
		return
	for ow in (overwrites or {}).values():
		for name, value in ow:
			if value is not None and not getattr(p, name, False):
				console.log.info(f"DEMO| refused: the bot's overwrites hand out {name}, which it doesn't have")
				raise _forbidden()


class FakeScheduledEvent:
	""" A Discord scheduled event, with Discord's status rules. """

	def __init__(self, guild, name, entity_type, start_time, channel=None, metadata=None, end_time=None, description=None):
		self.guild, self.id, self.name, self.entity_type = guild, next(_new_ids), name, entity_type
		self.start_time, self.end_time, self.description, self.channel = start_time, end_time, description, channel
		self.location = getattr(metadata, "location", None)
		self.status = ScheduledEventStatus.scheduled

	async def edit(self, status=None, type=None, metadata=None, reason=None, **kwargs):
		if status is not None:
			ok = {ScheduledEventStatus.scheduled: (ScheduledEventStatus.active, ScheduledEventStatus.canceled),
				  ScheduledEventStatus.active: (ScheduledEventStatus.completed,)}.get(self.status, ())
			if status not in ok:
				raise HTTPException(SimpleNamespace(status=400, reason="Bad Request"), f"Can't go from {self.status.name} to {status.name}")
			self.status = status
		if type is not None:
			self.entity_type = type
		if metadata is not None:
			self.location = metadata.location
		for k, v in kwargs.items():
			setattr(self, k, v)
		console.log.info(f"DEMO| scheduled event '{self.name}' edited ({self.status.name})")
		return self

	async def delete(self):
		self.guild.scheduled_events.pop(self.id, None)
		console.log.info(f"DEMO| scheduled event '{self.name}' deleted")

	def to_dict(self):
		return dict(id=str(self.id), name=self.name, status=self.status.name, type=self.entity_type.name,
					channel=str(self.channel.id) if self.channel else None, location=self.location,
					start=int(self.start_time.timestamp()), end=int(self.end_time.timestamp()) if self.end_time else None,
					description=self.description, image=len(self.image) if isinstance(getattr(self, "image", None), bytes) else 0)


class Role:
	def __init__(self, guild, rid, name, color=0, managed=False):
		self.guild, self.id, self.name, self.color, self.managed = guild, rid, name, Color(color), managed
		self.mentionable = True
		self.permissions = Perms(administrator=name.startswith("ADMIN"))

	def is_default(self):
		return self.id == self.guild.id

	@property
	def mention(self):
		return f"<@&{self.id}>"


class Category:
	type = ChannelType.category

	def __init__(self, name, position, cid=None, guild=None):
		self.name, self.position, self.id, self.guild = name, position, cid, guild
		self.overwrites = {}

	async def delete(self, reason=None):
		if self in self.guild.channels:
			self.guild.channels.remove(self)


# Channels created while the demo runs (QueueGen): new ids on every start, like Discord's, so a channel never
# inherits the queues of one from an earlier run (the database outlives the fake server).
_new_ids = iter(range(310000000000000000 + int(time.time()) * 1000, 320000000000000000))


class Editable:
	""" Channels FragQ can rename, re-permission and delete (QueueGen). """

	async def edit(self, name=None, topic=None, overwrites=None, **kwargs):
		if overwrites is not None:
			_check_overwrites(self.guild, overwrites)
		if name is not None:
			self.name = name
		if topic is not None:
			self.topic = topic
		if overwrites is not None:
			self.overwrites = dict(overwrites)

	async def delete(self, reason=None):
		console.log.info(f"DEMO| channel #{self.name} deleted ({reason})")
		if self in self.guild.channels:
			self.guild.channels.remove(self)


_msg_ids = iter(range(500000000000000000, 600000000000000000))
KEEP = object()


def _render(content=None, embed=None, view=None, author="FragQ", ephemeral_to=None):
	return dict(
		content=content,
		embeds=[embed.to_dict()] if embed is not None else [],
		components=view.to_components() if view is not None else [],
		author=author, ephemeral_to=ephemeral_to, at=time.time(),
	)


def _attachment(file):
	""" nextcord.File -> {filename: data URL}, so the preview can show attachment:// images. """
	if file is None:
		return {}
	return {file.filename: "data:image/png;base64," + base64.b64encode(file.fp.read()).decode()}


def _not_found():
	return NotFound(SimpleNamespace(status=404, reason="Not Found"), "Unknown Message")


class Message:
	""" Records what the bot posts, for the /dev/discord preview. """

	def __init__(self, channel, data):
		self.channel, self.id, self.data = channel, next(_msg_ids), data

	@property
	def embeds(self):
		return [Embed.from_dict(e) for e in self.data.get("embeds") or []]

	async def edit(self, content=KEEP, embed=None, view=None, file=None, attachments=None, **kwargs):
		if getattr(self.channel, "no_access", False):
			raise _no_access()
		if self not in self.channel.messages:  # like Discord: editing a deleted / unknown message fails
			raise _not_found()
		eph = self.data.get("ephemeral_to")
		files = {} if attachments is not None else self.data.get("attachments", {})
		# Like nextcord: content=None removes the text, leaving it out keeps it.
		self.data.update(_render(self.data["content"] if content is KEEP else content, embed, view, ephemeral_to=eph))
		self.data["attachments"] = dict(files, **_attachment(file))
		self.data["edited"] = True
		return self

	async def delete(self):
		if self in self.channel.messages:
			self.channel.messages.remove(self)

	async def add_reaction(self, *args):
		pass

	async def clear_reactions(self):
		pass


class TextChannel(Editable):
	type = ChannelType.text

	def __init__(self, guild, cid, name, category=None, position=0):
		self.guild, self.id, self.name, self.category, self.position = guild, cid, name, category, position
		self.messages = []
		self.topic, self.overwrites = None, {}
		self.no_access = False  # /dev/channel-access: the bot can't see the channel (Discord's 50001)

	@property
	def mention(self):
		return f"<#{self.id}>"

	def permissions_for(self, member):
		return Perms(administrator=getattr(member, "_admin", False))

	def get_partial_message(self, mid):
		return next((m for m in self.messages if m.id == mid), None) or Message(self, {})

	def get_thread(self, tid):
		return None

	@property
	def last_message_id(self):
		""" Like Discord: the newest message anyone can see (ephemeral replies don't count). """
		return max((m.id for m in self.messages if not m.data.get("ephemeral_to")), default=None)

	async def fetch_message(self, mid):
		if self.no_access:
			raise _no_access()
		if (msg := next((m for m in self.messages if m.id == mid), None)) is None:
			raise _not_found()
		return msg

	async def send(self, content=None, embed=None, view=None, file=None, **kwargs):
		if self.no_access:
			raise _no_access()
		msg = Message(self, _render(content, embed, view))
		msg.data["attachments"] = _attachment(file)
		self.messages.append(msg)
		del self.messages[:-40]
		return msg


class VoiceChannel(Editable):
	type = ChannelType.voice

	def __init__(self, guild, cid, name, category=None, position=0):
		self.guild, self.id, self.name, self.category, self.position = guild, cid, name, category, position
		self.topic, self.overwrites = None, {}

	@property
	def members(self):
		return [m for m in self.guild.members if m.voice and m.voice.channel is self]

	def permissions_for(self, member):
		return Perms(administrator=getattr(member, "_admin", False))


class DMChannel:
	""" A member's direct messages with the bot (FakeInteraction needs .guild, which DMs don't have). """
	type = ChannelType.private

	def __init__(self, uid):
		self.id, self.guild, self.messages, self.name = uid + 1, None, [], "dm"

	async def send(self, content=None, embed=None, view=None, **kwargs):
		msg = Message(self, _render(content, embed, view))
		self.messages.append(msg)
		return msg


DMS = {}  # user id -> DMChannel


class Member:
	def __init__(self, guild, uid, name, roles=(), admin=False):
		self.guild, self.id, self.name, self.nick = guild, uid, name, None
		self.roles = list(roles)
		self._admin = admin
		self.guild_permissions = Perms(administrator=admin)
		self.display_avatar = Asset(f"https://cdn.discordapp.com/embed/avatars/{uid % 6}.png")
		self.bot = False
		self.raw_status = "online"
		self.activity = None
		self.discriminator = "0"
		self.voice = None   # SimpleNamespace(channel=VoiceChannel) while in voice

	async def move_to(self, channel, reason=None):
		if self.voice is None:
			raise NotFound(SimpleNamespace(status=400, reason="Bad Request"), "Target user is not connected to voice.")
		console.log.info(f"DEMO| voice: {self.name} moved to {channel.name} ({reason})")
		self.voice = SimpleNamespace(channel=channel)

	@property
	def display_name(self):
		return self.nick or self.name

	@property
	def mention(self):
		return f"<@{self.id}>"

	def __eq__(self, other):
		return getattr(other, "id", None) == self.id

	def __hash__(self):
		return self.id

	async def send(self, content=None, embed=None, view=None, **kwargs):
		text = content or (embed.title if embed else "")
		console.log.info(f"DEMO| direct message to {self.name}: {text}")
		return await DMS.setdefault(self.id, DMChannel(self.id)).send(content=content, embed=embed, view=view)


class Guild:
	def __init__(self, gid, name, owner_id):
		self.id, self.name, self.owner_id = gid, name, owner_id
		self.icon = None
		self.unavailable = False
		self.roles, self.channels, self.members, self.emojis = [], [], [], []
		self.roles.append(Role(self, gid, "@everyone"))
		self.me = None
		self.scheduled_events = {}

	@property
	def text_channels(self):
		return [c for c in self.channels if isinstance(c, TextChannel)]

	@property
	def voice_channels(self):
		return [c for c in self.channels if isinstance(c, VoiceChannel)]

	@property
	def member_count(self):
		return len(self.members)

	@property
	def default_role(self):
		return self.roles[0]

	async def create_category(self, name, reason=None, **kwargs):
		c = Category(name, 9, next(_new_ids), self)
		self.channels.append(c)
		console.log.info(f"DEMO| category {name} created ({reason})")
		return c

	def get_scheduled_event(self, eid):
		return self.scheduled_events.get(eid)

	async def fetch_scheduled_event(self, eid):
		if eid not in self.scheduled_events:
			raise NotFound(SimpleNamespace(status=404, reason="Not Found"), "Unknown Guild Scheduled Event")
		return self.scheduled_events[eid]

	async def create_scheduled_event(self, name, entity_type, start_time, reason=None, privacy_level=None, image=None, **kwargs):
		p = self.me.guild_permissions
		if not (p.administrator or p.manage_events or p.value & (1 << 44)):
			raise _forbidden()
		if start_time.timestamp() < time.time():
			raise HTTPException(SimpleNamespace(status=400, reason="Bad Request"), "Cannot schedule event in the past")
		se = FakeScheduledEvent(self, name, entity_type, start_time, **kwargs)
		se.image = image
		self.scheduled_events[se.id] = se
		console.log.info(f"DEMO| scheduled event '{name}' created ({entity_type.name}, {reason})")
		return se

	async def create_text_channel(self, name, category=None, overwrites=None, topic=None, reason=None, **kwargs):
		_check_overwrites(self, overwrites)
		c = TextChannel(self, next(_new_ids), name, category, 50 + len(self.channels))
		c.topic, c.overwrites = topic, dict(overwrites or {})
		self.channels.append(c)
		console.log.info(f"DEMO| text channel #{name} created ({reason})")
		return c

	async def create_voice_channel(self, name, category=None, overwrites=None, reason=None, **kwargs):
		_check_overwrites(self, overwrites)
		c = VoiceChannel(self, next(_new_ids), name, category, 50 + len(self.channels))
		c.overwrites = dict(overwrites or {})
		self.channels.append(c)
		console.log.info(f"DEMO| voice channel {name} created ({reason})")
		return c

	def get_role(self, rid):
		return next((r for r in self.roles if r.id == rid), None)

	def get_channel(self, cid):
		return next((c for c in self.channels if c.id == cid), None)

	def get_member(self, uid):
		return next((m for m in self.members if m.id == uid), None)

	async def fetch_member(self, uid):
		return self.get_member(uid)


class BotUser:
	id = 100000000000000001
	name = "FragQ"
	discriminator = "0"
	display_avatar = Asset("https://cdn.discordapp.com/embed/avatars/1.png")
	avatar = display_avatar


GUILDS = []


def build_world():
	ids = iter(range(300000000000000000, 300000000000010000))

	td = Guild(next(ids), "Thunderdome Quake", OWNER)
	for name, color in [("ADMIN / Organizers", 0xe74c3c), ("Moderator", 0x3498db), ("PUG-Alerts", 0xf1c40f),
						("Div 1 Captain", 0x9b59b6), ("Vetted", 0x2ecc71), ("Shitter", 0x95a5a6), ("Quake Player", 0)]:
		td.roles.append(Role(td, next(ids), name, color))
	td.roles.append(Role(td, next(ids), "FragQ", 0x1ff2a2, managed=True))
	pugs = Category("Pickups", 1)
	info = Category("Info", 0)
	for i, (name, cat) in enumerate([
		("🔵│announcements", info), ("🔵│rules", info),
		("🔴│red-division", pugs), ("2v2-pug", pugs), ("🟡│1v1-challenge", pugs), ("🟡│open-pug", pugs),
		("4v4-pug", pugs), ("3v3-pug", pugs), ("🟣│chud-pugs", pugs), ("🟡│ctf-pug", pugs), ("general", None),
	]):
		td.channels.append(TextChannel(td, next(ids), name, cat, i))
	voice = Category("Voice", 2)
	for i, name in enumerate(["🔊 Pickup Lobby", "🔴 Red Team", "🔵 Blue Team", "General Voice"]):
		td.channels.append(VoiceChannel(td, next(ids), name, voice, 20 + i))
	td.members.append(Member(td, OWNER, "therealdoomsday", admin=True))
	for n in ["sk1nner", "st01c", "namastex", "trex", "bentley", "torrin", "flood", "cows", "monster", "doc",
			  "rapha", "sotrix", "tensa", "nino", "brut", "koya"]:
		td.members.append(Member(td, next(ids), n, roles=[td.roles[-2]]))
	td.members[1].roles.append(next(r for r in td.roles if r.name == "Moderator"))  # sk1nner moderates
	td.me = Member(td, BotUser.id, "FragQ", admin=True)

	qfn = Guild(next(ids), "Quake For Newbies", 999)
	qfn.channels.append(TextChannel(qfn, next(ids), "pickups"))
	qfn.members.append(Member(qfn, OWNER, "therealdoomsday", admin=True))
	qfn.me = Member(qfn, BotUser.id, "FragQ")

	GUILDS.extend([td, qfn])


def get_guild(gid):
	return next((g for g in GUILDS if g.id == gid), None)


def get_channel(cid):
	for g in GUILDS:
		if (c := g.get_channel(cid)):
			return c


type(dc).guilds = property(lambda self: GUILDS)
type(dc).user = property(lambda self: BotUser)
type(dc).latency = property(lambda self: 0.042)
dc.get_guild = get_guild
dc.get_channel = get_channel
dc.get_user = lambda uid: next((m for g in GUILDS for m in g.members if m.id == uid), None)


async def seed():
	td = GUILDS[0]
	by_name = {c.name: c for c in td.channels}
	wanted = {
		"🔴│red-division": [("Red-Division", 8)],
		"2v2-pug": [("2v2-pickup", 4)],
		"🟡│1v1-challenge": [("1v1", 2)],
		"🟡│open-pug": [("Open-PUG", 8)],
		"4v4-pug": [("4v4-pickup", 8)],
		"🟡│ctf-pug": [("CTF", 8)],
	}
	known = await bot.QueueChannel.cfg_factory.p_keys()
	for cname, queues in wanted.items():
		ch = by_name[cname]
		qc = await bot.QueueChannel.create(ch)
		bot.queue_channels[ch.id] = qc
		await qc.update_info(ch)
		if not qc.cfg.moderator_role:
			await qc.cfg.update({"moderator_role": str(next(r for r in td.roles if r.name == "Moderator").id)})
		if ch.id in known:
			continue
		for qname, size in queues:
			cfg = await bot.PickupQueue.cfg_factory.spawn(td, f_key=qc.id)
			await cfg.update({"name": qname, "size": str(size)})
			qc.queues.append(bot.PickupQueue(qc, cfg))

	# A few players in queues so the live views have something to show.
	players = [m for m in td.members if m.id != OWNER]
	red = bot.queue_channels[by_name["🔴│red-division"].id]
	if red.queues:
		red.queues[0].queue = players[:5]
		bot.active_queues.append(red.queues[0])
	duel = bot.queue_channels[by_name["🟡│1v1-challenge"].id]
	if duel.queues:
		duel.queues[0].queue = players[5:6]
		bot.active_queues.append(duel.queues[0])

	# Leaderboard rows
	import random
	rnd = random.Random(7)
	rows = []
	for m in players:
		w, l, d = rnd.randint(3, 40), rnd.randint(3, 40), rnd.randint(0, 3)
		rows.append(dict(channel_id=red.id, user_id=m.id, nick=m.name, is_hidden=0, rating=rnd.randint(1100, 2100),
						 deviation=rnd.randint(75, 200), wins=w, losses=l, draws=d, streak=rnd.randint(-4, 5),
						 last_ranked_match_at=int(time.time()) - rnd.randint(3600, 40 * 86400)))
	await database.db.insert_many("qc_players", rows, on_dublicate="replace")

	maps = ["Campgrounds", "Trinity", "Asylum", "Strain", "Hardwire", "Bloodrun"]
	if not await database.db.select(["match_id"], "qc_matches", where={"channel_id": red.id}, limit=1):
		now = int(time.time())
		for i in range(1, 13):
			mid = 9000 + i
			await database.db.insert("qc_matches", dict(
				match_id=mid, channel_id=red.id, queue_id=red.queues[0].id if red.queues else 0, queue_name="Red-Division",
				at=now - i * 5400, alpha_name="Alpha", beta_name="Beta", ranked=1, winner=rnd.choice([0, 1, None]),
				alpha_score=None, beta_score=None, maps=rnd.choice(maps)))
			team = rnd.sample(players, 8)
			await database.db.insert_many("qc_player_matches", [
				dict(match_id=mid, channel_id=red.id, user_id=p.id, nick=p.name, team=0 if k < 4 else 1)
				for k, p in enumerate(team)])


# ------------------------------------------------------------------ fake interactions / chat (for /dev/discord)

class FakeResponse:
	def __init__(self, inter):
		self.inter, self._done = inter, False

	def is_done(self):
		return self._done

	async def send_message(self, content=None, embed=None, ephemeral=False, view=None, **kwargs):
		self._done = True
		await self.inter.record(content, embed, view, ephemeral)

	async def defer(self, *args, **kwargs):
		self._done = True

	async def edit_message(self, content=KEEP, embed=None, view=None, **kwargs):
		self._done = True
		await self.inter.message.edit(content=content, embed=embed, view=view)

	async def send_modal(self, modal):
		# Discord shows a pop-up form; the preview shows it as a private message with the form fields.
		self._done = True
		msg = Message(self.inter.channel, _render(ephemeral_to=self.inter.user.name))
		msg.data.update(modal=modal.to_dict(), reply_to=self.inter.user.name)
		self.inter.channel.messages.append(msg)


class FakeFollowup:
	def __init__(self, inter):
		self.inter = inter

	async def send(self, content=None, embed=None, ephemeral=False, view=None, **kwargs):
		await self.inter.record(content, embed, view, ephemeral)


class FakeInteraction:
	type = InteractionType.component

	def __init__(self, channel, user, custom_id, message=None, values=None):
		self.channel, self.channel_id, self.user, self.guild = channel, channel.id, user, channel.guild
		self.data = dict(custom_id=custom_id)
		if values is not None:
			self.data["values"] = values
		self.message = message
		self.id = int((time.time() * 1000 - 1420070400000)) << 22
		self.response, self.followup = FakeResponse(self), FakeFollowup(self)

	async def edit_original_message(self, content=KEEP, embed=None, view=None, **kwargs):
		await self.message.edit(content=content, embed=embed, view=view)

	async def record(self, content, embed, view, ephemeral):
		msg = Message(self.channel, _render(content, embed, view, ephemeral_to=self.user.name if ephemeral else None))
		msg.data["reply_to"] = self.user.name
		self.channel.messages.append(msg)


class FakeChatMessage:
	def __init__(self, channel, author, content):
		self.channel, self.author, self.content, self.guild = channel, author, content, channel.guild
		self.thread, self.id = None, next(_msg_ids)
		self.mentions, self.role_mentions, self.channel_mentions = [], [], []

	async def reply(self, content=None, embed=None, **kwargs):
		msg = await self.channel.send(content=content, embed=embed)
		msg.data["reply_to"] = self.author.name
		return msg


def _channel_and_user(body):
	channel = get_channel(int(body["channel_id"]))
	user = channel.guild.get_member(int(body["user_id"])) if channel else None
	if channel is None or user is None:
		raise web.HTTPBadRequest(text="unknown channel/user")
	return channel, user


async def dev_discord(request):
	return web.FileResponse(os.path.join(HERE, "discord.html"))


async def dev_state(request):
	g = GUILDS[0]
	members = {str(m.id): m.name for m in g.members}
	members[str(BotUser.id)] = BotUser.name
	return web.json_response(dict(
		channels=[dict(id=str(c.id), name=c.name) for c in g.text_channels if c.id in bot.queue_channels],
		members=[dict(id=str(m.id), name=m.name) for m in g.members],
		names=members,
		voice={str(c.id): dict(name=c.name, members=[str(m.id) for m in c.members]) for c in g.voice_channels},
		messages={str(c.id): [dict(m.data, id=str(m.id)) for m in c.messages] for c in g.text_channels},
		scheduled_events=[se.to_dict() for se in g.scheduled_events.values()],
		text_channels=[dict(id=str(c.id), name=c.name) for c in g.text_channels],
	))


async def dev_checkmatch_choices(request):
	""" What /checkmatch's match option suggests in a channel: ?channel_id=&typed= """
	qc = bot.queue_channels.get(int(request.query.get("channel_id", 0)))
	return web.json_response(dict(choices=bot.live.choices(qc, request.query.get("typed", "")) if qc else []))


async def dev_bot_perms(request):
	"""
	The bot's server permissions on the first server: {"admin": true} (the default), or {"admin": false, "deny": [...]}
	for a role with the invite's permissions minus those listed (e.g. ["speak", "create_events"]).
	"""
	body = await request.json()
	g = GUILDS[0]
	p = Perms(administrator=bool(body.get("admin", True)))
	if not p.administrator:
		p.manage_channels = p.manage_roles = True
		p.value = 1 << 44
		for name in body.get("deny") or []:
			if name == "create_events":
				p.value = 0
			else:
				setattr(p, name, False)
	g.me.guild_permissions = p
	return web.json_response(dict(ok=True))


async def dev_channel_access(request):
	""" {"channel_id": ..., "access": false}: the bot loses (or gets back) access to a text channel, as when its View Channel is removed. """
	body = await request.json()
	channel = next(c for g in GUILDS for c in g.text_channels if c.id == int(body["channel_id"]))
	channel.no_access = not body.get("access", True)
	return web.json_response(dict(ok=True))


async def dev_press(request):
	body = await request.json()
	channel, user = _channel_and_user(body)
	message = next((m for m in channel.messages if str(m.id) == str(body.get("message_id"))), None)
	await bot.panel.on_component(FakeInteraction(channel, user, body["custom_id"], message, body.get("values")))
	return web.json_response(dict(ok=True))


async def dev_modal(request):
	""" Submit a pop-up form shown by send_modal. """
	body = await request.json()
	channel, user = _channel_and_user(body)
	form = next((m for m in channel.messages if str(m.id) == str(body.get("message_id"))), None)
	if form is not None:
		channel.messages.remove(form)
	inter = FakeInteraction(channel, user, body["custom_id"])
	inter.type = InteractionType.modal_submit
	inter.data["components"] = [
		dict(type=1, components=[dict(type=4, custom_id=k, value=v)]) for k, v in (body.get("values") or {}).items()
	]
	await bot.panel.on_modal(inter)
	return web.json_response(dict(ok=True))


async def dev_dms(request):
	""" Direct messages the bot sent to a member: ?user_id= """
	ch = DMS.get(int(request.query.get("user_id", 0)))
	return web.json_response(dict(messages=[dict(m.data, id=str(m.id)) for m in (ch.messages if ch else [])]))


async def dev_dm_press(request):
	""" Press a button in a direct message: {user_id, message_id, custom_id} """
	body = await request.json()
	uid = int(body["user_id"])
	ch = DMS.get(uid)
	message = next((m for m in (ch.messages if ch else []) if str(m.id) == str(body.get("message_id"))), None)
	user = dc.get_user(uid)
	if message is None or user is None:
		raise web.HTTPBadRequest(text="unknown DM message/user")
	inter = FakeInteraction(SimpleNamespace(id=ch.id, guild=None, messages=ch.messages), user, body["custom_id"], message)
	await bot.panel.on_component(inter)
	return web.json_response(dict(ok=True))


async def dev_voice(request):
	""" Put a member in a voice channel, or out of voice: {user_id, channel_id or null} """
	body = await request.json()
	member = dc.get_user(int(body["user_id"]))
	channel = get_channel(int(body["channel_id"])) if body.get("channel_id") else None
	if member is None or (body.get("channel_id") and not isinstance(channel, VoiceChannel)):
		raise web.HTTPBadRequest(text="unknown member/voice channel")
	for m in (x for g in GUILDS for x in g.members if x.id == member.id):
		m.voice = SimpleNamespace(channel=channel) if channel else None
	return web.json_response(dict(ok=True))


async def dev_say(request):
	body = await request.json()
	channel, user = _channel_and_user(body)
	msg = Message(channel, _render(body["text"], author=user.name))
	channel.messages.append(msg)
	await dc.on_message(FakeChatMessage(channel, user, body["text"]))
	return web.json_response(dict(ok=True))


async def dev_login(request):
	""" Signs in as the bot owner, or as any fake member with ?as=<name> (to try limited access). """
	who = request.query.get("as")
	member = next((m for m in GUILDS[0].members if m.name == who), None) if who else None
	uid, name = (member.id, member.name) if member else (OWNER, "therealdoomsday")
	payload = dict(id=str(uid), name=name, username=name, avatar=None, exp=int(time.time() + 86400))
	resp = web.HTTPFound("/")
	resp.set_cookie(auth.COOKIE, auth.sign(payload), httponly=True, samesite="Lax", path="/")
	return resp


async def main():
	build_world()
	await seed()
	bot.bot_ready = True
	app = webserver.make_app()
	app.router.add_get("/dev-login", dev_login)
	app.router.add_get("/dev/discord", dev_discord)
	app.router.add_get("/dev/state", dev_state)
	app.router.add_post("/dev/press", dev_press)
	app.router.add_post("/dev/modal", dev_modal)
	app.router.add_post("/dev/say", dev_say)
	app.router.add_post("/dev/voice", dev_voice)
	app.router.add_post("/dev/bot-perms", dev_bot_perms)
	app.router.add_post("/dev/channel-access", dev_channel_access)
	app.router.add_get("/dev/checkmatch-choices", dev_checkmatch_choices)
	app.router.add_get("/dev/dms", dev_dms)
	app.router.add_post("/dev/dm-press", dev_dm_press)
	runner = web.AppRunner(app, access_log=None)
	await runner.setup()
	await web.TCPSite(runner, config.cfg.WS_HOST, config.cfg.WS_PORT).start()
	console.log.info(f"Demo running: http://{config.cfg.WS_HOST}:{config.cfg.WS_PORT}/dev-login")
	console.log.info(f"Fake Discord channel view: http://{config.cfg.WS_HOST}:{config.cfg.WS_PORT}/dev/discord")
	for task in dc.events['on_init']:
		await task()
	while True:  # same background loop as FragQ.py: matches, expiry, queue panels
		for task in dc.events['on_think']:
			try:
				await task(time.time())
			except Exception as e:
				console.log.error(f"think: {e!r}")
		await asyncio.sleep(1)

try:
	loop.run_until_complete(main())
except KeyboardInterrupt:
	pass
