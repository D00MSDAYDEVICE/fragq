__all__ = ['steam']

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
