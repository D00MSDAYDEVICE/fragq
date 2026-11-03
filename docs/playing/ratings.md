# Ratings and leaderboard

Queues with **is ranked** (`ranked`) turned on keep a rating for every player. Ratings belong to the
channel: all ranked queues on a channel share them, and a channel can use another channel's ratings
with **Rating channel** (`rating_channel`).

## Rating systems

Choose one per channel with **Rating system** (`rating_system`):

| System | How it works |
|---|---|
| `TrueSkill` (default) | Microsoft's TrueSkill: a rating and an uncertainty (deviation). New players move quickly; settled players slowly. |
| `Glicko2` | Similar idea, with rating volatility |
| `flat` | A fixed number of points per win or loss |

New players start at **Initial rating** (`rating_initial`, 1500) with **Initial deviation** (200).
The [Rating settings](../reference/channel-settings.md#rating) also cover win and loss scaling, draw
bonuses, win and loss streak boosts, and weekly decay for inactive players.

## Ranks

The **Rating ranks** table (`ranks`) turns ratings into ranks such as `〈C〉` or `〈★〉`. Each rank can
have a Discord role, which FragQ gives to players automatically. With **Set ratings to nicks**
(`rating_nicks`) FragQ adds the rating to members' nicknames; that needs the **Manage Nicknames**
permission. Players can change their nickname with `/nick` and keep the prefix.

## Commands

| Command | What it does |
|---|---|
| `!rank` / `/rank` | Your rating profile, or another player's |
| `!leaderboard` / `!lb` / `/leaderboard` | The rating leaderboard, page by page |
| `/top` | Most active players over a period |
| `/stats show` | Channel or player statistics |

The leaderboard hides players with fewer than **Leaderboard min matches** and, optionally, players who
haven't played for **Leaderboard last match limit**.

## In the web panel

The **Leaderboard** and **Matches** tabs show the same data with search and sorting, and download it as
CSV; see [Live, leaderboard and matches](../web-panel/live-and-stats.md).

## Moderator tools

| Command | What it does |
|---|---|
| `/rating seed <player> <rating> [deviation]` | Set a player's rating |
| `/rating penality <player> <points>` | Subtract points |
| `/rating hide_player`, `/rating unhide_player` | Hide a player from the leaderboard, or show them again |
| `/rating snap` | Snap every rating to its rank's value |
| `/rating reset` | Reset all ratings on the channel |
| `/stats reset_player`, `/stats stats_replace_player` | Reset a player, or move one player's stats to another account |
| `/stats undo_match <id>` | Undo a finished match and its rating changes |
