# commands/convert.py
# 📐 Distance unit conversion tool

import discord
from discord import app_commands

CONVERSIONS: dict[str, float] = {
    "km": 1000.0,
    "m":  1.0,
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
    async def convert(interaction: discord.Interaction, value: float, from_unit: str, to_unit: str):
        from_unit = from_unit.strip().lower()
        to_unit   = to_unit.strip().lower()

        if from_unit not in CONVERSIONS or to_unit not in CONVERSIONS:
            supported = ", ".join(f"`{u}`" for u in CONVERSIONS)
            await interaction.response.send_message(
                f"❌ Unsupported unit. Supported: {supported}", ephemeral=True
            )
            return

        # Calculate using meters as base
        meters = value * CONVERSIONS[from_unit]
        result = meters / CONVERSIONS[to_unit]
        
        # Clean formatting
        result_str = f"{result:,.6f}".rstrip("0").rstrip(".")

        embed = discord.Embed(title="📐 Unit Conversion", color=0x5865F2)
        embed.add_field(name="Input", value=f"`{value:,}` {UNIT_LABELS.get(from_unit, from_unit)}", inline=True)
        embed.add_field(name="Result", value=f"**`{result_str}`** {UNIT_LABELS.get(to_unit, to_unit)}", inline=True)
        
        await interaction.response.send_message(embed=embed)
