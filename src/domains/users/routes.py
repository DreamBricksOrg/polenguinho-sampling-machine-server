from pathlib import Path
from typing import List

from fastapi import APIRouter, Body, HTTPException, Query, Request, Response
from pydantic import EmailStr
from starlette.responses import HTMLResponse, RedirectResponse
from starlette.templating import Jinja2Templates

from infrastructure.config import settings
from integrations.logcenter.log_sender import LogSender
from .schemas import (
    QRCodeInitResponse,
    SessionCompleteRequest,
    SessionCompleteResponse,
    SessionGetResponse,
    SessionPickupRequest,
    SessionPickupResponse,
    UserGetResponse,
    UserInitRequest,
    UserInitResponse,
    UserPickupRequest,
    UserPickupResponse,
    UserUpdateRequest,
)
from .repositories import DEFAULT_COLLECTION, AddressRepository
from .services import (
    PICKUP_BLOCK_COOKIE_NAME,
    SessionService,
    UserService,
    build_pickup_block_cookie_value,
    is_ip_blocked,
    is_pickup_blocked,
    is_within_business_hours,
    now_saopaulo,
    now_utc,
)


def _extract_client_ip(request: Request) -> str:
    return (
        request.headers.get("x-forwarded-for", "").split(",")[0].strip()
        or request.headers.get("x-real-ip", "")
        or (request.client.host if request.client else "unknown")
    )

_BASE_DIR = Path(__file__).resolve().parents[2]
templates = Jinja2Templates(directory=str(_BASE_DIR / "static" / "sample" / "html"))

router = APIRouter(prefix="/api/users")
session_router = APIRouter(prefix="/api/sample")


def service_for(collection: str) -> UserService:
    return UserService.for_collection(collection)


@router.post("/", response_model=UserInitResponse)
async def create_user(payload: UserInitRequest, collection: str = Query(DEFAULT_COLLECTION)):
    return await service_for(collection).create_user(payload)


@router.get("/", response_model=List[UserGetResponse])
async def list_users(collection: str = Query(DEFAULT_COLLECTION)):
    return await service_for(collection).list_users()


@router.get("/email/{email}", response_model=UserGetResponse)
async def get_user_by_email(email: EmailStr, collection: str = Query(DEFAULT_COLLECTION)):
    return await service_for(collection).get_user_by_email(email)


@router.get("/{user_id}", response_model=UserGetResponse)
async def get_user(user_id: str, collection: str = Query(DEFAULT_COLLECTION)):
    return await service_for(collection).get_user(user_id)


@router.put("/{user_id}", response_model=UserGetResponse)
async def update_user(user_id: str, update: UserUpdateRequest, collection: str = Query(DEFAULT_COLLECTION)):
    return await service_for(collection).update_user(user_id, update)


@router.delete("/{user_id}")
async def delete_user(user_id: str, collection: str = Query(DEFAULT_COLLECTION)):
    return await service_for(collection).delete_user(user_id)


@router.post("/pickup", response_model=UserPickupResponse)
async def register_pickup(payload: UserPickupRequest = Body(...), collection: str = Query(DEFAULT_COLLECTION)):
    return await service_for(collection).register_pickup(payload)


@router.post("/eligibility/refresh")
async def refresh_eligibility(collection: str = Query(DEFAULT_COLLECTION)):
    return await service_for(collection).refresh_eligibility()


@session_router.post("/session/complete", response_model=SessionCompleteResponse)
async def complete_session(payload: SessionCompleteRequest):
    return await SessionService().complete_session(payload)


@session_router.post("/qrcode/init", response_model=QRCodeInitResponse)
async def init_qrcode():
    return await SessionService().init_qrcode()


