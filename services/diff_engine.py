
import hashlib
import json

def generate_hash(data):
    raw = json.dumps(data, sort_keys=True)
    return hashlib.sha256(raw.encode()).hexdigest()

def detect_change(old_data, new_data):
    return generate_hash(old_data) != generate_hash(new_data)
