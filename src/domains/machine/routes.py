import secrets
import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from pathlib import Path

from infrastructure.config import settings
from integrations.logcenter.log_sender import LogSender
from .schemas import DropRequest, SerialMessageRequest, DropValueRequest
from .services import InventoryService, MachineService

_security = HTTPBasic()
_ADMIN_HTML = Path(__file__).resolve().parents[2] / "static" / "sample" / "html" / "admin.html"


def _admin_auth(credentials: HTTPBasicCredentials = Depends(_security)):
    ok_user = secrets.compare_digest(credentials.username, settings.SAMPLE_ADMIN_USER)
    ok_pass = secrets.compare_digest(credentials.password, settings.SAMPLE_ADMIN_PASSWORD)
    if not (ok_user and ok_pass):
        raise HTTPException(401, "Credenciais inválidas", headers={"WWW-Authenticate": "Basic"})

log = structlog.get_logger()
router = APIRouter(prefix="/api/sample")


def _verify_drop_code(drop_code: str) -> None:
    if drop_code != settings.DROP_CODE:
        raise HTTPException(403, "Drop code inválido")


@router.get("/admin", dependencies=[Depends(_admin_auth)])
async def admin_page():
    return FileResponse(_ADMIN_HTML)


@router.post("/drop")
async def drop(payload: DropRequest):
    _verify_drop_code(payload.drop_code)
    try:
        await MachineService().drop()
        return {"status": "drop_sent"}
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(500, "Erro interno do servidor")


@router.post("/drop/wait")
async def drop_waiting_callback(payload: DropRequest):
    _verify_drop_code(payload.drop_code)
    try:
        status = await MachineService().drop_waiting_callback()
        return {"status": status}
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(500, "Erro interno do servidor")


@router.post("/drop/value")
async def drop_value(payload: DropValueRequest):
    _verify_drop_code(payload.drop_code)
    try:
        result = await MachineService().drop_value(payload.quantity, payload.timeout_seconds)
        return result
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(500, "Erro interno do servidor")


@router.post("/serial")
async def send_serial_message(payload: SerialMessageRequest):
    _verify_drop_code(payload.drop_code)
    try:
        return await MachineService().send_serial_message(
            message=payload.message,
            timeout_seconds=payload.timeout_seconds,
        )
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(500, "Erro interno do servidor")


@router.get("/on")
async def machine_on():
    try:
        return await MachineService().turn_on()
    except Exception:
        raise HTTPException(500, "Erro interno do servidor")


@router.get("/off")
async def machine_off():
    try:
        return await MachineService().turn_off()
    except Exception:
        raise HTTPException(500, "Erro interno do servidor")


@router.post("/admin/dispense", dependencies=[Depends(_admin_auth)])
async def admin_dispense(request: Request):
    body = await request.json()
    message = str(body.get("message", "")).strip()
    if not message:
        raise HTTPException(400, "Campo 'message' obrigatório")
    try:
        return await MachineService().admin_dispense(message)
    except Exception:
        raise HTTPException(500, "Erro interno do servidor")


@router.post("/admin/serial/inject", dependencies=[Depends(_admin_auth)])
async def admin_serial_inject(request: Request):
    if not settings.SERIAL_FAKE:
        raise HTTPException(400, "Disponível apenas com SERIAL_FAKE=true")
    body = await request.json()
    message = str(body.get("message", "")).strip()
    if not message:
        raise HTTPException(400, "Campo 'message' obrigatório")
    from .services import get_serial_comm
    get_serial_comm().inject(message)
    return {"status": "injected", "message": message}


@router.get("/admin/inventory")
async def get_inventory():
    try:
        return InventoryService().repository.load()
    except Exception as exc:
        log.error("admin-inventory-get-error", error=str(exc))
        raise HTTPException(500, "Erro interno do servidor")


@router.post("/admin/inventory")
async def update_inventory(request: Request):
    try:
        return await InventoryService().update(await request.json(), LogSender())
    except Exception as exc:
        log.error("admin-inventory-error", error=str(exc))
        raise HTTPException(500, "Erro interno do servidor")
