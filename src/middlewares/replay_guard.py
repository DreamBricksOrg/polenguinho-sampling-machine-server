# src/middlewares/replay_guard.py
import time
import hashlib
import structlog
from starlette.types import ASGIApp, Receive, Scope, Send
from starlette.responses import JSONResponse
from starlette.requests import Request

log = structlog.get_logger()

class ReplayGuardMiddleware:
    """
    Bloqueia replays rápidos do mesmo request (IP + path + query + body) por uma janela (TTL) em segundos.
    Escopo: instância do processo (memória local).
    """
    def __init__(self, app: ASGIApp, ttl_seconds: int = 5, protected_paths: tuple[str, ...] = (
        "/api/sample/session/complete",
        "/api/sample/form",
    )):
        self.app = app
        self.ttl = ttl_seconds
        self.protected_paths = protected_paths
        self._seen: dict[str, float] = {}  # key -> last_seen_epoch

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        request = Request(scope, receive=receive)

        # só protege paths específicos
        if request.url.path not in self.protected_paths:
            return await self.app(scope, receive, send)

        # extrai IP
        client_ip = (
            request.headers.get("x-forwarded-for", "")
            .split(",")[0]
            .strip()
            or request.headers.get("x-real-ip", "")
            or (request.client.host if request.client else "unknown")
        )

        # lê body de forma segura (vamos reinjetar depois)
        raw_body = await request.body()

        # monta chave única (IP + path + query + hash(body))
        key_base = f"{client_ip}|{request.method}|{str(request.url.path)}|{request.url.query}"
        body_hash = hashlib.sha256(raw_body).hexdigest() if raw_body else "-"
        k = f"{key_base}|{body_hash}"

        now = time.time()
        # limpeza leve (best-effort)
        if len(self._seen) > 2000:
            expired = [kk for kk, ts in self._seen.items() if now - ts > self.ttl]
            for kk in expired:
                self._seen.pop(kk, None)

        last = self._seen.get(k)
        if last is not None and (now - last) < self.ttl:
            log.warning("replay-guard-hit", ip=client_ip, path=str(request.url.path),
                        query=request.url.query, since=now - last)
            response = JSONResponse(
                {"detail": "Ação repetida muito rápido. Tente novamente em alguns segundos."},
                status_code=429,
            )
            await response(scope, receive, send)
            return

        # registra primeira vez
        self._seen[k] = now

        # reinjeta o body para downstream
        async def _receive() -> dict:
            return {"type": "http.request", "body": raw_body, "more_body": False}

        # segue o fluxo
        return await self.app(scope, _receive, send)
