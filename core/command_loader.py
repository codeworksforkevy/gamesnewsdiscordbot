"""
core/command_loader.py
────────────────────────────────────────────────────────────────
Auto-loads all command modules from the /commands folder.

Each command file must expose:
    async def register(bot, app_state, session) -> None

Files starting with '_' are skipped (e.g. __init__.py).
"""

import importlib
import logging
import os
import sys
import traceback

logger = logging.getLogger("command-loader")

COMMANDS_PATH = "commands"

async def load_all_commands(bot, app_state, session=None) -> None:
    """
    Discovers and loads every command module in the commands/ directory.
    Safe to call multiple times — modules are reloaded via importlib.
    """
    loaded: list[str] = []
    failed: list[str] = []

    if not os.path.exists(COMMANDS_PATH):
        logger.error(f"Commands folder '{COMMANDS_PATH}' not found — no commands loaded")
        return

    filenames = sorted(os.listdir(COMMANDS_PATH))

    for filename in filenames:
        if not filename.endswith(".py") or filename.startswith("_"):
            continue

        module_name = f"{COMMANDS_PATH}.{filename[:-3]}"
        short_name = filename[:-3]

        try:
            # Reload if already cached (supports hot-redeploy on Railway)
            if module_name in sys.modules:
                module = importlib.reload(sys.modules[module_name])
            else:
                module = importlib.import_module(module_name)

            if not hasattr(module, "register"):
                logger.warning(f"Skipping {module_name} — no register() function found")
                continue

            await module.register(bot, app_state, session)
            loaded.append(module_name)

            # Track in registry if available
            if hasattr(app_state, 'registry') and app_state.registry:
                app_state.registry.register(short_name, module_name)

            logger.info(f"Loaded command module: {module_name}")

        except Exception as e:
            failed.append(module_name)

            # Track error in registry if available
            if hasattr(app_state, 'registry') and app_state.registry:
                app_state.registry.register_error(module_name, e)

            logger.error(
                f"Command load failed: {module_name}\n"
                f"Error: {type(e).__name__}: {e}\n"
                f"Traceback:\n{traceback.format_exc()}"
            )

    # ── Summary ────────────────────────────────────────────────
    logger.info("Command loading complete")

    if loaded:
        logger.info(f"Loaded: {', '.join(loaded)}")

    if failed:
        logger.warning(
            f"Failed modules (fix these): {', '.join(failed)}\n"
            "Check the tracebacks above for each one."
        )
