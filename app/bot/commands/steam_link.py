__all__ = ['steam', 'slipgate']

from nextcord import Member, Embed, Colour

from core.utils import get_nick

import bot


async def steam(ctx, steam: str = None):
	""" Link the author's Steam account (changes wait for a moderator's approval), or show the linked one """
	if not steam:
		row = bot.steam.get_link(ctx.author.id)
		if row:
			text = ctx.qc.gt("Your Steam account: {steam}.").format(steam=bot.steam.describe(row))
		else:
			text = ctx.qc.gt("No Steam account linked. Use `{cmd} <SteamID64 or profile link>`.").format(
				cmd=f"{ctx.qc.cfg.prefix}steam"
			)
		if req := bot.steam.requests.get(ctx.author.id):
			text += "\n" + ctx.qc.gt("Waiting for a moderator's approval: change to {steam}.").format(steam=bot.steam.describe(req))
		await ctx.reply(text)
		return
	status, row = await bot.steam.link(ctx.author, steam)
	await ctx.success(bot.steam.result_text(status, row, ctx.qc.gt), title=None)


async def slipgate(ctx, player: Member = None):
	""" A player's Slipgate ratings, by their linked Steam account """
	if not player:
		target = ctx.author
	elif hasattr(player, "id"):  # already a member (slash option, or found by the message command)
		target = player
	else:
		target = await ctx.get_member(player)
	if not target:
		raise bot.Exc.SyntaxError(ctx.qc.gt("Specified user not found."))
	gt = ctx.qc.gt
	steam_id = bot.slipgate.steam_id_of(target)
	if not steam_id:
		raise bot.Exc.NotFoundError(gt("{player} has no linked Steam account. Link one with `{cmd}`.").format(
			player=get_nick(target), cmd=f"{ctx.qc.cfg.prefix}steam"))
	try:
		data = await bot.slipgate.player_ratings(steam_id)
	except bot.slipgate.SlipgateError as e:
		raise bot.Exc.PubobotException(gt("Couldn't ask Slipgate: {error}").format(error=e))
	ratings = [r for r in (data or {}).get("ratings") or [] if isinstance(r, dict)]
	if not ratings:
		await ctx.reply(gt("Slipgate has no ratings for {player} yet.").format(player=get_nick(target)))
		return

	# The game types this channel's queues use come first, then the most played.
	ours = [q.cfg.slipgate_game_type for q in ctx.qc.queues if q.cfg.slipgate_game_type]
	ratings.sort(key=lambda r: (
		ours.index(r.get("game_type")) if r.get("game_type") in ours else len(ours),
		r.get("rating_set") != "A", -(r.get("games") or 0)
	))
	lines = []
	for r in ratings[:10]:
		name = bot.slipgate.GAME_NAMES.get(r.get("game_type"), str(r.get("game_type")))
		line = f"**{name}**" + (" " + gt("(modified)") if r.get("rating_set") == "B" else "")
		line += f" · `{r.get('display')}` · {r.get('tier_name') or '?'} · " + gt("{n} games").format(n=r.get("games") or 0)
		if r.get("provisional"):
			line += " · *" + gt("provisional") + "*"
		lines.append(line)
	embed = Embed(
		colour=Colour(0x1ff2a2),
		title=gt("Slipgate ratings of {player}").format(player=get_nick(target)),
		url=bot.slipgate.profile_url(steam_id),
		description="\n".join(lines),
	)
	footer = "slipgate.gg"
	if any(r.get("rating_set") == "B" for r in ratings[:10]):
		footer = gt("Modified: instagib, PQL and other non-standard settings") + " · " + footer
	embed.set_footer(text=footer)
	await ctx.reply(embed=embed)
