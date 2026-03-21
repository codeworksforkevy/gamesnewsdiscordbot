import importlib
import pkgutil
import inspect
import logging

logger = logging.getLogger("hot-reload")


async def reload_commands(bot, app_state):
    from commands import __path__ as commands_path

    for _, module_name, _ in pkgutil.iter_modules(commands_path):
        full_name = f"commands.{module_name}"

        try:
            if full_name in importlib.sys.modules:
                module = importlib.reload(importlib.sys.modules[full_name])
            else:
                module = importlib.import_module(full_name)

            register_fn = getattr(module, "register", None)

            if not register_fn:
                continue

            if inspect.iscoroutinefunction(register_fn):
                await register_fn(bot, app_state)
            else:
                register_fn(bot, app_state)

            app_state.registry.register(module_name, full_name)

            logger.info(f"[HOT RELOAD] {module_name}")

        except Exception as e:
            app_state.registry.register_error(full_name, e)
            logger.exception(f"Reload failed: {module_name}")
