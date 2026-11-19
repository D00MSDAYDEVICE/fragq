# Discord application

FragQ runs as your own Discord bot, so it needs a Discord application. You get three values from it,
plus your own user id, and the installer asks for all four.

## Create the application

1. Open the [Discord developer portal](https://discord.com/developers/applications) and choose
   **New Application**. The name is what players see, for example *FragQ*.
2. Optionally upload an icon on **General Information**. The bot's avatar also shows in the web panel.

## Bot tab

1. Press **Reset Token** and copy the token. This is `DISCORD_BOT_TOKEN`.
2. Under **Privileged Gateway Intents**, turn on all three:

    | Intent | Why FragQ needs it |
    |---|---|
    | **Presence Intent** | Remove offline players from queues, show streamers on match start |
    | **Server Members Intent** | Find members for the web panel, roles, rank roles and nicknames |
    | **Message Content Intent** | Read chat commands such as `!add`, `++` and `!pick` |

!!! danger "Keep the token secret"
    Anyone with the token can control the bot. If it leaks, press **Reset Token** and put the new one
    in `.env`.

## OAuth2 tab

1. Copy the **Client ID** (`DISCORD_CLIENT_ID`).
2. Press **Reset Secret** and copy the **Client Secret** (`DISCORD_CLIENT_SECRET`). The web panel uses
   these for **Sign in with Discord**.
3. Under **Redirects**, add the address of your web panel followed by `/auth/callback`:

    ```text
    https://fragq.example.com/auth/callback
    https://203.0.113.10:8443/auth/callback
    ```

    It must match `PUBLIC_URL` in `.env` exactly, including `https`, the port, and no trailing
    slash. The installer prints the exact line to add when it finishes. If you skip this step, the
    login fails with *Invalid OAuth2 redirect_uri*.

## Installation tab

You don't need to build an invite link. Once FragQ is running, the web panel's **Invite bot** link
asks for the right scopes and permissions itself, whatever this tab says. Check two things:

1. Under **Installation Contexts**, keep **Guild Install** ticked, or Discord refuses to add the bot
   to a server. **User Install** isn't used and can be unticked.
2. Under **Install Link**, choose **None** unless you want Discord's own **Add App** button on the
   bot's profile. If you do, choose **Discord Provided Link** and set **Default Install Settings →
   Guild Install** to match the panel's link:

    | Setting | Value |
    |---|---|
    | Scopes | `bot`, `applications.commands` |
    | Permissions | Manage Channels, Manage Roles, View Channels, Send Messages, Manage Messages, Embed Links, Attach Files, Read Message History, Add Reactions, Connect, Move Members |

    Add **Manage Nicknames** if you'll use *Set ratings to nicks*. [Invite the bot](first-steps.md#2-invite-the-bot)
    says what each permission is for.

!!! tip "Who can invite the bot"
    **Public Bot** on the **Bot** tab lets anyone with the link add your bot to their server. Turn it
    off to keep the bot to servers you add it to yourself. Leave **Requires OAuth2 Code Grant** off:
    with it on, the invite fails.

## Your user id

`DISCORD_OWNER_ID` makes you the bot owner. The owner has full access to every server the bot is on,
plus the **Bot status** and [Settings](../administration/settings-page.md) pages. To find your id, turn on **Developer Mode** in Discord
(**User Settings → Advanced**), then right-click your name and choose **Copy User ID**.

## Optional: faster slash commands

Discord can take up to an hour to show new or changed global slash commands. While testing, put your
server id in `DISCORD_SLASH_SERVERS` to register them on that server only, where they appear right
away. See the [.env reference](../administration/env.md#discord).

Next: [Installation](installation.md).
