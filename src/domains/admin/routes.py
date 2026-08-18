from datetime import date
from pathlib import Path as FilePath
from typing import Any

import structlog
from fastapi import APIRouter, Depends, Path, Query, Request, status
from fastapi.responses import StreamingResponse
from starlette.responses import HTMLResponse
from starlette.templating import Jinja2Templates

from infrastructure.config import settings
from integrations.logcenter.log_sender import LogSender
from .repositories import DEFAULT_COLLECTION
from .security import admin_required
from .services import AdminUserService

log = structlog.get_logger()
router = APIRouter(prefix="/api/admin")

_BASE_DIR = FilePath(__file__).resolve().parents[2]
templates = Jinja2Templates(directory=str(_BASE_DIR / "static" / "admin"))


def service_for(collection: str) -> AdminUserService:
    return AdminUserService.for_collection(collection)


@router.get("/users", dependencies=[Depends(admin_required)], response_model=Any)
async def list_users(
    name: str | None = Query(None),
    email: str | None = Query(None),
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    collection: str = Query(DEFAULT_COLLECTION),
) -> Any:
    return await service_for(collection).list_users(name, email, date_from, date_to, page, page_size)


@router.get("/users/export", dependencies=[Depends(admin_required)], response_class=StreamingResponse)
async def export_users(
    name: str | None = Query(None),
    email: str | None = Query(None),
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
    collection: str = Query(DEFAULT_COLLECTION),
):
    headers = {
        "Content-Disposition": 'attachment; filename="users.csv"',
        "Content-Type": "text/csv; charset=utf-8",
    }
    return StreamingResponse(
        service_for(collection).export_users_csv(name, email, date_from, date_to),
        headers=headers,
    )


@router.get("/users/raw", dependencies=[Depends(admin_required)], response_model=Any)
async def list_users_raw(collection: str = Query(DEFAULT_COLLECTION)) -> Any:
    """Nome/email/telefone sem projeção — usado pela página de descriptografia
    (esses campos podem estar cifrados quando ENCRYPTION_ENABLED=true)."""
    return await service_for(collection).list_users_raw()


@router.get("/users/{user_id}", dependencies=[Depends(admin_required)])
async def get_user(user_id: str = Path(..., title="ID do Usuário"), collection: str = Query(DEFAULT_COLLECTION)):
    return await service_for(collection).get_user(user_id)


@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(admin_required)])
async def delete_user(user_id: str = Path(..., description="ID do Usuário a ser excluído"), collection: str = Query(DEFAULT_COLLECTION)):
    await service_for(collection).delete_user(user_id)


@router.get("/encryption-status", dependencies=[Depends(admin_required)])
async def encryption_status() -> dict:
    return {"enabled": settings.ENCRYPTION_ENABLED}


@router.get("/inventory", response_class=HTMLResponse, dependencies=[Depends(admin_required)])
async def html_admin_inventory(request: Request):
    try:
        LogSender().log("pagina_admin_acessada")
        return templates.TemplateResponse(request, "admin.html")
    except Exception as exc:
        log.error("html-render-failed", error=str(exc), page="admin")
        return templates.TemplateResponse(request, "error.html")
