# Linking Steam

FragQ can link your Discord account to your Steam account. Your Steam avatar then shows on the
[queue panel](../queue-panel/panel.md), and communities that require it can check who is who.

## Link your account

Use any of these, in a channel FragQ is enabled on:

```text
!steam https://steamcommunity.com/id/yourname
/steam steam:76561198000000000
```

`!link_steam` and `!steamid` work too. FragQ accepts:

| Format | Example |
|---|---|
| SteamID64 | `76561198000000000` |
| Profile link | `https://steamcommunity.com/profiles/76561198000000000` |
| Custom URL or its name | `https://steamcommunity.com/id/yourname`, or just `yourname` |
| SteamID2 | `STEAM_0:1:12345678` |
| SteamID3 | `[U:1:24691357]` |

FragQ looks the account up on Steam and replies with the Steam name it found. `!steam` or `/steam` on
its own shows your current link.

### From a game server

On game servers with a FragQ [connector](../connectors/index.md), such as a Quake Live server with the
FragQ plugin, you can also type this in the game chat:

```text
!link <your Discord user id or username>
```

FragQ sends you a Discord direct message: press **Confirm** to link the Steam account you are playing
on. See [`!link`](../connectors/quake-live.md#link).

## Change your account

Run `!steam` again with another ID. Your first link is immediate, but a **change** needs a moderator's
approval: FragQ replies that the change is waiting, and you stay linked to your current account until a
moderator or admin approves or rejects it. You get a direct message with the outcome. `!steam` on its
own shows a pending change. To withdraw it, run `!steam` with your current account.

!!! note "Private profiles"
    Private Steam profiles can be linked too: Steam always shares the profile name and avatar.

## When FragQ asks

If the bot owner turned on **Require Linked Steam IDs**, FragQ asks for your Steam ID the first time
you join a queue:

- From the **Join** button or `/add`: a pop-up form appears. Paste your Steam ID or profile link and
  submit; FragQ links it and adds you to the queue straight away.
- From `!add` or `++`: FragQ replies with a **Link Steam** button that opens the same form.

Moderators can still add players who haven't linked an account.

## Rules

- One Steam account can only be linked to one Discord member. If yours is already taken, ask a
  moderator; they can remove links on the **Settings** page.
- Links apply on every server the bot is on.
- Steam names and avatars are refreshed every few days.

For the admin side, see [Steam integration](../administration/steam.md).
