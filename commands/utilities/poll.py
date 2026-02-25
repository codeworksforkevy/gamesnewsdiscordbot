import discord
from discord import app_commands


def register_poll(group):

    @group.command(name="poll", description="Create a quick poll")
    @app_commands.describe(
        question="Poll question",
        option1="Option 1",
        option2="Option 2"
    )
    async def poll(
        interaction: discord.Interaction,
        question: str,
        option1: str,
        option2: str
    ):

        embed = discord.Embed(
            title="📊 Poll",
            description=f"**{question}**\n\n1️⃣ {option1}\n2️⃣ {option2}",
            color=0x00BFFF
        )

        await interaction.response.send_message(embed=embed)

        msg = await interaction.original_response()
        await msg.add_reaction("1️⃣")
        await msg.add_reaction("2️⃣")
