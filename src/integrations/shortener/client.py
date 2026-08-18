import time
import asyncio
import httpx
import structlog
from typing import Tuple
from pydantic import HttpUrl
from integrations.shortener.schemas import ShortenerLoginResponse, ShortenerCreateResponse
from infrastructure.config import settings

log = structlog.get_logger()

_token_lock = asyncio.Lock()
_token_value: str | None = None
_token_expiry_epoch: float = 0.0

async def _login(client: httpx.AsyncClient) -> Tuple[str, float]:
    """Efetua login no encurtador e retorna (token, expiry_epoch)."""
    url = f"{settings.SHORTENER_BASE_URL.rstrip('/')}/auth/login"

    form = {
        "username": settings.SHORTENER_USER,
        "password": settings.SHORTENER_PASSWORD,
        "grant_type": "password",
    }

    try:
        r = await client.post(
            url, data=form,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=15.0,
        )
        r.raise_for_status()
    except httpx.HTTPStatusError as e:
        err_text = e.response.text if e.response is not None else str(e)
        log.error("shortener-login-failed", status=e.response.status_code if e.response else None, body=err_text)
        raise

    data = ShortenerLoginResponse(**r.json())
    now = time.time()
    expiry = now + max(1, int(data.expiresIn * 0.9))  # margem de segurança
    log.info("shortener-login-ok", expiresIn=data.expiresIn)
    return data.accessToken, expiry

async def _ensure_token(client: httpx.AsyncClient) -> str:
    global _token_value, _token_expiry_epoch
    now = time.time()
    if _token_value and now < _token_expiry_epoch:
        return _token_value

    async with _token_lock:
        now = time.time()
        if _token_value and now < _token_expiry_epoch:
            return _token_value
        token, expiry = await _login(client)
        _token_value = token
        _token_expiry_epoch = expiry
        return _token_value

async def create_short_link(
    long_url: str,
    *,
    session_id: str | None = None,
    name: str | None = None,
    callback_url: str | None = None,
    slug: str | None = None,
):
    """
    Cria link curto + QR no encurtador autenticado.
    Retorna: (ShortenerCreateResponse, short_url)
    """
    async with httpx.AsyncClient() as client:
        token = await _ensure_token(client)
        url = f"{settings.SHORTENER_BASE_URL.rstrip('/')}/admin/shorten"
        headers = {"Authorization": f"Bearer {token}"}

        form = {
            "name": (name or f"MACHINE session {session_id or ''}").strip(),
            "url": long_url,
        }
        if callback_url:
            form["callback_url"] = callback_url
        if slug:
            form["slug"] = slug

        r = await client.post(url, data=form, headers=headers, timeout=15.0)
        if r.status_code == 401:
            log.warning("shortener-unauthorized-retrying")
            # invalida cache e reloga
            global _token_value, _token_expiry_epoch
            _token_value, _token_expiry_epoch = None, 0
            token = await _ensure_token(client)
            headers["Authorization"] = f"Bearer {token}"
            r = await client.post(url, data=form, headers=headers, timeout=15.0)

        r.raise_for_status()
        data = ShortenerCreateResponse(**r.json())
        short_url = f"{settings.SHORTENER_BASE_URL.rstrip('/')}/{data.slug}"
        HttpUrl(short_url)  # validação leve

        log.info("shortener-create-ok", slug=data.slug)
        return ShortenerCreateResponse(
            slug=data.slug,
            qr_png=data.qr_png,
            qr_svg=data.qr_svg,
        ), short_url
