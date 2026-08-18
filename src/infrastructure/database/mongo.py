from motor.motor_asyncio import AsyncIOMotorClient
import certifi
from infrastructure.config import settings

_tls_kwargs = {"tls": True, "tlsCAFile": certifi.where()} if settings.MONGO_TLS else {}
_client = AsyncIOMotorClient(
    settings.MONGO_URI,
    serverSelectionTimeoutMS=20000,
    **_tls_kwargs,
)
db = _client[settings.MONGO_DB]


async def get_db():
    return db


async def init_db():
    await db.registrations.create_index("createdAt")
    await db.addresses.create_index("last_pickup_at")
