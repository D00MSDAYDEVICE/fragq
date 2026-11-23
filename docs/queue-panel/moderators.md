# Moderator buttons

The queue panel has icon buttons next to **Leave**, for the channel's **Moderator role** and
**Admin role**. Everyone can see them; anyone else who presses them gets a private "You must possess
moderator permissions" reply.

| Button | What it does |
|---|---|
| 👤 | **Add player**: add one or more members to a queue |
| ⏸️ | **Pause queue**: stop players from joining a queue (or all of them). Turns into a blue ▶️ when every queue is paused. |
| ⏹️ | **End series**: end a queue's [series](../playing/matches.md#series) now, after a confirmation. Only on a channel with a series queue; grey while no series is on. |

The buttons only show an icon, because Discord buttons can't show tooltips; the panel's footer explains
them ("Moderators: 👤 add player · ⏸️ pause queue · ⏹️ end series").

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

Each queue has its own pause. On a channel with one queue, ⏸️ pauses it at once (and ▶️ resumes it). With
several queues, FragQ asks privately which one: each queue is listed with ⏸️ (pause) or ▶️ (resume), plus
**Pause all queues** and **Resume all queues**.

While a queue is paused:

- its field on the panel shows *⏸️ CTF · 0/8 · paused* and only its **Join** button turns grey; when every
  queue is paused, the whole panel turns amber, with *Queue paused: joining is disabled for now. Moderators
  can still add players.*;
- `!add`, `+ctf` and `/add` for it reply *CTF is paused, joining is disabled for now.* With `++` or several
  queues at once, players join the queues that are open, and FragQ names the paused ones;
- players already in it stay, and **Leave** keeps working;
- matches in progress carry on, and moderators can still add players with 👤.

The pause is saved, so it survives a restart of the bot. It can also be switched with **Pause Queue** /
**Queue paused** on the queue's page in the web panel, or its **⋯** menu (needs *Pause queues* access).

!!! note "It used to pause the whole channel"
    Up to FragQ 1.4 the pause was for the whole channel at once. A channel that was paused when you updated has
    each of its queues paused instead, and so does restoring an older backup with a paused channel.

Typical uses: holding the queues during a tournament, while the game server is down, or at the end of
the evening.

## End series

The ⏹️ button is there when one of the channel's queues has a **Series length** above 1. It is grey
until a series starts.

1. Press ⏹️. If several of the channel's queues have a series on, pick one first.
2. FragQ asks, privately, *End the series of **CTF** now? 1 of 3 games played (match #123). The queue
   opens again.* Press **End series** to end it, or **Cancel**.
3. The channel gets the usual *Series of **CTF** is over (ended by …)* message, the players go back to
   the Lobby (with voice moves on), and the queue opens again.

If the series ended on its own in the meantime, FragQ says so and does nothing. The same is available as
`!endseries <queue>` / `/endseries` and as **End series** in the web panel.

## Hide the buttons

Channel settings → **Messages** → *Moderator buttons on queue panel* (`panel_mod_buttons`). With it off,
the panel only has Join and Leave, and the footer drops the explanation.
