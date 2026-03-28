import discord
from discord import app_commands


CONVERSIONS: dict[str, float] = {
    # Distance
    "km": 1000,
    "m":  1,
    "cm": 0.01,
    "mm": 0.001,
    "mi": 1609.344,
    "ft": 0.3048,
    "in": 0.0254,
}

UNIT_LABELS: dict[str, str] = {
    "km": "kilometres",
    "m":  "metres",
    "cm": "centimetres",
    "mm": "millimetres",
    "mi": "miles",
    "ft": "feet",
    "in": "inches",
}


def register_convert(group):

    @group.command(name="convert", description="📐 Convert between distance units")
    @app_commands.describe(
        value="Numeric value to convert",
        from_unit="Unit to convert from (km, m, cm, mm, mi, ft, in)",
        to_unit="Unit to convert to (km, m, cm, mm, mi, ft, in)",
    )
    async def convert(
        interaction: discord.Interaction,
        value: float,
        from_unit: str,
        to_unit: str,
    ):
        from_unit = from_unit.strip().lower()
        to_unit   = to_unit.strip().lower()

        supported = ", ".join(f"`{u}`" for u in CONVERSIONS)

        if from_unit not in CONVERSIONS or to_unit not in CONVERSIONS:
            embed = discord.Embed(
                title="❌ Unsupported unit",
                description=f"Supported units: {supported}",
                color=0xE74C3C,
            )
            return await interaction.response.send_message(embed=embed, ephemeral=True)

        meters = value * CONVERSIONS[from_unit]
        result = meters / CONVERSIONS[to_unit]

        # Format result cleanly — no unnecessary decimals
        result_str = f"{result:,.6f}".rstrip("0").rstrip(".")

        embed = discord.Embed(
            title="📐 Unit Conversion",
            color=0x5865F2,
        )
        embed.add_field(
            name="Input",
            value=f"`{value:,}` {UNIT_LABELS.get(from_unit, from_unit)}",
            inline=True,
        )
        embed.add_field(
            name="Result",
            value=f"**`{result_str}`** {UNIT_LABELS.get(to_unit, to_unit)}",
            inline=True,
        )
        embed.set_footer(text=f"🖥️ {from_unit.upper()} → {to_unit.upper()}")

        await interaction.response.send_message(embed=embed)
