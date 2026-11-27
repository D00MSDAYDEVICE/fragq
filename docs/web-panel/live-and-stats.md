# Live, leaderboard and matches

## Live

A channel's **Live** tab shows each queue with its players and how full it is, and the matches in
progress. It updates by itself while you look at it. The server overview shows the same for all
channels of a server.

When a match's game server sends [live status](../connectors/result-format.md#live-status) (the Quake Live plugin
does, from 1.7.0), its card shows how the game stands instead of the plain teams: the state, round or minute, clock,
map and mode, the score, and a table per team with every player's stats (💀 for dead players), with when it was
last updated. Unranked matches, which FragQ stops following once they start, stay on the Live tab while their game
server keeps reporting. It's the same information as [`!checkmatch`](../reference/commands.md#matches) in Discord.

![The Live tab](../assets/screenshots/live.png){ .shot loading=lazy }

## Leaderboard

The **Leaderboard** tab lists the channel's players by rating, with the rating system in use. Each row
shows the rank, the rating with its deviation (`1553 ±193`), wins / losses / draws, the win rate, the
current win or loss streak and the last match. Type in **Search players…** to filter by name.

![The Leaderboard tab](../assets/screenshots/leaderboard.png){ .shot loading=lazy }

## Matches

The **Matches** tab is the channel's recent match history, newest first: match id, date, queue, the
teams, the maps and the winner.

![The Matches tab](../assets/screenshots/matches.png){ .shot loading=lazy }

## CSV downloads

**Players CSV** and **Matches CSV** on both tabs (also **Export players / matches (CSV)** in the
channel's **⋯** menu) download:

| File | Contents |
|---|---|
| **Players CSV** | One row per player: id, nick, rating, deviation, wins, losses, draws, streak, hidden, last ranked match |
| **Matches CSV** | One row per match: id, time, queue, ranked, winner, team names and scores, maps, and the players of each team |

The files open in Excel, LibreOffice or Google Sheets.

The Leaderboard and Matches tabs and the CSV downloads need the *Stats* permission; see
[Web panel access](../administration/access.md).
