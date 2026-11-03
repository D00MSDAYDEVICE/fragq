# Moderator buttons

The queue panel has two icon buttons next to **Leave**, for the channel's **Moderator role** and
**Admin role**. Everyone can see them; anyone else who presses them gets a private "You must possess
moderator permissions" reply.

| Button | What it does |
|---|---|
| 👤 | **Add player**: add one or more members to a queue |
| ⏸️ | **Pause queue**: stop players from joining. Turns into a blue ▶️ that resumes the queue. |

The buttons only show an icon, because Discord buttons can't show tooltips; the panel's footer explains
them ("Moderators: 👤 add player · ⏸️ pause queue").

## Add player

1. Press 👤. If the channel has more than one queue, pick the queue first.
2. Pick up to 25 members in the member list and confirm.
3. FragQ replies, privately, with who was added and who was skipped and why: a bot, already in the
   queue, in a match, queue full, not allowed by the queue's roles.

Adding players works **while the queue is paused**, and for players who haven't
[linked a Steam account](../playing/steam.md) even when that is required. If the queue fills up, the
match starts as usual and any remaining members are skipped ("queue started").

The same is available as `/queue add_player`; `/queue remove_player` removes players.

## Pause queue

Press ⏸️ to pause the whole channel:

- every **Join** button turns grey and the panel turns amber, with *Queue paused: joining is disabled
  for now. Moderators can still add players.*;
- `!add`, `++`, `+queue` and `/add` reply *The queue is paused, joining is disabled for now.*;
- players already in a queue stay in it, and **Leave** keeps working;
- matches in progress carry on.

Press ▶️ to resume. The pause is saved, so it survives a restart of the bot. It can also be switched with
**Pause queue** / **Resume queue** on the channel page of the web panel (needs *Pause queues* access).

Typical uses: holding the queues during a tournament, while the game server is down, or at the end of
the evening.

## Hide the buttons

Channel settings → **Messages** → *Moderator buttons on queue panel* (`panel_mod_buttons`). With it off,
the panel only has Join and Leave, and the footer drops the explanation.
