import csv
import io
from datetime import date, datetime, time, timezone
from typing import Any

import structlog
from fastapi import HTTPException, status

from .repositories import DEFAULT_COLLECTION, AdminUserRepository

log = structlog.get_logger()


def dt2date_str(value) -> str | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return None


def safe_int(value, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


def build_filters(name: str | None, email: str | None, date_from: date | None, date_to: date | None) -> dict:
    filters: dict = {}
    if name:
        filters["name"] = {"$regex": name, "$options": "i"}
    if email:
        filters["email"] = {"$regex": email, "$options": "i"}
    if date_from or date_to:
        date_filter: dict = {}
        if date_from:
            date_filter["$gte"] = datetime.combine(date_from, time.min).replace(tzinfo=timezone.utc)
        if date_to:
            date_filter["$lte"] = datetime.combine(date_to, time.max).replace(tzinfo=timezone.utc)
        filters["createdAt"] = date_filter
    return filters


def admin_user_row(doc: dict) -> dict[str, Any]:
    return {
        "id": str(doc["_id"]),
        "name": doc.get("name", ""),
        "email": doc.get("email", ""),
        "status": doc.get("status", ""),
        "birthDate": dt2date_str(doc.get("birthDate")),
        "registerDay": dt2date_str(doc.get("registerDay")),
        "canPickFrom": dt2date_str(doc.get("canPickFrom")),
        "pickedDay": dt2date_str(doc.get("pickedDay")),
        "juicesPicked": safe_int(doc.get("juicesPicked", 0)),
    }


class AdminUserService:
    def __init__(self, repository: AdminUserRepository):
        self.repository = repository

    @classmethod
    def for_collection(cls, collection: str = DEFAULT_COLLECTION) -> "AdminUserService":
        return cls(AdminUserRepository(collection))

    async def list_users(
        self,
        name: str | None,
        email: str | None,
        date_from: date | None,
        date_to: date | None,
        page: int,
        page_size: int,
    ) -> dict:
        filters = build_filters(name, email, date_from, date_to)
        skip = (page - 1) * page_size
        cursor = self.repository.find(filters).sort("createdAt", -1).skip(skip).limit(page_size)
        results = [admin_user_row(doc) async for doc in cursor]
        total = await self.repository.count(filters)
        log.info("admin-list-users", filters=filters, page=page, page_size=page_size, collection=self.repository.collection_name)
        return {"data": results, "page": page, "page_size": page_size, "total": total}

    def export_users_csv(self, name: str | None, email: str | None, date_from: date | None, date_to: date | None):
        filters = build_filters(name, email, date_from, date_to)
        cursor = self.repository.find(filters).sort("createdAt", -1)
        log.info("admin-export-users", filters=filters, collection=self.repository.collection_name)

        async def csv_generator():
            buf = io.StringIO()
            writer = csv.writer(buf)
            writer.writerow([
                "id", "name", "email", "status",
                "birthDate", "registerDay", "canPickFrom", "pickedDay",
                "juicesPicked", "createdAt",
            ])
            yield buf.getvalue()
            buf.seek(0)
            buf.truncate(0)

            async for doc in cursor:
                writer.writerow([
                    str(doc["_id"]),
                    doc.get("name", ""),
                    doc.get("email", ""),
                    doc.get("status", ""),
                    dt2date_str(doc.get("birthDate")) or "",
                    dt2date_str(doc.get("registerDay")) or "",
                    dt2date_str(doc.get("canPickFrom")) or "",
                    dt2date_str(doc.get("pickedDay")) or "",
                    safe_int(doc.get("juicesPicked", 0)),
                    (doc.get("createdAt") or datetime.now(timezone.utc)).isoformat(),
                ])
                yield buf.getvalue()
                buf.seek(0)
                buf.truncate(0)

        return csv_generator()

    async def list_users_raw(self) -> list[dict[str, Any]]:
        """Retorna nome/email/telefone sem projeção — usados pela página de
        descriptografia, que pode receber texto cifrado nesses mesmos campos
        quando ENCRYPTION_ENABLED estiver ativo."""
        cursor = self.repository.find({}).sort("createdAt", -1)
        results = []
        async for doc in cursor:
            results.append({
                "id": str(doc["_id"]),
                "name": doc.get("name", ""),
                "email": doc.get("email", ""),
                "phone": doc.get("phone", ""),
                "created_at": (doc.get("createdAt") or datetime.now(timezone.utc)).isoformat(),
                "productsPicked": safe_int(doc.get("productsPicked", 0)),
            })
        return results

    async def get_user(self, user_id: str) -> dict:
        doc = await self.repository.find_by_id(user_id)
        if not doc:
            log.warning("admin-user-not-found", user_id=user_id, collection=self.repository.collection_name)
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Usuário não encontrado")
        result = admin_user_row(doc)
        result["createdAt"] = (doc.get("createdAt") or datetime.now(timezone.utc)).isoformat()
        return result

    async def delete_user(self, user_id: str) -> None:
        deleted = await self.repository.delete(user_id)
        if deleted == 0:
            log.warning("admin-delete-failed", user_id=user_id, collection=self.repository.collection_name)
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Usuário não encontrado")
        log.info("admin-delete-user", user_id=user_id, collection=self.repository.collection_name)
