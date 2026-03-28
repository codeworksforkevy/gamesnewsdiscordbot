import discord
from discord import app_commands


REACTIONS = ["1️⃣", "2️⃣", "3️⃣", "4️⃣"]


def register_poll(group):

    @group.command(name="poll", description="🗳️ Create a poll with up to 4 options")
    @app_commands.describe(
        question="The question to ask",
        option1="Option 1 (required)",
        option2="Option 2 (required)",
        option3="Option 3 (optional)",
        option4="Option 4 (optional)",
    )
    async def poll(
        interaction: discord.Interaction,
        question: str,
        option1: str,
        option2: str,
        option3: str | None = None,
        option4: str | None = None,
    ):
        options = [o for o in [option1, option2, option3, option4] if o]

        lines = "\n".join(
            f"{REACTIONS[i]}  {opt}" for i, opt in enumerate(options)
        )

        embed = discord.Embed(
            title=f"🗳️ {question}",
            description=lines,
            color=0x5865F2,
        )
        embed.set_footer(
            text=f"👾 Poll by {interaction.user.display_name} • React to vote!"
        )

        await interaction.response.send_message(embed=embed)
        msg = await interaction.original_response()

        for i in range(len(options)):
            await msg.add_reaction(REACTIONS[i])
