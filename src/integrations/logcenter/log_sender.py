import json
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Union

from logcenter_sdk import LogCenterConfig, LogCenterSender
from logcenter_sdk.client import LogCenterHttpClient
from infrastructure.config import settings

BRASILIA_TZ = timezone(timedelta(hours=-3))


def _brasilia_iso() -> str:
    return datetime.now(BRASILIA_TZ).isoformat()


def _patched_headers(self: LogCenterHttpClient) -> Dict[str, str]:
    """logcenter-sdk envia 'x_api_key'; o LogCenter espera 'X-API-Key' (causa 401)."""
    headers = {"accept": "application/json", "Content-Type": "application/json"}
    if self.api_key:
        headers["X-API-Key"] = self.api_key
    return headers


LogCenterHttpClient.headers = _patched_headers


async def _patched_flush_spool(self: LogCenterSender, *, max_batches: int = 10) -> Dict[str, Any]:
    """logcenter-sdk descarta o resto do lote (até 199 itens) quando o
    primeiro envio falha, porque pop_batch já remove tudo do arquivo antes
    de tentar enviar. Aqui devolvemos ao spool o item que falhou e todos os
    que ainda não tinham sido tentados nesse lote."""
    sent = 0
    failed = 0

    for _ in range(max_batches):
        batch, _remaining = self.spool.pop_batch(self.cfg.flush_batch_size)
        if not batch:
            break

        for i, payload in enumerate(batch):
            try:
                resp = await self.http.post_log(payload)
                ok = 200 <= resp.status_code < 300
            except Exception:
                ok = False

            if ok:
                sent += 1
                continue

            failed += 1
            for pending in batch[i:]:
                self.spool.append(pending)
            return {"sent": sent, "failed": failed, "remaining": self.spool.stats().queued}

    return {"sent": sent, "failed": failed, "remaining": self.spool.stats().queued}


LogCenterSender.flush_spool = _patched_flush_spool


def _make_sender() -> LogCenterSender:
    cfg = LogCenterConfig(
        base_url=(settings.LOG_API or "").rstrip("/"),
        project_id=settings.LOG_PROJECT_ID or "",
        api_key=settings.LOG_API_KEY,
        enabled=bool(settings.LOG_API and settings.LOG_PROJECT_ID),
    )
    return LogCenterSender(cfg)


sender: LogCenterSender = _make_sender()


def _to_data(additional: Union[str, Dict[str, Any], None]) -> Optional[Dict[str, Any]]:
    if not additional:
        return None
    if isinstance(additional, dict):
        return additional
    try:
        parsed = json.loads(additional)
        if isinstance(parsed, dict):
            return parsed
    except (ValueError, TypeError):
        pass
    return {"additional": additional}


class LogSender:
    def log(self, message: str, *, additional: Union[str, Dict[str, Any], None] = None, status: Optional[str] = None, tags: Optional[List[str]] = None) -> None:
        sender.send_sync("DEBUG", message, data=_to_data(additional), status=status, tags=tags, timestamp=_brasilia_iso())
