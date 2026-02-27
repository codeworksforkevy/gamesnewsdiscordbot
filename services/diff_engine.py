import hashlib
import json
import logging

logger = logging.getLogger("diff-engine")


def generate_hash(data):

    try:
        raw = json.dumps(
            data,
            sort_keys=True,
            default=str  # datetime fallback
        )
    except Exception as e:
        logger.warning("Hash serialization failed: %s", e)
        raw = str(data)

    return hashlib.sha256(raw.encode()).hexdigest()


def detect_change(old_data, new_data):
    return generate_hash(old_data) != generate_hash(new_data)
