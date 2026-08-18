from datetime import datetime

from pymongo import ReadPreference, ReturnDocument

from infrastructure.database.mongo import db

DEFAULT_COLLECTION = "machine"
SESSIONS_COLLECTION = "sample_sessions"
ADDRESSES_COLLECTION = "addresses"


class SessionRepository:
    def __init__(self):
        self.collection = db[SESSIONS_COLLECTION]

    async def create(self, doc: dict) -> None:
        await self.collection.insert_one(doc)

    async def find(self, session_id: str) -> dict | None:
        return await self.collection.find_one({"_id": session_id})

    async def try_mark_form_opened(self, session_id: str, now):
        return await self.collection.find_one_and_update(
            {"_id": session_id, "status": "pending", "retire_sent": {"$ne": True}},
            {"$set": {"retire_sent": True, "status": "form_shown", "form_opened_at": now}},
            return_document=ReturnDocument.AFTER,
        )

    async def try_start_processing(self, session_id: str, slug: str, now):
        return await self.collection.find_one_and_update(
            {
                "_id": session_id,
                "slug": slug,
                "status": "form_shown",
                "processing": {"$ne": True},
            },
            {"$set": {"processing": True, "status": "processing", "processing_started_at": now}},
            return_document=ReturnDocument.AFTER,
        )

    async def finalize(self, session_id: str, status: str, now) -> None:
        await self.collection.update_one(
            {"_id": session_id},
            {"$set": {"status": status, "processing": False, "completed_at": now}},
        )


class UserRepository:
    def __init__(self, collection_name: str = DEFAULT_COLLECTION):
        self.collection_name = collection_name
        self.collection = db[collection_name]

    def primary(self) -> "UserRepository":
        repo = UserRepository(self.collection_name)
        repo.collection = self.collection.with_options(read_preference=ReadPreference.PRIMARY)
        return repo

    async def ensure_unique_email_index(self) -> None:
        await self.collection.create_index("email", unique=True, name="uniq_email")

    async def create(self, doc: dict) -> None:
        await self.collection.insert_one(doc)

    async def list(self) -> list[dict]:
        return [doc async for doc in self.collection.find()]

    async def find_by_id(self, user_id: str) -> dict | None:
        return await self.collection.find_one({"_id": user_id})

    async def find_by_email(self, email: str) -> dict | None:
        return await self.collection.find_one({"email": email.lower()})

    async def find_one(self, query: dict) -> dict | None:
        return await self.collection.find_one(query)

    async def update_name(self, user_id: str, fields: dict) -> dict | None:
        return await self.collection.find_one_and_update(
            {"_id": user_id},
            {"$set": fields},
            return_document=ReturnDocument.AFTER,
        )

    async def delete(self, user_id: str) -> int:
        result = await self.collection.delete_one({"_id": user_id})
        return result.deleted_count

    async def add_pick(self, query: dict, pick_at, fields: dict) -> dict | None:
        return await self.collection.find_one_and_update(
            query,
            {"$push": {"pickHistory": pick_at}, "$set": fields},
            return_document=ReturnDocument.AFTER,
        )

    async def register_pickup(self, query: dict, day_dt, qty: int, next_can_pick_dt, updated_at) -> int:
        result = await self.collection.update_one(
            {
                **query,
                "$or": [{"pickedDay": {"$exists": False}}, {"pickedDay": {"$ne": day_dt}}],
            },
            {
                "$inc": {"productsPicked": qty},
                "$set": {
                    "pickedDay": day_dt,
                    "status": "picked",
                    "canPickFrom": next_can_pick_dt,
                    "updatedAt": updated_at,
                },
            },
            upsert=False,
        )
        return result.modified_count

    async def refresh_eligibility(self, today, updated_at):
        return await self.collection.update_many(
            {"status": "registered", "canPickFrom": {"$lte": today}},
            {"$set": {"status": "eligible", "updatedAt": updated_at}},
        )


class AddressRepository:
    def __init__(self):
        self.collection = db[ADDRESSES_COLLECTION]

    async def record_access(self, ip: str, now_sp: datetime) -> dict | None:
        return await self.collection.find_one_and_update(
            {"_id": ip},
            {
                "$setOnInsert": {"first_access_at": now_sp},
                "$set": {"last_access_at": now_sp},
                "$push": {"accesses": {"at": now_sp}},
            },
            upsert=True,
            return_document=ReturnDocument.AFTER,
        )

    async def record_pickup(self, ip: str, session_id: str, now_sp: datetime) -> None:
        await self.collection.update_one(
            {"_id": ip},
            {
                "$setOnInsert": {"first_access_at": now_sp},
                "$set": {"last_pickup_at": now_sp},
                "$push": {"pickups": {"at": now_sp, "session_id": session_id}},
            },
            upsert=True,
        )

    async def find(self, ip: str) -> dict | None:
        return await self.collection.find_one({"_id": ip})
