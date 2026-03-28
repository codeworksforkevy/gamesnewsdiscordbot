"""
core/hot_reload.py
────────────────────────────────────────────────────────────────
Hot-reloads all command modules without restarting the bot.

Fixes vs original:
- `importlib.sys` doesn't exist — the original would crash with
  AttributeError on every reload call. Fixed: use `sys` directly.
- register() is called with (bot, app_state, session) to match
  command_loader.py's calling convention. Original only passed
  (bot, app_state), which would cause TypeError in any command
  that accepts session.
- Added reloaded / failed summary log so you can see at a glance
  what succeeded and what needs fixing.
- registry.register() is now called with the full module path,
  consistent with command_loader.py.
"""

import importlib
import inspect
import logging
import sys

import pkgutil

logger = logging.getLogger("hot-reload")


async def reload_commands(bot, app_state, session=None) -> dict:
    """
    Reloads all modules found in the commands package.

    Returns a summary dict:
        {
            "reloaded": ["commands.ping", ...],
            "failed":   ["commands.broken_cmd"],
            "skipped":  ["commands.no_register"],
        }
    """
    from commands import __path__ as commands_path

    reloaded: list[str] = []
    failed:   list[str] = []
    skipped:  list[str] = []

    for _, module_name, _ in pkgutil.iter_modules(commands_path):
        full_name = f"commands.{module_name}"

        try:
            # Reload if cached, import fresh if not
            if full_name in sys.modules:
                module = importlib.reload(sys.modules[full_name])
            else:
                module = importlib.import_module(full_name)

            register_fn = getattr(module, "register", None)

            if not register_fn:
                skipped.append(full_name)
                logger.debug(f"Hot reload skipped (no register): {module_name}")
                continue

            # Call register with or without session depending on signature
            if inspect.iscoroutinefunction(register_fn):
                sig = inspect.signature(register_fn)
                if len(sig.parameters) >= 3:
                    await register_fn(bot, app_state, session)
                else:
                    await register_fn(bot, app_state)
            else:
                sig = inspect.signature(register_fn)
                if len(sig.parameters) >= 3:
                    register_fn(bot, app_state, session)
                else:
                    register_fn(bot, app_state)

            if app_state.registry:
                app_state.registry.register(module_name, full_name)

            reloaded.append(full_name)
            logger.info(f"Hot reloaded: {module_name}")

        except Exception as e:
            failed.append(full_name)

            if app_state.registry:
                app_state.registry.register_error(full_name, e)

            logger.exception(f"Hot reload failed: {module_name}")

    # ── Summary ────────────────────────────────────────────────
    logger.info(
        "Hot reload complete",
        extra={"extra_data": {
            "reloaded": len(reloaded),
            "failed":   len(failed),
            "skipped":  len(skipped),
        }},
    )

    if failed:
        logger.warning(f"Failed modules: {', '.join(failed)}")

    return {"reloaded": reloaded, "failed": failed, "skipped": skipped}
