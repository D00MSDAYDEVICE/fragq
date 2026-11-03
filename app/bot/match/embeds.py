import re
from datetime import datetime, timezone

from nextcord import Embed, Colour, Streaming, Member
from core.client import dc
from core.utils import get_nick, join_and


class Embeds:
	""" This class generates discord embeds for various match states """

	def __init__(self, match):
		self.m = match
		# self.
		self.footer = dict(
			text=f"Match id: {self.m.id}",
			icon_url=dc.user.avatar.with_size(32).url if dc.user.avatar else None
			# icon_url="https://cdn.discordapp.com/avatars/240843400457355264/a51a5bf3b34d94922fd60751ba1d60ab.png?size=64"
		)

	def _ranked_nick(self, p: Member):
		if self.m.ranked:
			if self.m.qc.cfg.emoji_ranks:
				return f'{self.m.rank_str(p)}`{get_nick(p)}`'
			return f'`{self.m.rank_str(p)}{get_nick(p)}`'
		return f'`{get_nick(p)}`'

	def _ranked_mention(self, p: Member):
		if self.m.ranked:
			if self.m.qc.cfg.emoji_ranks:
				return f'{self.m.rank_str(p)}{p.mention}'
			return f'`{self.m.rank_str(p)}`{p.mention}'
		return p.mention

	def check_in(self, not_ready):
		embed = Embed(
			colour=Colour(0xf5d858),
			title=self.m.gt("__**{queue}** is now on the check-in stage!__").format(
				queue=self.m.queue.name[0].upper()+self.m.queue.name[1:]
			)
		)
		embed.add_field(
			name=self.m.gt("Waiting on:"),
			value="\n".join((f" \u200b {'❌ ' if p in self.m.check_in.discarded_players else ''}<@{p.id}>" for p in not_ready)),
			inline=False
		)
		if not len(self.m.check_in.maps):
			embed.add_field(
				name="—",
				value=self.m.gt(
					"Please react with {ready_emoji} to **check-in** or {not_ready_emoji} to **abort**!").format(
					ready_emoji=self.m.check_in.READY_EMOJI, not_ready_emoji=self.m.check_in.NOT_READY_EMOJI
				) + "\n\u200b",
				inline=False
			)
		else:
			embed.add_field(
				name="—",
				value="\n".join([
					self.m.gt("Please react with {ready_emoji} or vote for a map to **check-in**.").format(
						ready_emoji=self.m.check_in.READY_EMOJI
					),
					self.m.gt("React with {not_ready_emoji} to **abort**!").format(
						not_ready_emoji=self.m.check_in.NOT_READY_EMOJI
					) + "\n\u200b\nMaps:",
					"\n".join([
						f" \u200b \u200b {self.m.check_in.INT_EMOJIS[i]} \u200b {self.m.check_in.maps[i]}"
						for i in range(len(self.m.check_in.maps))
					])
				]),
				inline=False
			)
		embed.set_footer(**self.footer)

		return embed

	def draft(self):
		embed = Embed(
			colour=Colour(0x8758f5),
			title=self.m.gt("__**{queue}** is now on the draft stage!__").format(
				queue=self.m.queue.name[0].upper()+self.m.queue.name[1:]
			)
		)

		teams_names = [
			f"{t.emoji} \u200b **{t.name}**" +
			(f" \u200b `〈{sum((self.m.ratings[p.id] for p in t))//(len(t) or 1)}〉`" if self.m.ranked else "")
			for t in self.m.teams[:2]
		]
		team_players = [
			" \u200b ".join([
				self._ranked_nick(p) for p in t
			]) if len(t) else self.m.gt("empty")
			for t in self.m.teams[:2]
		]
		embed.add_field(name=teams_names[0], value=" \u200b ❲ \u200b " + team_players[0] + " \u200b ❳", inline=False)
		embed.add_field(name=teams_names[1], value=" \u200b ❲ \u200b " + team_players[1] + " \u200b ❳\n\u200b", inline=False)

		if len(self.m.teams[2]):
			embed.add_field(
				name=self.m.gt("Unpicked:"),
				value="\n".join((
					" \u200b " + self._ranked_nick(p)
				) for p in self.m.teams[2]),
				inline=False
			)

			if len(self.m.teams[0]) and len(self.m.teams[1]):
				msg = self.m.gt("Pick players with `/pick @player` command.")
				pick_step = len(self.m.teams[0]) + len(self.m.teams[1]) - 2
				picker_team = self.m.teams[self.m.draft.pick_order[pick_step]] if pick_step < len(self.m.draft.pick_order)-1 else None
				if picker_team:
					msg += "\n" + self.m.gt("{member}'s turn to pick!").format(member=f"<@{picker_team[0].id}>")
			else:
				msg = self.m.gt("Type {cmd} to become a captain and start picking teams.").format(
					cmd=f"`{self.m.qc.cfg.prefix}capfor {'/'.join((team.name.lower() for team in self.m.teams[:2]))}`"
				)

			embed.add_field(name="—", value=msg + "\n\u200b", inline=False)

		embed.set_footer(**self.footer)

		return embed

	def final_message(self):
		show_ranks = bool(self.m.ranked and not self.m.qc.cfg.rating_nicks)
		embed = Embed(
			colour=Colour(0x27b75e),
			title=self.m.qc.gt("__**{queue}** has started!__").format(
				queue=self.m.queue.name[0].upper()+self.m.queue.name[1:]
			)
		)

		if len(self.m.teams[0]) == 1 and len(self.m.teams[1]) == 1:  # 1v1
			p1, p2 = self.m.teams[0][0], self.m.teams[1][0]
			players = " \u200b {player1}{rating1}\n \u200b {player2}{rating2}".format(
				rating1=f" \u200b `〈{self.m.ratings[p1.id]}〉`" if show_ranks else "",
				player1=f"<@{p1.id}>",
				rating2=f" \u200b `〈{self.m.ratings[p2.id]}〉`" if show_ranks else "",
				player2=f"<@{p2.id}>",
			)
			embed.add_field(name=self.m.gt("Players"), value=players, inline=False)
		elif len(self.m.teams[0]):  # team vs team
			teams_names = [
				f"{t.emoji} \u200b **{t.name}**" +
				(f" \u200b `〈{sum((self.m.ratings[p.id] for p in t))//(len(t) or 1)}〉`" if self.m.ranked else "")
				for t in self.m.teams[:2]
			]
			team_players = [
				" \u200b " +
				" \u200b ".join([
					self._ranked_mention(p) for p in t
				])
				for t in self.m.teams[:2]
			]
			team_players[1] += "\n\u200b"  # Extra empty line
			embed.add_field(name=teams_names[0], value=team_players[0], inline=False)
			embed.add_field(name=teams_names[1], value=team_players[1], inline=False)
			if self.m.ranked or self.m.cfg['pick_captains']:
				embed.add_field(
					name=self.m.gt("Captains"),
					value=" \u200b " + join_and([self.m.teams[0][0].mention, self.m.teams[1][0].mention]),
					inline=False
				)

		else:  # just players list
			embed.add_field(
				name=self.m.gt("Players"),
				value=" \u200b " + " \u200b ".join((m.mention for m in self.m.players)),
				inline=False
			)
			if len(self.m.captains) and len(self.m.players) > 2:
				embed.add_field(
					name=self.m.gt("Captains"),
					value=" \u200b " + join_and([m.mention for m in self.m.captains]),
					inline=False
				)

		if len(self.m.maps):
			embed.add_field(
				name=self.m.qc.gt("Map" if len(self.m.maps) == 1 else "Maps"),
				value="\n".join((f"**{i}**" for i in self.m.maps)),
				inline=True
			)
		if self.m.cfg['server']:
			embed.add_field(name=self.m.qc.gt("Server"), value=f"`{self.m.cfg['server']}`", inline=True)

		if self.m.cfg['start_msg']:
			embed.add_field(name="—", value=self.m.cfg['start_msg'] + "\n\u200b", inline=False)

		if self.m.cfg['show_streamers']:
			if len(streamers := [p for p in self.m.players if isinstance(p.activity, Streaming)]):
				embed.add_field(name=self.m.qc.gt("Player streams"), inline=False, value="\n".join([
					f"{p.mention}: {p.activity.url}" for p in streamers
				]) + "\n\u200b")
		embed.set_footer(**self.footer)

		return embed

	# ------------------------------------------------------------------ FragQ "modern" layout

	@staticmethod
	def _server_lines(server: str) -> str:
		""" 'LABEL:' lines become bold headings, 'Name: value' keeps the name and makes the value copyable, addresses become code spans. """
		out = []
		for line in (server or "").splitlines():
			line = line.strip()
			if not line:
				if out and out[-1] != "":
					out.append("")
			elif line.endswith(":"):
				out.append(f"**{line.rstrip(':')}**")
			elif (kv := re.fullmatch(r"([^\d:]{1,24}):\s+(.+)", line)) and not re.match(r"[a-z]+://", line, re.I):
				out.append(f"{kv.group(1)}: `{kv.group(2)}`")
			elif not re.search(r"\d", line):
				out.append(f"**{line}**")
			else:
				out.append(f"`{line}`")
		return "\n".join(out).strip()[:1024]

	def _modern_player(self, p: Member, show_ranks: bool):
		if show_ranks:
			rank = self.m.rank_str(p)
			rank = rank if self.m.qc.cfg.emoji_ranks else f"`{rank}`"
			return f"{rank} {p.mention} ​`{self.m.ratings.get(p.id)}`"
		return p.mention

	def _team_avg(self, team):
		return sum(self.m.ratings[p.id] for p in team) // (len(team) or 1)

	def final_message_modern(self):
		m = self.m
		show_ranks = bool(m.ranked and not m.qc.cfg.rating_nicks)
		name = m.queue.name[0].upper() + m.queue.name[1:]
		teams = m.teams[:2]
		icon = self.footer.get("icon_url")
		embed = Embed(
			colour=Colour(0xf5b40a if m.ranked else 0x1ff2a2),
			title="⚔️ " + m.qc.gt("{queue} has started!").format(queue=name),
			timestamp=datetime.now(timezone.utc),
		)
		embed.set_author(
			name=f"MATCH #{m.id} · {'RANKED' if m.ranked else 'UNRANKED'} · {len(m.players)} PLAYERS",
			icon_url=icon
		)

		if m.cfg['start_msg']:
			embed.description = "\n".join(f"> {line}" for line in m.cfg['start_msg'].splitlines())

		if len(teams[0]) == 1 and len(teams[1]) == 1:  # duel
			p1, p2 = teams[0][0], teams[1][0]
			embed.add_field(name=m.gt("Players"), value="\n".join((
				self._modern_player(p1, show_ranks),
				"​ ​ ​ **vs**",
				self._modern_player(p2, show_ranks),
			)), inline=False)
		elif len(teams[0]):  # team vs team, side by side
			captains = m.ranked or m.cfg['pick_captains'] != "no captains"
			for t in teams:
				title = f"{t.emoji} {t.name}"
				if m.ranked:
					title += f" · avg {self._team_avg(t)}"
				lines = [
					self._modern_player(p, show_ranks) + (" \U0001F451" if i == 0 and captains else "")
					for i, p in enumerate(t)
				]
				embed.add_field(name=title, value="\n".join(lines) or "—", inline=True)
			embed.add_field(name="​", value="​", inline=True)  # keeps the two teams on their own row
		else:  # no teams: players in two columns
			players = [self._modern_player(p, show_ranks) for p in m.players]
			half = (len(players) + 1) // 2
			embed.add_field(name=f"{m.gt('Players')} ({len(players)})", value="\n".join(players[:half]) or "—", inline=True)
			embed.add_field(name="​", value="\n".join(players[half:]) or "​", inline=True)
			embed.add_field(name="​", value="​", inline=True)
			if len(m.captains) and len(m.players) > 2:
				embed.add_field(name=m.gt("Captains"), value=" · ".join(c.mention for c in m.captains), inline=False)

		if len(m.maps):
			embed.add_field(
				name="\U0001F5FA️ " + m.qc.gt("Map" if len(m.maps) == 1 else "Maps"),
				value="\n".join(f"`{i + 1}` **{map_name}**" for i, map_name in enumerate(m.maps)),
				inline=True
			)
		if m.cfg['server']:
			embed.add_field(name="\U0001F5A5️ " + m.qc.gt("Server"), value=self._server_lines(m.cfg['server']), inline=True)

		if m.cfg['show_streamers']:
			if len(streamers := [p for p in m.players if isinstance(p.activity, Streaming)]):
				embed.add_field(name="\U0001F4FA " + m.qc.gt("Player streams"), inline=False, value="\n".join(
					f"{p.mention}: {p.activity.url}" for p in streamers
				))

		hint = "captains report the result with /report" if m.ranked else "GLHF"
		embed.set_footer(text=f"Match #{m.id} · {hint}", icon_url=icon)
		return embed
