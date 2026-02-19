import json
import os
import discord
from discord import app_commands
from services.twitch_api import resolve_user

DATA_FILE = "data/streamers.json"


# ==============================
# STORAGE
# ==============================

def load_streamers():
    if not os.path.exists(DATA_FILE):
        return {}
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_streamers(data):
    os.makedirs("data", exist_ok=True)
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


# ==============================
# PERMISSIONS
# ==============================

def has_permission(interaction: discord.Interaction):
    if not interaction.guild:
        return False
    perms = interaction.user.guild_permissions
    return perms.administrator or perms.manage_guild


# ==============================
# COMMAND REGISTER
# ==============================

def register_live_commands(bot):

    group = app_commands.Group(
        name="live",
        description="Manage tracked live streamers"
    )

    # ------------------------------
    # ADD
    # ------------------------------

    @group.command(
        name="add",
        description="👩‍💻 Start tracking a streamer’s live sessions"
    )
    async def add(interaction: discord.Interaction, login: str):

        if not has_permission(interaction):
            await interaction.response.send_message(
                "Admin or mod only.",
                ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)

        user = await resolve_user(login)
        if not user:
            await interaction.followup.send("Streamer not found.")
            return

        data = load_streamers()

        if user["id"] in data:
            await interaction.followup.send("Already being tracked.")
            return

        data[user["id"]] = user
        save_streamers(data)

        await interaction.followup.send(
            f"""👩‍💻 **Start tracking a streamer’s live sessions**

**{user['display_name']}** is now being tracked.
The bot will automatically notify this channel when they go live.

🇳🇱 **Flemish**
👨‍💻 Begin met het volgen van de live sessies van **{user['display_name']}**.
De bot stuurt automatisch een melding wanneer ze live gaan.

Need help? Ask Sim for guidance."""
        )

    # ------------------------------
    # REMOVE
    # ------------------------------

    @group.command(
        name="remove",
        description="🧑‍💻 Stop tracking a streamer’s live sessions"
    )
    async def remove(interaction: discord.Interaction, login: str):

        if not has_permission(interaction):
            await interaction.response.send_message(
                "Admin or mod only.",
                ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)

        data = load_streamers()

        for sid, info in list(data.items()):
            if info["login"].lower() == login.lower():
                del data[sid]
                save_streamers(data)

                await interaction.followup.send(
                    f"""🧑‍💻 **Stop tracking a streamer’s live sessions**

**{info['display_name']}** is no longer tracked.
Live notifications for this streamer have been disabled.

🇳🇱 **Flemish**
👩‍💻 Stop met het volgen van de live sessies van **{info['display_name']}**.
Live meldingen zijn uitgeschakeld.

Need help? Ask Sim for guidance."""
                )
                return

        await interaction.followup.send("Streamer not found.")

    # ------------------------------
    # LIST
    # ------------------------------

    @group.command(
        name="list",
        description="💻 View tracked streamers"
    )
    async def list_cmd(interaction: discord.Interaction):

        data = load_streamers()

        if not data:
            await interaction.response.send_message(
                "No streamers tracked.",
                ephemeral=True
            )
            return

        names = [v["display_name"] for v in data.values()]

        await interaction.response.send_message(
            "💻 **Tracked Streamers**\n\n" + "\n".join(f"• {n}" for n in names),
            ephemeral=True
        )

    bot.tree.add_command(group)
