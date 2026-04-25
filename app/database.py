from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from pymongo.errors import PyMongoError
from app.config import settings

_client: AsyncIOMotorClient | None = None


async def connect_db() -> None:
    global _client
    _client = AsyncIOMotorClient(settings.MONGODB_URI)
    try:
        # Fail fast during startup so API/agents don't run without DB.
        await _client.admin.command("ping")
    except PyMongoError:
        _client.close()
        _client = None
        raise


async def close_db() -> None:
    global _client
    if _client:
        _client.close()
        _client = None


def get_db() -> AsyncIOMotorDatabase:
    if _client is None:
        raise RuntimeError("Database client not initialized. Call connect_db() first.")
    return _client[settings.MONGODB_DB_NAME]
