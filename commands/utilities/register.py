import discord
from discord import app_commands

from .timestamp import register_timestamp
from .convert import register_convert
from .poll import register_poll
from .reminder import register_reminder


async def register_utilities(bot):

    util_group = app_commands.Group(
        name="util",
        description="Utility tools"
    )

    register_timestamp(util_group)
    register_convert(util_group)
    register_poll(util_group)
    register_reminder(util_group)

    bot.tree.add_command(util_group)