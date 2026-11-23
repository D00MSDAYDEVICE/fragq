# Slipgate

[Slipgate](https://slipgate.gg) rates Quake Live players from their public games. With a Slipgate API key,
FragQ can:

- have Slipgate **split the players into even teams** when a match starts, and show how fair the teams are;
- **start new players at their Slipgate rating** on ranked queues, instead of the channel's initial rating;
- **keep a queue to a range of Slipgate ratings**, such as a newcomers' queue ([rating limits](#rating-limits));
- show a player's Slipgate ratings with **`!slipgate`** / **`/slipgate`**;
- add **Slipgate's view of the match** to results posted by a Quake Live game server: a link to its full stats,
  the top highlights and whether demos exist ([results](#slipgate-details-on-results)).

Everything goes by the Steam accounts players [linked in FragQ](steam.md). Slipgate is off until a key is saved
and passes a test, and FragQ never waits long on it: when Slipgate is slow or unavailable, FragQ uses its own
ratings and says so. Nothing changes on the game servers; the [Quake Live plugin](../connectors/quake-live.md)
needs no update for this.

## Set up the key

1. On Slipgate, sign in and open [slipgate.gg/me/settings](https://slipgate.gg/me/settings). Under **API keys**,
   create a key for FragQ. It is personal and read-only, and starts with `sg_`.
2. On FragQ's [Settings page](settings-page.md), paste it into the **Slipgate** panel and press **Save**. FragQ
   saves it and tests it with one lookup. **Test** checks the key in the box without saving it (an empty box
   tests the saved key).
3. Once the test passes, the panel shows **Connected**.

**Remove** forgets the key: queues that balance with Slipgate go back to FragQ's own matchmaking, and new
players start at the channel's initial rating again. The key isn't part of a [settings backup](backup-restore.md);
after a restore, save it again.

!!! note "One key, one account"
    The key belongs to the Slipgate account that made it, and every call FragQ makes counts against that
    account's rate limit. FragQ keeps calls few: one per match start for balancing, one per new player for
    starting ratings, and `!slipgate` answers are kept for 10 minutes.

## Balance teams with Slipgate

The queue's Slipgate settings are on their own **Settings → Slipgate** tab, after Voice:

| Setting | Tab | |
|---|---|---|
| **Pick teams** | Teams | `matchmaking` |
| **Slipgate game type** | Slipgate | The game type whose Slipgate ratings to use: `ca`, `ctf`, `tdm`, `ft`, `duel`, … |
| **Balance teams with Slipgate** | Slipgate | **ON** |

When the match starts, FragQ sends the players' Steam IDs to Slipgate, and Slipgate splits them into two teams.
Players Slipgate hasn't rated yet are balanced at Slipgate's starting estimate. The match message says how it
went, under the teams:

> ⚖️ **Balance** · Balanced by Slipgate · fairness 93% · Alpha 52% / Beta 48%

*Fairness* is 100% for a coin flip and 0% for a foregone conclusion; the percentages are each team's chance of
winning.

FragQ picks the teams itself, with its usual matchmaking, and the line says why, when:

| Line | Why |
|---|---|
| *Balanced by FragQ ratings (sk1nner not linked to Steam)* | A player has no linked Steam account. With [Require Linked Steam IDs](steam.md#require-linked-steam-ids) on, this doesn't happen. |
| *… (Slipgate unavailable)* | Slipgate didn't answer within 2.5 seconds, answered with an error, or asked FragQ to wait (rate limit). |
| *… (Slipgate's answer didn't fit the match)* | Slipgate's teams didn't contain exactly the match's players. |
| *… (Slipgate isn't connected)* | No key passed a test. |

After a substitution or `!put`, the line is dropped: the teams are no longer the ones Slipgate picked. Ratings
change after `/report` as usual: Slipgate only picks the teams, it never changes FragQ ratings.

## Start new players at their Slipgate rating

On the channel's **Settings → Rating** tab, **Start new players at their Slipgate rating**. It works for ranked
queues that have a **Slipgate game type**.

When a ranked match starts, each player who has no rating on the channel yet, and is linked to Steam, starts from
their place on that game type's Slipgate ladder:

- the middle of the ladder is the channel's **Initial rating**;
- one rating deviation per standard deviation above or below it: with an initial rating of 1500 and a deviation
  of 200, a player in the top 2% starts around 1900, one at the bottom 5% around 1175;
- the deviation is 60% of the channel's, so FragQ can still correct the rating quickly; a Slipgate rating that is
  still *provisional* keeps the full deviation. Flat-points channels only get the rating.

It goes by the ladder position, not Slipgate's own numbers, so it fits whatever scale the channel uses. It
happens once per player, and shows in their rating history as *Slipgate starting rating*. Players who aren't
linked, aren't on the ladder, or are on a ladder of fewer than 20 players start at the initial rating as before.

## The game type and ladder

Everything a queue does with Slipgate uses its **Slipgate game type** (`ca`, `ctf`, …) and **Slipgate ladder**, on
the queue's **Settings → Slipgate** tab. Each game type has two ladders on Slipgate: **standard** (the default), for
normal settings, and **modified**, for PQL, instagib and other non-standard settings. Set **modified** for a PQL or
instagib queue so its balancing, starting ratings and rating limits use that ladder.

## Rating limits

A queue can be limited to a range of Slipgate ratings, such as a newcomers' queue with a maximum, or a high-level
queue with a minimum. On the queue's **Settings → Slipgate** tab, with a **Slipgate game type** set:

| Setting | Default | |
|---|---|---|
| **Minimum Slipgate rating** | not set | Players whose Slipgate **display rating** is lower can't join |
| **Maximum Slipgate rating** | not set | Players whose display rating is higher can't join |
| **Let unrated players in** | on | Players Slipgate has no rating for in this game type and ladder, or who aren't linked to Steam, can join anyway |
| **Let provisional players in** | on | Players whose rating is still provisional can join whatever it is |

The display rating is the number Slipgate shows on its site and `!slipgate` shows here. The web panel refuses a
minimum above the maximum, and the queue panel shows the range next to the queue's name, such as *🎯 ≤1800* or
*🎯 1200–1800*.

When a player joins (Join, `!add`, `++`, `/add`), FragQ looks up their rating by their linked Steam account (kept
for 10 minutes) and replies, if they can't join, with why: *"Your Slipgate Clan Arena rating (1950) is above the
maximum for **CA-low** (1800)."* Adding to several queues at once, they join the others they asked for.

- With **Let unrated players in** off, players unknown to Slipgate are refused, and players who aren't linked are
  asked to link their Steam account first, like [Require Linked Steam IDs](steam.md#require-linked-steam-ids).
- With **Let provisional players in** off, players whose rating is still provisional are refused until it settles.
- When Slipgate can't be asked (no key, unavailable, rate limited), players are let in rather than locked out, and
  the reason is logged.
- Moderators can still add anyone with **Add player**.

## `!slipgate`

`!slipgate [player]`, `!sg` or `/slipgate` shows a player's Slipgate ratings, by their linked Steam account: the
game types the channel's queues use first, then the most played, each with the rating, tier and number of games.
*Modified* is Slipgate's ladder for instagib, PQL and other non-standard settings. The title links to the player's
Slipgate page. This works without a key too.

## Slipgate details on results

For a Quake Live game server that also runs Slipgate's own plugin, FragQ can add Slipgate's view of each match to
the result the game server posts. Turn on **Add Slipgate details to results** on the server's connector
(**Connectors** page, Quake Live connectors only). It works without an API key; with one, the calls count against
the key instead of FragQ's address.

To keep Slipgate's details off one queue's results, turn on **Disable Slipgate Results** on that queue's
**Settings → Slipgate** tab (off by default). Its results are still posted, just without Slipgate's part, whatever
the connector and the Settings page say. Turned on while a result is still being looked up, it stops that lookup.

The result is posted right away, as always. Slipgate only has the match once its plugin uploaded it, so FragQ
looks it up 30 seconds, 2 minutes, 5 minutes and 15 minutes after the result, and stops at the first answer. When
it has it, FragQ edits the posted result:

- the title links to the match on slipgate.gg;
- a **🔎 Slipgate** field says *Full stats on Slipgate*, whether Slipgate rated the match (or why not, such as
  *too few players*), and how many player demos there are and whether a merged demo exists, linked to the match
  page, where players download them after signing in on Slipgate;
- up to three highlights, biggest first, such as *🎯 Midair rail: sk1nner* or *🔥 Clutch 1v3: st01c*. Players
  linked in FragQ show with their Discord name, others with their in-game name.

FragQ finds the match by the Quake Live match ID the [FragQ plugin](../connectors/quake-live.md#match-results)
already sends with every result. If Slipgate doesn't know that ID by the last try, FragQ looks for a match of one of
the players on the same map that ended within 5 minutes of the result and has most of its players. If there is
none, the result stays as it was. The lookups survive a restart of FragQ: results from the last 30 minutes that
were still being looked up carry on. Matches found this way also get a **Slipgate** link next to their number on
the channel's **Matches** page.

## The Settings panel

Besides **Connected**, the **Slipgate** panel shows when the key was tested, how many matches Slipgate balanced
(and how many FragQ balanced instead), how many starting ratings were given and how many results got Slipgate
details since FragQ started, the last
error, and, after a rate limit, until when FragQ leaves Slipgate alone. FragQ waits exactly as long as Slipgate's
`Retry-After` asks.
