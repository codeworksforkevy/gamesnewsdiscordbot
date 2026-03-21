import importlib
import pkgutil
import inspect
import logging

logger = logging.getLogger("command-loader")


# ==================================================
# AUTO COMMAND LOADER
# ==================================================
async def load_commands(bot, app_state=None):
    """
    Automatically discovers and registers all commands.
    """

    from commands import __path__ as commands_path

    for _, module_name, _ in pkgutil.iter_modules(commands_path):
        full_module_name = f"commands.{module_name}"

        try:
            module = importlib.import_module(full_module_name)

            # -------------------------------------------------
            # FIND REGISTER FUNCTION
            # -------------------------------------------------
            register_fn = getattr(module, "register", None)

            if not register_fn:
                continue

            # -------------------------------------------------
            # CALL REGISTER (ASYNC / SYNC SAFE)
            # -------------------------------------------------
            if inspect.iscoroutinefunction(register_fn):
                await register_fn(bot, app_state)
            else:
                register_fn(bot, app_state)

            logger.info(f"Loaded command module: {module_name}")

        except Exception as e:
            logger.exception(f"Failed to load {module_name}: {e}")
