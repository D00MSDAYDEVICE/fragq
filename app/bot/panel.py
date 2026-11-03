# -*- coding: utf-8 -*-
"""
Queue panel: a message with one Join button per queue and a Leave button, kept up to date as
players add and remove. Buttons run the same code as the /add and /remove commands.

Moderators also get Add Player (pick a queue and members, works while paused) and Pause Queue, which
stops Join / !add / ++ for the channel until it is pressed again.

Players' profile pictures are shown as a row of avatars (bot.avatars) at the bottom of the embed,
right above the buttons.

The panel's message id is kept in the channel's cfg_info, so it survives restarts. Presses are routed by
custom_id ("fragq:add:<queue_id>", "fragq:remove", "fragq:pause", "fragq:mod_add", the selects
"fragq:mod_queue" / "fragq:mod_users:<queue_id>", "fragq:steam_prompt:<queues>" and the Steam ID form
"fragq:steam_link:<queues>"), so no view registration is needed.
"""
import io
import time
import traceback
from asyncio import wait_for, shield
from asyncio.exceptions import TimeoutError as aTimeoutError

from nextcord import Embed, Colour, ButtonStyle, Interaction, InteractionType, NotFound, Forbidden, HTTPException
from nextcord import SelectOption, File
from nextcord.ui import View, Button, StringSelect, UserSelect

from core.client import dc
from core.console import log
from core.utils import get_nick, error_embed

import bot
from bot.context.slash.context import SlashContext

PREFIX = "fragq:"
MAX_QUEUES = 20          # 4 rows of 5 join buttons, the 5th row holds Leave and the moderator buttons
PAUSED_COLOUR = 0xf5a524
EDIT_INTERVAL = 2.0      # seconds between edits of one panel (Discord rate limits message edits)

_state = {}  # qc.id -> dict(sig=..., edited=float, repost=bool)


def _bar(n, size, width=12):
	if size <= width:
		return "▰" * n + "▱" * (size - n)
	filled = round(width * n / size)
	return "▰" * filled + "▱" * (width - filled)


