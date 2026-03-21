class AppState:
    def __init__(self, db_pool, redis, config):
        self.db = db_pool
        self.redis = redis
        self.config = config

        self.features = None
        self.registry = None
