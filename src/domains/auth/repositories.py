from infrastructure.database.mongo import db


class AdminAuthRepository:
    def __init__(self):
        self.collection = db.admins

    async def find_by_username(self, username: str) -> dict | None:
        return await self.collection.find_one({"username": username})

    async def create(self, username: str, hashed_password: str) -> None:
        await self.collection.insert_one({"username": username, "password": hashed_password})
