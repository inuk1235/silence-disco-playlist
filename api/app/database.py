from motor.motor_asyncio import AsyncIOMotorClient
from .config import get_settings

settings = get_settings()

class Database:
    client: AsyncIOMotorClient = None
    db = None

    def connect(self):
        self.client = AsyncIOMotorClient(settings.mongo_url)
        self.db = self.client[settings.db_name]

    def close(self):
        if self.client:
            self.client.close()

    def get_db(self):
        return self.db

db = Database()
