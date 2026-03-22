# core/command_loader.py

import os
import importlib
import logging

logger = logging.getLogger("command-loader")


async def load_all_commands(bot, app_state, session):
    """
    Auto-load all commands from /commands folder

    Expected structure:
    commands/
        x.py → async def register(bot, app_state, session)
    """

    commands_path = "commands"

    loaded = 0
    failed = 0

    for filename in os.listdir(commands_path):

        # skip non-python files
        if not filename.endswith(".py") or filename.startswith("_"):
            continue

        module_name = f"{commands_path}.{filename[:-3]}"

        try:
            module = importlib.import_module(module_name)

            # must have register()
            if not hasattr(module, "register"):
                logger.warning(f"{module_name} missing register()")
                continue

            register_func = getattr(module, "register")

            # async register
            await register_func(bot, app_state, session)

            loaded += 1

            logger.info(f"Loaded command module: {module_name}")

        except Exception as e:
            failed += 1

            logger.error(
                f"Command load failed: {module_name}",
                extra={"extra_data": {"error": str(e)}}
            )

    logger.info(
        "Command loading complete",
        extra={
            "extra_data": {
                "loaded": loaded,
                "failed": failed
            }
        }
    )
