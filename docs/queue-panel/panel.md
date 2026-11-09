# The queue panel

The queue panel is a Discord message with a button for every queue. Players join and leave with one
click instead of typing commands, and the message always shows who is in which queue.

![The queue panel](../assets/screenshots/panel.png){ .shot loading=lazy width=600 }

## What it shows

- **One field per queue**: the name, how full it is (`5/8`), ⭐ for ranked queues, a progress bar and the
  players.
- **Matches in progress** on the channel, with their stage (check-in, draft, in game) and how long
  they've been running.
- **Player avatars**: a row of profile pictures per queue, with empty rings for the open places. Players
  with a [linked Steam account](../playing/steam.md) show their Steam avatar, others their Discord
  avatar. Queues over 8 players get another row of 8 (up to 24 places are drawn).
- **The buttons**: <span class="dbtn green">➕ Join</span> per queue (**Join *name*** when there are
  several), <span class="dbtn red">✖️ Leave</span>, and the two
  [moderator buttons](moderators.md) 👤 and ⏸️.
- **The footer** reminds players of `!add` / `!remove` and explains the moderator icons, because
  Discord buttons can't show tooltips.

The panel updates itself whenever someone joins, leaves, a match starts or finishes. A full queue's
**Join** button turns grey until there is room again.

## Post it

Any of these, by someone with the channel's **Admin role** (or *Queue panel* access in the web panel):

- **Post queue panel** on the channel page in the web panel.
- `!panel` in the channel.
- `/channel panel` (action *post*).

You don't have to: when a player joins a queue on a channel that has no panel, FragQ posts one by itself.

There is one panel per channel. Posting it again moves it to the bottom of the channel: the old message
is deleted and a new one is posted. The panel is remembered across restarts.

## Keep it visible

FragQ moves the panel back to the bottom of the channel (the same as **Move panel down**):

- **When a player joins a queue**, with the Join button, `!add`, `++` or `/add`. FragQ waits a moment
  for its reply, then moves the panel below it. If nothing has been posted since the panel, it stays
  where it is.
- **When a match starts**: the panel is re-posted below the match message. Turn that off with Channel
  settings → **Messages** → *Keep queue panel at the bottom* (`panel_repost`).
- **Every few minutes, if chat has buried it**, when **Auto-refresh panel** is on. It's at the top
  right of the channel's **Settings → General** tab: turn it on, set the minutes (5 to start with, 1 to
  1440) and save. A panel that is still the latest message is left alone, so quiet channels don't get
  reposts. In chat: `/channel set panel_autorefresh 5`, and `none` to turn it off.

You can also move it down at any time with **Move panel down** in the web panel or `!panel` again.

## Remove it

**Remove panel** in the web panel, `!panel off`, or `/channel panel` with action *remove*. Deleting the
message in Discord works too; FragQ notices and stops updating it.

## Replies are private

Button presses are answered with messages only the player sees (the queue they joined and who is in
it, or why they couldn't join), so the channel isn't flooded. `!add`, `++` and `/add` keep working as before and
reply in the channel.

## Avatar cache

FragQ downloads each avatar once and keeps it in the data volume (`/data/avatars`), so the panel picture
is drawn without fetching from Steam or Discord every time. Pictures that haven't been used for 30 days
are deleted automatically.
