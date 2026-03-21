import asyncio


class FetchRouter:
    def __init__(self, sources: list):
        self.sources = sources  # ordered list of callables

    async def fetch(self, *args, **kwargs):
        last_error = None

        for source in self.sources:
            try:
                result = await source(*args, **kwargs)

                if result:
                    return result

            except Exception as e:
                last_error = e
                continue

        raise RuntimeError(f"All sources failed: {last_error}")
