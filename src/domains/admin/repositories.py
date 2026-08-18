from infrastructure.database.mongo import db

DEFAULT_COLLECTION = "machine"


class AdminUserRepository:
    def __init__(self, collection_name: str = DEFAULT_COLLECTION):
        self.collection_name = collection_name
        self.collection = db[collection_name]

    def find(self, filters: dict):
        return self.collection.find(filters)

    async def count(self, filters: dict) -> int:
        return await self.collection.count_documents(filters)

    async def find_by_id(self, user_id: str) -> dict | None:
        return await self.collection.find_one({"_id": user_id})

    async def delete(self, user_id: str) -> int:
        result = await self.collection.delete_one({"_id": user_id})
        return result.deleted_count
