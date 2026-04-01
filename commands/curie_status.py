import discord
from discord import app_commands
import logging
from datetime import datetime

logger = logging.getLogger("status-command")
KEVY_PINK = 0xFFB6C1

async def register(bot, app_state, session):
    
    @bot.tree.command(name="curie_status", description="⚠️ (Admin) Check Curie's laboratory vitals")
    @app_commands.default_permissions(manage_guild=True) # Sadece adminler görür
    async def curie_status(interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        
        # Teknik Kontroller
        db_status = "🟢 Connected" if app_state.db else "🔴 Offline"
        redis_status = "🟢 Active" if app_state.cache else "🟡 In-Memory"
        twitch_status = "🟢 Ready" if app_state.twitch_api else "🔴 Error"
        
        # Uptime hesaplama (bot.py'de start_time tanımlıysa)
        uptime = "Stable"
        if hasattr(bot, 'start_time'):
            delta = datetime.now() - bot.start_time
            uptime = str(delta).split('.')[0]

        embed = discord.Embed(
            title="🧪 Curie Laboratory Status",
            color=KEVY_PINK,
            description="All systems are operating within expected parameters."
        )
        
        embed.add_field(name="📊 Database", value=db_status, inline=True)
        embed.add_field(name="🧠 Redis", value=redis_status, inline=True)
        embed.add_field(name="📺 Twitch API", value=twitch_status, inline=True)
        
        embed.add_field(name="⏱️ Uptime", value=uptime, inline=True)
        embed.add_field(name="🏘️ Guilds", value=str(len(bot.guilds)), inline=True)
        embed.add_field(name="🛰️ Latency", value=f"{round(bot.latency * 1000)}ms", inline=True)

        embed.set_footer(text="Find a Curie • Restricted Access")
        embed.timestamp = discord.utils.utcnow()

        await interaction.followup.send(embed=embed)

    logger.info("Command /curie_status (Admin Only) registered")
