import os
import importlib
import logging
import traceback

logger = logging.getLogger("command-loader")


async def load_all_commands(bot, app_state, session):
    """
    Auto-load all command modules from the /commands folder.

    Each command file must expose:
        async def register(bot, app_state, session) -> None

    Files starting with '_' are skipped (e.g. __init__.py).
    Errors in individual modules are logged in full but do NOT
    crash the loader — the bot starts with whatever commands
    loaded successfully.
    """
    commands_path = "commands"
    loaded = []
    failed = []

    try:
        filenames = sorted(os.listdir(commands_path))
    except FileNotFoundError:
        logger.error(f"Commands folder '{commands_path}' not found — no commands loaded")
        return

    for filename in filenames:
        # Skip non-Python files and private/dunder files
        if not filename.endswith(".py") or filename.startswith("_"):
            continue

        module_name = f"{commands_path}.{filename[:-3]}"

        try:
            # importlib.import_module caches modules — reload if already imported
            # so Railway hot-redeploys pick up changes correctly
            if module_name in __import__("sys").modules:
                module = importlib.reload(__import__("sys").modules[module_name])
            else:
                module = importlib.import_module(module_name)

            if not hasattr(module, "register"):
                logger.warning(
                    f"Skipping {module_name} — no register() function found"
                )
                continue

            await module.register(bot, app_state, session)
            loaded.append(module_name)
            logger.info(f"Loaded command module: {module_name}")

        except Exception as e:
            failed.append(module_name)
            # Log the FULL traceback so you can see exactly what line failed
            logger.error(
                f"Command load failed: {module_name}\n"
                f"Error: {type(e).__name__}: {e}\n"
                f"Traceback:\n{traceback.format_exc()}"
            )

    # ── Summary ────────────────────────────────────────────────────────────
    logger.info(
        f"Command loading complete — "
        f"{len(loaded)} loaded, {len(failed)} failed"
    )

    if loaded:
        logger.info(f"Loaded: {', '.join(loaded)}")

    if failed:
        logger.warning(
            f"Failed modules (fix these): {', '.join(failed)}\n"
            f"Check the tracebacks above for each one."
        )
