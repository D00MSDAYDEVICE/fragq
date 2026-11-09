# Settings page

**Settings** in the top bar holds the bot-wide settings: they apply to every server the bot is on.

| Who | What they see |
|---|---|
| The bot owner (`DISCORD_OWNER_ID`) | Everything below |
| Server admins and members with a channel's **Admin role** or **Moderator role** | Only **Linked players**, to [review Steam account changes](steam.md#approving-steam-account-changes) of members of their servers |

When Steam account changes are waiting for someone, the **Settings** link in the top bar shows how many.

![The Settings page](../assets/screenshots/settings.png){ .shot loading=lazy }

## Bot settings

The settings save as soon as you change them.

!!! note "Auto-repost queue panels moved"
    FragQ 1.0.0 had **Auto-repost queue panels** here, for every channel at once. It is now
    **Auto-refresh panel** on each channel's **Settings → General** tab (see
    [Keep it visible](../queue-panel/panel.md#keep-it-visible)). If it was on, every channel was
    switched on with the same number of minutes when you updated.

### Require Linked Steam IDs

Players must link a Steam account before they can join a queue. See
[Steam integration](steam.md#require-linked-steam-ids).

### Steam Web API key

Optional; makes Steam lookups faster. See [Steam integration](steam.md#steam-web-api-key).

## Linked players

Every Steam link, with pending changes at the top and **Approve**, **Reject** and **Unlink** buttons.
See [Steam integration](steam.md#linked-players).

## Backup and restore

A single file with all FragQ settings, to move them to a fresh install. See
[Backup and restore → Settings backup](backup-restore.md#settings-backup).