def build(qc):
	""" Returns (embed, view) for a queue channel. """
	guild = dc.get_guild(qc.guild_id)
	channel = dc.get_channel(qc.id)
	queues = qc.queues[:MAX_QUEUES]
	paused = qc.paused

	if paused:
		description = "⏸️ **" + qc.gt("Queue paused") + "**: " + qc.gt("joining is disabled for now. Moderators can still add players.")
	else:
		description = qc.gt("Press **Join** to add yourself to a queue, **Leave** to remove yourself from all of them.")
	embed = Embed(
		colour=Colour(PAUSED_COLOUR if paused else 0x1ff2a2),
		title="\U0001F3AE " + qc.gt("Pickup queues"),
		description=description,
	)
	if guild and channel:
		embed.set_author(name=f"{guild.name} · #{channel.name}", icon_url=str(guild.icon.with_size(64)) if guild.icon else None)

	if not queues:
		embed.add_field(name="​", value=qc.gt("No queues on this channel yet."), inline=False)
	for q in queues:
		n, size = len(q.queue), q.cfg.size
		title = f"{q.name} · {n}/{size}" + (" · ⭐ ranked" if q.cfg.ranked else "")
		players = " · ".join(f"`{get_nick(m)}`" for m in q.queue) or "*" + qc.gt("waiting for players") + "*"
		value = f"`{_bar(n, size)}`\n{players}"
		embed.add_field(name=title, value=value[:1024], inline=False)

	matches = [m for m in bot.active_matches if m.qc is qc]
	if matches:
		lines = []
		for m in matches[:5]:
			state = {1: "check-in", 2: "draft", 3: "in game"}.get(m.state, "starting")
			mins = max(0, int((time.time() - m.start_time) // 60))
			lines.append(f"`#{m.id}` **{m.queue.name}** — {state} · {mins} min")
		embed.add_field(name="⚔️ " + qc.gt("Matches in progress"), value="\n".join(lines), inline=False)

	footer = qc.gt("Updates live · or type {add} / {remove}").format(add=f"{qc.cfg.prefix}add", remove=f"{qc.cfg.prefix}remove")
	if qc.cfg.panel_mod_buttons:  # the moderator buttons are icon-only, so say what they do
		footer += "\n" + qc.gt("Moderators: 👤 add player · {icon} {action}").format(
			icon="▶️" if paused else "⏸️", action=qc.gt("resume queue") if paused else qc.gt("pause queue")
		)
	embed.set_footer(text=footer)

	# Presses are answered by on_component(); auto_defer would race it and answer first.
	view = View(timeout=None, auto_defer=False)
	joins = []
	for q in queues:
		closed = paused or len(q.queue) >= q.cfg.size
		joins.append(Button(
			style=ButtonStyle.secondary if closed else ButtonStyle.success,
			label=(qc.gt("Join") + " " + q.name)[:80] if len(queues) > 1 else qc.gt("Join"),
			emoji="➕",
			custom_id=f"{PREFIX}add:{q.id}",
			disabled=closed,
		))
	# Leave and the moderator buttons stay together, after the last Join button if they fit in its row.
	group = [Button(style=ButtonStyle.danger, label=qc.gt("Leave"), emoji="✖️", custom_id=f"{PREFIX}remove")]
	if qc.cfg.panel_mod_buttons:
		# Icon-only: Discord buttons can't show hover tooltips, so the state is in the icon and colour.
		group.append(Button(style=ButtonStyle.secondary, emoji="👤", custom_id=f"{PREFIX}mod_add", disabled=not queues))
		group.append(Button(
			style=ButtonStyle.primary if paused else ButtonStyle.secondary,
			emoji="▶️" if paused else "⏸️",
			custom_id=f"{PREFIX}pause",
		))
	for i, item in enumerate(joins):
		item.row = i // 5
		view.add_item(item)
	used = len(joins) % 5
	row = (len(joins) - 1) // 5 if joins and used and used + len(group) <= 5 else -(-len(joins) // 5)
	for item in group:
		item.row = row
		view.add_item(item)
	return embed, view


def _signature(qc):
	return (
		qc.cfg.prefix, qc.paused, qc.cfg.panel_mod_buttons, bot.avatars.signature(qc),
		tuple((q.id, q.name, q.cfg.size, q.cfg.ranked, tuple(m.id for m in q.queue)) for q in qc.queues),
		tuple((m.id, m.state, int((time.time() - m.start_time) // 60)) for m in bot.active_matches if m.qc is qc),
	)


def message_id(qc):
	return (qc.cfg.cfg_info.get("panel") or {}).get("message_id")


async def _set_message_id(qc, mid):
	info = dict(qc.cfg.cfg_info)
	if mid:
		info["panel"] = dict(message_id=mid)
	else:
		info.pop("panel", None)
	await qc.cfg.set_info(info)


async def post(qc):
	""" Post the panel at the bottom of the channel, replacing an existing one. """
	channel = dc.get_channel(qc.id)
	if channel is None:
		raise bot.Exc.NotFoundError("Discord channel not found.")
	await remove(qc, forget=False)
	sig = _signature(qc)
	embed, view, file = await _render(qc)
	try:
		msg = await channel.send(embed=embed, view=view, file=file)
	except Forbidden:
		raise bot.Exc.PermissionError("The bot can't send messages in this channel.")
	await _set_message_id(qc, msg.id)
	_state[qc.id] = dict(sig=sig, edited=time.time(), repost=False, msg=msg, posted=time.time())
	return msg.id


async def _render(qc):
	""" (embed, view, file): the panel, with the player avatars attached as an image if anyone is queued. """
	embed, view = build(qc)
	try:
		png = await bot.avatars.queue_image(qc)
	except Exception as e:
		log.error(f"Failed to draw queue panel avatars for {qc.id}: {e}\n{traceback.format_exc()}")
		png = None
	if png is None:
		return embed, view, None
	embed.set_image(url="attachment://players.png")
	return embed, view, File(io.BytesIO(png), filename="players.png")


def bump(qc):
	""" A match message was posted: move the panel below it on the next tick (if enabled). """
	if message_id(qc) and qc.cfg.panel_repost:
		_state.setdefault(qc.id, dict(sig=None, edited=0))["repost"] = True


async def remove(qc, forget=True):
	""" Delete the panel message. """
	mid = message_id(qc)
	if mid and (channel := dc.get_channel(qc.id)):
		try:
			await channel.get_partial_message(mid).delete()
		except (NotFound, Forbidden, HTTPException):
			pass
	if forget:
		await _set_message_id(qc, None)
		_state.pop(qc.id, None)


async def refresh(qc, force=False):
	mid = message_id(qc)
	if not mid:
		return
	st = _state.setdefault(qc.id, dict(sig=None, edited=0, repost=False))
	sig = _signature(qc)
	if not force and sig == st["sig"] and not st.get("repost"):
		return
	now = time.time()
	if not force and now - st["edited"] < EDIT_INTERVAL:
		return

	if st.get("repost"):  # keep the panel below the newest match message
		try:
			await post(qc)
		except Exception as e:
			st["repost"] = False
			log.error(f"Failed to re-post queue panel in {qc.id}: {e}")
		return

	channel = dc.get_channel(qc.id)
	if channel is None:
		return
	st["sig"], st["edited"] = sig, now  # set first: a concurrent refresh sees nothing to do
	try:
		# A full Message is needed to swap the avatar image (PartialMessage.edit can't upload files).
		msg = st.get("msg")
		if msg is None or msg.id != mid:
			msg = await channel.fetch_message(mid)
		embed, view, file = await _render(qc)
		kwargs = dict(embed=embed, view=view, attachments=[])
		if file is not None:
			kwargs["file"] = file
		st["msg"] = await msg.edit(**kwargs) or msg
	except NotFound:  # deleted by someone: stop updating it
		log.info(f"Queue panel in #{channel.name} was deleted.")
		await _set_message_id(qc, None)
		_state.pop(qc.id, None)
	except (Forbidden, HTTPException) as e:
		log.error(f"Failed to update queue panel in #{channel.name}: {e}")


def _buried(qc, mid):
	""" Newer messages than the panel in its channel (ephemeral replies don't count). """
	channel = dc.get_channel(qc.id)
	last = getattr(channel, "last_message_id", None)
	return bool(last and last > mid)


async def think(frame_time):
	autorepost = bot.settings.get("panel_autorepost")
	interval = max(1, int(bot.settings.get("panel_autorepost_minutes") or 5)) * 60
	for qc in list(bot.queue_channels.values()):
		if not (mid := message_id(qc)):
			continue
		if autorepost:  # Settings page: move panels buried by chat back to the bottom every few minutes
			st = _state.setdefault(qc.id, dict(sig=None, edited=0, repost=False))
			st.setdefault("posted", frame_time)
			if frame_time - st["posted"] >= interval:
				st["posted"] = frame_time
				if _buried(qc, mid):
					st["repost"] = True
		await refresh(qc)


# ------------------------------------------------------------------ buttons

class PanelContext(SlashContext):
	"""
	Context for panel buttons. The panel already shows who is in the queues, so queue status
	replies only go to the clicking user. Everything else (match messages, check-ins) goes to the
	channel as usual.
	"""

	async def _ack(self):
		if not self.interaction.response.is_done():
			await self.interaction.response.defer()

	async def _private(self, *args, **kwargs):
		if not self.interaction.response.is_done():
			await self.interaction.response.send_message(*args, **kwargs, ephemeral=True)
		else:
			await self.interaction.followup.send(*args, **kwargs, ephemeral=True)

	async def notice(self, content=None, embed=None, **kwargs):
		if embed is None and content == self.qc.topic:
			await self._private(content=content)
			return
		await self._ack()
		await self.interaction.channel.send(content=content, embed=embed)

	async def reply(self, *args, **kwargs):
		await self._private(*args, **kwargs)

	async def reply_dm(self, *args, **kwargs):
		await self._private(*args, **kwargs)

	async def ignore(self, *args, **kwargs):
		await self._private(*args, **kwargs)

	async def error(self, *args, **kwargs):
		await self._private(embed=error_embed(*args, **kwargs))

	async def success(self, *args, **kwargs):
		await self._private(*args, **kwargs)


async def _run(ctx, coro, **kwargs):
	try:
		await coro(ctx, **kwargs)
	except bot.Exc.PubobotException as e:
		await ctx.error(str(e), title=e.__class__.__name__)
	except Exception as e:
		await ctx.error(str(e), title="RuntimeError")
		log.error(f"Error processing panel button {coro.__name__} in {ctx.qc.id}: {e}\n{traceback.format_exc()}")
	await ctx._ack()


# ------------------------------------------------------------------ moderator buttons

async def _toggle_pause(ctx):
	ctx.check_perms(ctx.Perms.MODERATOR)
	qc = ctx.qc
	await qc.set_paused(not qc.paused)
	log.info(f"{get_nick(ctx.author)} {'paused' if qc.paused else 'resumed'} the queues in #{ctx.interaction.channel.name}.")
	await ctx._ack()
	await refresh(qc, force=True)


def _user_picker(qc, q):
	free = q.cfg.size - len(q.queue)
	view = View(timeout=None, auto_defer=False)
	view.add_item(UserSelect(
		custom_id=f"{PREFIX}mod_users:{q.id}",
		placeholder=qc.gt("Select players to add to {queue}").format(queue=q.name)[:150],
		min_values=1, max_values=max(1, min(25, free)),
	))
	text = qc.gt("Add players to **{queue}** ({n}/{size}).").format(queue=q.name, n=len(q.queue), size=q.cfg.size)
	return text, view


async def _mod_add(ctx):
	""" Add Player button: pick the queue (if there are several), then the members. """
	ctx.check_perms(ctx.Perms.MODERATOR)
	queues = ctx.qc.queues[:25]
	if not queues:
		raise bot.Exc.NotFoundError(ctx.qc.gt("No queues on this channel yet."))
	if len(queues) == 1:
		text, view = _user_picker(ctx.qc, queues[0])
	else:
		view = View(timeout=None, auto_defer=False)
		view.add_item(StringSelect(
			custom_id=f"{PREFIX}mod_queue",
			placeholder=ctx.qc.gt("Select a queue"),
			options=[
				SelectOption(label=q.name[:100], value=str(q.id), description=f"{len(q.queue)}/{q.cfg.size}")
				for q in queues
			],
		))
		text = ctx.qc.gt("Which queue should the players be added to?")
	await ctx.interaction.response.send_message(content=text, view=view, ephemeral=True)


def _find_queue(qc, qid):
	q = next((q for q in qc.queues if str(q.id) == str(qid)), None)
	if q is None:
		raise bot.Exc.NotFoundError(qc.gt("This queue no longer exists."))
	return q


async def _mod_queue(ctx):
	""" Queue picked from the Add Player menu: swap the menu for the member picker. """
	ctx.check_perms(ctx.Perms.MODERATOR)
	q = _find_queue(ctx.qc, (ctx.interaction.data.get("values") or [None])[0])
	text, view = _user_picker(ctx.qc, q)
	await ctx.interaction.response.edit_message(content=text, view=view)


async def _mod_users(ctx, qid):
	""" Members picked: add them like !add_player does. Works while the channel is paused. """
	ctx.check_perms(ctx.Perms.MODERATOR)
	qc, interaction = ctx.qc, ctx.interaction
	q = _find_queue(qc, qid)
	await interaction.response.defer()

	members = []
	for uid in interaction.data.get("values") or []:
		member = interaction.guild.get_member(int(uid))
		if member is None:
			try:
				member = await interaction.guild.fetch_member(int(uid))
			except (NotFound, HTTPException):
				member = None
		if member is not None:
			members.append(member)

	added, skipped = [], []
	for i, m in enumerate(members):
		if m.bot:
			skipped.append((m, qc.gt("bot")))
			continue
		if any(m in match.players for match in bot.active_matches):
			skipped.append((m, qc.gt("in a match")))
			continue
		resp = await q.add_member(ctx, m)
		if resp == bot.Qr.Success:
			added.append(m)
			await qc.update_expire(m)
		elif resp == bot.Qr.QueueStarted:
			added.append(m)
			skipped.extend((r, qc.gt("queue started")) for r in members[i + 1:])
			break
		else:
			skipped.append((m, {
				bot.Qr.Duplicate: qc.gt("already in queue"),
				bot.Qr.QueueFull: qc.gt("queue full"),
				bot.Qr.NotAllowed: qc.gt("not allowed by queue roles"),
			}.get(resp, resp.__name__)))

	lines = []
	if added:
		lines.append("✅ " + qc.gt("Added {players} to **{queue}**.").format(
			players=", ".join(f"**{get_nick(m)}**" for m in added), queue=q.name
		))
		log.info(f"{get_nick(ctx.author)} added {', '.join(get_nick(m) for m in added)} to {q.name} from the queue panel.")
	if skipped:
		lines.append("⚠️ " + qc.gt("Not added: {players}.").format(
			players=", ".join(f"{get_nick(m)} ({why})" for m, why in skipped)
		))
	await interaction.edit_original_message(content="\n".join(lines) or qc.gt("Action had no effect."), view=None)


async def on_component(interaction: Interaction) -> bool:
	""" Handle a FragQ button press. Returns False if the interaction isn't ours. """
	custom_id = (interaction.data or {}).get("custom_id", "")
	if not custom_id.startswith(PREFIX):
		return False

	if not bot.bot_ready:
		await interaction.response.send_message(embed=error_embed("Bot is connecting, try again in a moment."), ephemeral=True)
		return True
	if custom_id.startswith(bot.connectors.BUTTON):  # confirmation of a !link typed on a game server (a DM)
		await bot.connectors.on_button(interaction)
		return True
	qc = bot.queue_channels.get(interaction.channel_id)
	if qc is None:
		await interaction.response.send_message(embed=error_embed("The bot is not enabled on this channel."), ephemeral=True)
		return True

	action, _, arg = custom_id[len(PREFIX):].partition(":")
	ctx = PanelContext(qc, interaction)
	log.command(f"{interaction.guild.name} | #{interaction.channel.name} | {get_nick(interaction.user)}: [button] {action} {arg}")

	if action == "add":
		q = next((q for q in qc.queues if str(q.id) == arg), None)
		if q is None:
			await ctx.error("This queue no longer exists.", title=None)
			await refresh(qc, force=True)
			return True
		task = _run(ctx, bot.commands.add, queues=q.name)
	elif action == "remove":
		task = _run(ctx, bot.commands.remove)
	elif action == "pause":
		task = _run(ctx, _toggle_pause)
	elif action == "mod_add":
		task = _run(ctx, _mod_add)
	elif action == "mod_queue":
		task = _run(ctx, _mod_queue)
	elif action == "mod_users":
		task = _run(ctx, _mod_users, qid=arg)
	elif action == "steam_prompt":
		await interaction.response.send_modal(bot.steam.link_modal(arg or None))
		return True
	else:
		await ctx.error("Unknown button.", title=None)
		return True

	# Interactions must be answered within 3 seconds.
	try:
		await wait_for(shield(task), timeout=2.5)
	except (TimeoutError, aTimeoutError):
		await ctx._ack()
	await refresh(qc)
	return True


async def on_modal(interaction: Interaction) -> bool:
	""" Handle a FragQ pop-up form. Returns False if the interaction isn't ours. """
	custom_id = (interaction.data or {}).get("custom_id", "")
	if not custom_id.startswith(f"{PREFIX}steam_link:"):
		return False
	ok, queues = await bot.steam.on_modal(interaction)
	qc = bot.queue_channels.get(interaction.channel_id)
	if ok and qc is not None:  # finish the join the player started
		await _run(PanelContext(qc, interaction), bot.commands.add, queues=queues)
		await refresh(qc)
	return True


@dc.event
async def on_interaction(interaction: Interaction):
	# Registering this event replaces nextcord's default handler, so slash commands are passed on.
	if interaction.type == InteractionType.component and await on_component(interaction):
		return
	if interaction.type == InteractionType.modal_submit and await on_modal(interaction):
		return
	await dc.process_application_commands(interaction)


@dc.event
async def on_think(frame_time):
	await think(frame_time)
