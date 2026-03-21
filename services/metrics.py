# services/metrics.py

import logging

logger = logging.getLogger("metrics")

_metrics = {}


def inc(name: str, value: int = 1):
    """
    Simple in-memory metrics counter
    """

    try:
        _metrics[name] = _metrics.get(name, 0) + value

    except Exception as e:
        logger.warning(f"Metrics inc failed: {e}")


def get_metrics():
    return _metrics
