# QueueGen events

**QueueGen** sets up a one-off match between two fixed teams, such as a cup final or a clan match, on a date
you choose. FragQ creates the event's own text channel, voice channels, queue and Discord scheduled event. Only
the players on the roster can check in, and the match starts once all of them have.

An event never touches your existing channels: it has its own channel, queue, ratings and match numbers, and its
channels are deleted again after the event.

Open **QueueGen** in the web panel's top bar. It needs the **Manage events** permission
([Web Panel Access](access.md)); server owners, Discord administrators and the bot owner have it.

## Before the first event

### Bot permissions

The bot's role needs these Discord permissions on the server. The page warns when one is missing.

| Permission | For |
|---|---|
| View Channels, Send Messages, Embed Links, Read Message History | The event channel and its messages |
| Manage Channels | Creating, renaming and deleting the event's channels and the Events category |
| Manage Roles | Setting who can see, type and connect in the event's channels |
| Connect, Move Members | Moving players from the Lobby into their team's voice channel |
| Speak | Letting players speak in the event's voice channels (the bot can only allow what it has itself) |
| Create Events | The Discord scheduled event |

The bot's invite link asks for all of them. A bot invited with an older link needs Speak and Create Events added
to its role in **Server Settings → Roles**, or a new invite.

### QueueGen settings

At the bottom of the page, per Discord server:

| Setting | |
|---|---|
| **Events category** | Where FragQ creates the event channels. By default it creates a **FragQ Events** category. If you choose your own, the bot needs View Channels, Manage Channels and Manage Roles in it. |
| **Organizer role** | Members with this role can type in every event channel, join its voice channels and moderate its match (it is the event channel's Admin role). Discord administrators always can. |
| **Lobby** | Where players wait before the match: a Lobby voice channel per event, one Lobby for every event that FragQ creates, or one you choose. |
| **Delete event channels** | The default cleanup time for new events. |

## Create an event

Press **Create event**.

| Field | |
|---|---|
| **Team 1**, **Team 2** | The team names, spaces allowed. |
| **Event name** | Empty: *Team 1 vs Team 2*. Names the channel too (`#team-1-vs-team-2`). |
| **Date and time** | In your own time zone. Discord shows it to everyone in theirs. |
| **Team size** | 1 v 1 to 8 v 8. |
| **Server** | `IP:port`, suggested from your channels' [Server Lists](../web-panel/overview.md). Shown on the event message and the match message. |
| **Roster** | The players of each team, chosen from the members who [linked a Steam account](steam.md). |
| **Description** | Shown on the event message and as the channel topic. |
| **Series** | One match for several games (best of 3, 5, 7 or 9); each game server result counts one game, as on a [series queue](../playing/matches.md). |
| **Results from** | The [game connector](../connectors/index.md) whose results go to this event's channel. |
| **Tournament** | Share ratings with other events ([Tournaments](#tournaments)). |
| **Rated** | On: the event is rated and the captains report the result (`/report`), as on a ranked queue. Off: any player ends the match. |
| **Show Slipgate results** | Slipgate's details on the results, when the connector has [Slipgate details](slipgate.md#slipgate-details-on-results) on. |
| **Private channel** | Only the roster and admins see the event's channels. Off: everyone sees them, only the roster and admins can type. |
| **Promote with a Discord event** | Create the [Discord event](#the-discord-event). Not for private events. |
| **Open check-in at the start time** | Off: an admin presses **Open check-in**. |
| **Discord event cover** | One of FragQ's four covers, or none. |
| **Discord event ends** | 1 day after the start by default. |
| **Delete the channels** | 24 hours after the event ends by default, or 3 or 7 days, or keep them. |

When you save, FragQ creates right away:

- the text channel `#team-1-vs-team-2` in the Events category, with an announcement: when, where, the rosters and
  a link to the Discord event;
- a voice channel per team, **🔴 Team 1** and **🔵 Team 2**, that only that team (and admins) can join;
- the Lobby, as set in the QueueGen settings;
- the Discord scheduled event.

Event channels don't appear in the panel's channel list: everything about them is on the QueueGen page.

## Check-in and the match

At the start time (or when an admin presses **Open check-in**) FragQ pings the roster in the event channel with
a message showing each player: ✅ checked in, ⌛ waiting, 🎮 still in another match. Players press **Check in**
(or type `!add`); **Leave** takes them out again. Players who haven't checked in are reminded every 10 minutes.

- Only the roster can check in. Anyone else is told so.
- A player still in a match on another queue checks in once that match is over: FragQ leaves running matches
  alone.
- If a team isn't full at the start time, FragQ says so in the channel and the event waits for an admin to fill
  the roster and press **Open check-in**.

When the last player checks in, the match starts with the two teams as you set them, with their names. Players
in the Lobby are moved into their team's voice channel. From there it is a normal FragQ match: reports, series,
results from the game server.

- **Rated** events: the captains (the first player of each team) report with `/report`, or a moderator does.
- **Unrated** events: any player of the match ends it with `/report`.
- A **canceled** match (`!cancel_match`, or no report within the match lifetime) puts the event back to check-in.

When the match (or series) is over, FragQ posts the result in the channel and the event is **finished**.

### Swap a player

Only admins change the roster: players can't sub themselves in or out. Use **Swap player** on the event:

- before the match, the new player takes the place on the roster and gets access to the channels;
- during the match, the new player takes their place in the match right away, as a substitute.

Before check-in opens, **Edit** changes the roster freely.

## The Discord event

Each public event gets a Discord scheduled event in the server's **Events** list:

| | |
|---|---|
| Title | ◄Team 1 vs Team 2► |
| Where | *Somewhere Else*: the Discord server's name |
| When | The match's start time, until 1 day later by default (**Discord event ends**). It doesn't repeat. |
| Description | The rosters, one team after the other |
| Cover | The chosen FragQ cover |

Members press **Interested** and Discord reminds them when it starts. It follows the event: it moves when you
change the date, its rosters update after a swap, it starts when check-in opens, and it ends when the event
finishes. Cancelling or deleting the event cancels or deletes it.

FragQ's covers are Crosshair (the default), Versus, Arena and Match day. They are drawn by `app/dev/gen_covers.py`
and stored in `app/webui/static/covers/`.

If Discord refuses the event (for example without Create Events), the event is still created and its card says
why. Save the event again once it's fixed.

## Tournaments

Without a tournament each event keeps its own ratings. To rate a series of events together (a cup, a league
season), create a **Tournament** on the QueueGen page and pick it on each event.

| Setting | |
|---|---|
| **Name** | |
| **Rating system** | As on a channel's Rating tab (TrueSkill by default) |
| **Initial rating**, **Initial deviation** | Where new players start |

Rated events in the same tournament share one rating history: a player's rating carries over from one event to
the next. The tournament card shows the number of rated players and matches, the events, and the top 10. Its
ratings stay when the event channels are deleted.

An event's tournament can't change once check-in is open. A tournament can't be deleted while upcoming or running
events use it; once deleted, its ratings stay in the database but aren't shown any more.

## Cancel, finish and clean up

- **Cancel event** ends it: its match is canceled, the Discord event too, and the channel says so.
- After an event is finished or cancelled, FragQ deletes the channels it created after the cleanup time (24 hours
  by default). A Lobby you chose, and the shared Lobby, stay. The event moves to **Past events** with its result.
- **Delete** removes an event right away, with its channels and its Discord event.

Results and ratings always stay: they are in the database, in the event's own ratings or its tournament's.

Events aren't part of [settings backups](backup-restore.md); the QueueGen settings and the tournaments are.
