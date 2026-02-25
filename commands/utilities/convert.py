import discord
from discord import app_commands


def register_convert(group):

    @group.command(name="convert", description="Convert units")
    @app_commands.describe(
        value="Numeric value",
        from_unit="Unit to convert from (km, m, cm)",
        to_unit="Unit to convert to (km, m, cm)"
    )
    async def convert(
        interaction: discord.Interaction,
        value: float,
        from_unit: str,
        to_unit: str
    ):

        conversions = {
            "km": 1000,
            "m": 1,
            "cm": 0.01
        }

        if from_unit not in conversions or to_unit not in conversions:
            await interaction.response.send_message(
                "Supported units: km, m, cm",
                ephemeral=True
            )
            return

        meters = value * conversions[from_unit]
        result = meters / conversions[to_unit]

        await interaction.response.send_message(
            f"{value} {from_unit} = **{result} {to_unit}**"
        )