@session_router.get("/start")
async def start_static_session(request: Request):
    if not is_within_business_hours(
        now_utc(), settings.SAMPLE_TIMEZONE, settings.SAMPLE_OPEN_HOUR, settings.SAMPLE_CLOSE_HOUR
    ):
        LogSender().log(
            "servidor_start_blocked_horario",
            additional={"open_hour": settings.SAMPLE_OPEN_HOUR, "close_hour": settings.SAMPLE_CLOSE_HOUR},
            status="ERROR",
            tags=["form", "start", "blocked", "horario", "server"],
        )
        return templates.TemplateResponse(
            request,
            "closed.html",
            {"open_hour": settings.SAMPLE_OPEN_HOUR, "close_hour": settings.SAMPLE_CLOSE_HOUR},
        )

    client_ip = _extract_client_ip(request)
    addr_repo = AddressRepository()
    addr_doc = await addr_repo.record_access(client_ip, now_saopaulo())

    if is_ip_blocked(addr_doc, now_utc(), settings.PICKUP_COOKIE_BLOCK_HOURS):
        LogSender().log(
            "servidor_start_blocked_ip",
            additional={"ip": client_ip},
            status="ERROR",
            tags=["form", "start", "blocked", "ip", "server"],
        )
        return templates.TemplateResponse(request, "error.html")

    cookie_value = request.cookies.get(PICKUP_BLOCK_COOKIE_NAME)
    if is_pickup_blocked(cookie_value, now_utc(), settings.PICKUP_COOKIE_BLOCK_HOURS):
        LogSender().log(
            "servidor_start_blocked",
            additional={"cookie": cookie_value},
            status="ERROR",
            tags=["form", "start", "blocked", "server"],
        )
        return templates.TemplateResponse(request, "error.html")

    doc = await SessionService().init_static_session()
    return RedirectResponse(
        url=f"/api/sample/form?sid={doc['_id']}&slug={doc['slug']}",
        status_code=302,
    )


@session_router.post("/session/pickup", response_model=SessionPickupResponse)
async def start_pickup(payload: SessionPickupRequest):
    return await SessionService().start_pickup(payload)


@session_router.get("/thanks", response_class=HTMLResponse)
async def html_thanks(request: Request):
    return _render_logged_page(request, "thanks.html", "pagina_agradecimento_acessada", "thanks")


@session_router.get("/session/{sid}", response_model=SessionGetResponse)
async def get_session_info(sid: str, response: Response, request: Request):
    info = await SessionService().get_session_info(sid)
    if info.status == "completed" and info.mode == "qrcode_static":
        response.set_cookie(
            key=PICKUP_BLOCK_COOKIE_NAME,
            value=build_pickup_block_cookie_value(sid, now_utc()),
            max_age=int(settings.PICKUP_COOKIE_BLOCK_HOURS * 3600),
            httponly=True,
            samesite="lax",
            secure=settings.ENV != "dev",
            path="/api/sample",
        )
        client_ip = _extract_client_ip(request)
        await AddressRepository().record_pickup(client_ip, sid, now_saopaulo())
    return info


@session_router.get("/claim", response_class=HTMLResponse)
async def html_claim(request: Request):
    return _render_logged_page(request, "claim.html", "servidor_claim", "claim")


@session_router.get("/welcome", response_class=HTMLResponse)
async def html_welcome(request: Request):
    return _render_logged_page(request, "welcome.html", "pagina_boasvindas_acessada", "welcome")


@session_router.get("/form", response_class=HTMLResponse)
async def html_form(request: Request):
    import structlog
    log = structlog.get_logger()
    sid = request.query_params.get("sid")
    if not sid:
        raise HTTPException(400, "sid ausente")
    try:
        template_name = await SessionService().open_form(sid)
        LogSender().log("servidor_form", additional={"session_id": sid}, status="SUCCESS", tags=["formulario", "pagina", "servidor"])
        context = {"encryption_enabled": settings.ENCRYPTION_ENABLED} if template_name == "form.html" else {}
        return templates.TemplateResponse(request, template_name, context)
    except HTTPException:
        raise
    except Exception as exc:
        log.error("html-render-failed", error=str(exc), page="form")
        LogSender().log("servidor_error", additional={"page": "form", "session_id": sid, "error": str(exc)}, status="ERROR", tags=["erro", "pagina", "servidor"])
        return templates.TemplateResponse(request, "error.html")


@session_router.get("/terms", response_class=HTMLResponse)
async def html_terms(request: Request):
    return _render_logged_page(request, "terms.html", "pagina_termos_acessada", "terms")



def _render_logged_page(request: Request, template_name: str, event: str, page: str):
    import structlog
    log = structlog.get_logger()
    try:
        LogSender().log(event)
        return templates.TemplateResponse(request, template_name)
    except Exception as exc:
        log.error("html-render-failed", error=str(exc), page=page)
        LogSender().log("servidor_error", additional={"page": page, "error": str(exc)}, status="ERROR", tags=["erro", "pagina", "servidor"])
        return templates.TemplateResponse(request, "error.html")
