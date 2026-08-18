import structlog
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from domains.machine.repositories import BASE_DIR

log = structlog.get_logger()
router = APIRouter(prefix="/api")
templates = Jinja2Templates(directory=str(BASE_DIR / "static"))


@router.get("/health")
async def health():
    return {"status": "ok", "version": "0.1.0"}


@router.get("/", response_class=HTMLResponse, include_in_schema=False)
async def page_home(request: Request):
    return templates.TemplateResponse(request, "admin/login.html")


@router.get("/user", include_in_schema=False)
async def page_user(request: Request):
    return templates.TemplateResponse(request, "admin/user.html")


@router.get("/admin", include_in_schema=False)
async def page_admin(request: Request):
    return templates.TemplateResponse(request, "admin/admin.html")
