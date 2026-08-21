import asyncio
import hashlib
import secrets
import uuid
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

import structlog
from fastapi import HTTPException
from pydantic import EmailStr
from pymongo.errors import DuplicateKeyError

from infrastructure.config import settings
from integrations.logcenter.log_sender import LogSender
from infrastructure.hardware.udp_sender import UDPSender
from .schemas import (
    QRCodeInitResponse,
    SessionCompleteRequest,
    SessionCompleteResponse,
    SessionGetResponse,
    SessionPickupRequest,
    SessionPickupResponse,
    SessionTermsRequest,
    SessionTermsResponse,
    UserGetResponse,
    UserInitRequest,
    UserInitResponse,
    UserPickupRequest,
    UserPickupResponse,
    UserUpdateRequest,
)
from .repositories import DEFAULT_COLLECTION, SessionRepository, UserRepository

log = structlog.get_logger()
_udp_sender: UDPSender | None = None


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def now_saopaulo() -> datetime:
    return datetime.now(ZoneInfo("America/Sao_Paulo"))


PICKUP_BLOCK_COOKIE_NAME = "sample_pickup_block"


def build_pickup_block_cookie_value(session_id: str, now: datetime) -> str:
    return f"{session_id}:{int(now.timestamp())}"


def is_ip_blocked(doc: dict | None, now: datetime, hours: float) -> bool:
    if not doc:
        return False
    last_pickup_at = doc.get("last_pickup_at")
    if not last_pickup_at:
        return False
    elapsed_seconds = (now - as_utc(last_pickup_at)).total_seconds()
    return 0 <= elapsed_seconds < hours * 3600


def parse_pickup_cookie(cookie_value: str | None) -> tuple[str, int] | None:
    """Devolve (session_id, timestamp) do cookie, ou None se estiver corrompido."""
    if not cookie_value:
        return None
    try:
        session_id, ts_str = cookie_value.rsplit(":", 1)
        return session_id, int(ts_str)
    except (ValueError, AttributeError):
        return None


def _within_window(ts: int, now: datetime, hours: float) -> bool:
    return 0 <= now.timestamp() - ts < hours * 3600


def is_pickup_blocked(cookie_value: str | None, now: datetime, hours: float) -> bool:
    parsed = parse_pickup_cookie(cookie_value)
    return bool(parsed) and _within_window(parsed[1], now, hours)


def is_within_recall_window(cookie_value: str | None, now: datetime, hours: float) -> bool:
    """O cookie sobrevive ao bloqueio: a janela de reconhecimento é mais longa
    que a de bloqueio, e é o que permite pular o form de quem já se cadastrou."""
    parsed = parse_pickup_cookie(cookie_value)
    return bool(parsed) and _within_window(parsed[1], now, hours)


def is_within_business_hours(now: datetime, timezone_name: str, open_hour: int, close_hour: int) -> bool:
    """Abertura e fechamento zerados desligam a checagem — atende sempre.

    Sem essa saída, `0 <= hora < 0` nunca é verdade e a máquina ficaria
    permanentemente fechada, que é o oposto de desligar a restrição."""
    if open_hour == 0 and close_hour == 0:
        return True
    local_hour = now.astimezone(ZoneInfo(timezone_name)).hour
    return open_hour <= local_hour < close_hour


def get_udp_sender() -> UDPSender:
    global _udp_sender
    if _udp_sender is None:
        _udp_sender = UDPSender(port=settings.UDP_PORT)
    return _udp_sender


class SessionService:
    def __init__(self, session_repository: SessionRepository | None = None):
        self.sessions = session_repository or SessionRepository()

    async def init_qrcode(self) -> QRCodeInitResponse:
        session_id = str(uuid.uuid4())
        slug = secrets.token_urlsafe(6)
        long_url = f"{settings.CADASTRO_BASE_URL}?sid={session_id}&slug={slug}"

        doc = {
            "_id": session_id,
            "slug": slug,
            "short_url": long_url,
            "long_url": long_url,
            "mode": "with_forms",
            "status": "pending",
            "retire_sent": False,
            "processing": False,
            "created_at": now_utc(),
            "form_opened_at": None,
            "processing_started_at": None,
            "completed_at": None,
        }
        await self.sessions.create(doc)
        log.info("sample-session-created", session_id=session_id, long_url=long_url)
        return QRCodeInitResponse(
            session_id=session_id,
            long_url=long_url,
            short_url=long_url,
            slug=slug,
        )

    async def get_session_info(self, sid: str) -> SessionGetResponse:
        session = await self.sessions.find(sid)
        if not session:
            raise HTTPException(status_code=404, detail="Sessão inválida ou expirada")
        return SessionGetResponse(
            session_id=session["_id"],
            slug=session["slug"],
            status=session["status"],
            mode=session.get("mode"),
            short_url=session.get("short_url"),
            created_at=session.get("created_at"),
            form_opened_at=session.get("form_opened_at"),
            terms_accepted_at=session.get("terms_accepted_at"),
            processing_started_at=session.get("processing_started_at"),
            completed_at=session.get("completed_at"),
        )

    async def accept_terms(self, req: SessionTermsRequest) -> SessionTermsResponse:
        """Marca a sessão como terms_accepted após o envio do formulário."""
        link = {k: v for k, v in (("user_id", req.user_id), ("collection", req.collection)) if v}
        doc = await self.sessions.try_mark_terms_accepted(req.session_id, now_utc(), link)
        if doc:
            log.info("session-terms-accepted", session_id=req.session_id)
            LogSender().log(
                "termos_aceitos",
                additional={"session_id": req.session_id},
                status="SUCCESS",
                tags=["formulario", "termos", "servidor"],
            )
            return SessionTermsResponse(status=doc["status"], session_id=req.session_id)

        session = await self.sessions.find(req.session_id)
        if not session:
            raise HTTPException(404, "Sessão inválida ou expirada")
        if session["status"] == "terms_accepted":
            # reenvio/refresh do form: idempotente
            return SessionTermsResponse(status="terms_accepted", session_id=req.session_id)
        raise HTTPException(409, "Sessão já encerrada ou em processamento")

    async def complete_session(self, req: SessionCompleteRequest) -> SessionCompleteResponse:
        doc = await self.sessions.try_start_processing(req.session_id, req.slug, now_utc())
        if not doc:
            session = await self.sessions.find(req.session_id)
            if not session:
                raise HTTPException(404, "Sessão inválida ou expirada")
            if session.get("slug") != req.slug:
                raise HTTPException(400, "Slug não corresponde à sessão")
            raise HTTPException(409, "Sessão já encerrada ou em processamento")

        LogSender().log("sessao_concluida")
        # Mesmo ciclo do modo QR estático ("on" → "1" → "off"): espera até
        # PICKUP_TIMEOUT_SECONDS pela retirada, muito além do timeout do
        # RESULTADO.cs. Roda em background e o celular acompanha o desfecho
        # pelo polling de /session/{sid}, como o continue.html já faz.
        asyncio.create_task(self._run_pickup(req.session_id))
        return SessionCompleteResponse(status="processing", session_id=req.session_id)

    async def recall_user(self, cookie_value: str | None, sid: str) -> dict | None:
        """Reaproveita o cadastro de quem já passou por aqui.

        O cookie guarda a sessão anterior; ela guarda o user_id desde o aceite
        do formulário. Reconhecendo a pessoa, amarramos o mesmo usuário à sessão
        nova e a marcamos como terms_accepted — que é o sinal pelo qual o
        TERMOS.cs libera o totem para o jogo. Devolve a sessão atualizada, ou
        None quando não dá para reconhecer (e aí o formulário aparece normal)."""
        now = now_utc()

        if not is_within_recall_window(cookie_value, now, settings.USER_RECALL_HOURS):
            return None

        previous_sid = parse_pickup_cookie(cookie_value)[0]
        previous = await self.sessions.find(previous_sid)
        user_id = (previous or {}).get("user_id")
        collection = (previous or {}).get("collection")
        if not user_id or not collection:
            log.info("recall-no-user-linked", session_id=sid, previous_session_id=previous_sid)
            return None

        user = await UserRepository(collection).find_by_id(user_id)
        if not user:
            log.warning("recall-user-missing", session_id=sid, user_id=user_id, collection=collection)
            return None

        # O cooldown do cadastro continua valendo: reconhecer alguém não é
        # autorizar uma retirada fora da janela. Sem recall, cai no formulário
        # e o create_user devolve o 429 de sempre.
        can_pick_from = user.get("canPickFrom")
        if can_pick_from and now < as_utc(can_pick_from):
            log.info("recall-cooldown-active", session_id=sid, user_id=user_id, can_pick_from=str(can_pick_from))
            return None

        doc = await self.sessions.try_mark_terms_accepted(
            sid,
            now,
            {"user_id": user_id, "collection": collection, "recalled_from": previous_sid},
        )
        if not doc:
            log.warning("recall-session-not-markable", session_id=sid, user_id=user_id)
            return None

        log.info("recall-user-applied", session_id=sid, previous_session_id=previous_sid, user_id=user_id)
        LogSender().log(
            "cadastro_reaproveitado",
            additional={"session_id": sid, "previous_session_id": previous_sid, "id": user_id},
            status="SUCCESS",
            tags=["formulario", "recall", "servidor"],
        )
        return doc

    async def open_form(self, sid: str) -> str:
        session = await self.sessions.find(sid)
        if not session:
            log.error("html-session-expired", page="form")
            return "error.html"
        if session["status"] in ("processing", "completed", "failed", "aborted"):
            log.error("html-session-used", page="form", status=session["status"])
            raise HTTPException(404, "Sessão Inválida.")

        updated = await self.sessions.try_mark_form_opened(sid, now_utc())
        if updated:
            log.info("form-opened-first-time", session_id=sid)
            LogSender().log("pagina_formulario_acessada")
            get_udp_sender().send("next")
        else:
            # refresh com status form_shown: reexibe o form sem reenviar UDP
            log.info("form-reopened", session_id=sid, status=session["status"])
        return "form.html"

    async def init_static_session(self) -> dict:
        session_id = str(uuid.uuid4())
        doc = {
            "_id": session_id,
            "slug": secrets.token_urlsafe(6),
            "short_url": None,
            "mode": "qrcode_static",
            "status": "pending",
            "retire_sent": False,
            "processing": False,
            "created_at": now_utc(),
            "form_opened_at": None,
            "processing_started_at": None,
            "completed_at": None,
        }
        await self.sessions.create(doc)
        log.info("static-session-created", session_id=session_id)
        LogSender().log(
            "sessao_qrcode_estatico_iniciada",
            additional={"session_id": session_id, "slug": doc["slug"]},
            status="SUCCESS",
            tags=["qrcode_estatico", "inicio", "servidor"],
        )
        return doc

    async def start_pickup(self, req: SessionPickupRequest) -> SessionPickupResponse:
        doc = await self.sessions.try_start_processing(req.session_id, req.slug, now_utc())
        if not doc:
            session = await self.sessions.find(req.session_id)
            if not session:
                raise HTTPException(404, "Sessão inválida ou expirada")
            if session.get("slug") != req.slug:
                raise HTTPException(400, "Slug não corresponde à sessão")
            raise HTTPException(409, "Sessão já encerrada ou em processamento")

        LogSender().log("retirada_iniciada")
        asyncio.create_task(self._run_pickup(req.session_id))
        return SessionPickupResponse(status="processing", session_id=req.session_id)

    async def _run_pickup(self, session_id: str) -> None:
        from domains.machine.services import MachineService

        status_final = "failed"
        try:
            status_final = await MachineService().pickup_cycle()
        except Exception as exc:
            log.error("pickup-task-error", error=str(exc), session_id=session_id)
        finally:
            await self.sessions.finalize(session_id, status_final, now_utc())
            log.info("session-finalized", session_id=session_id, status=status_final)
            if status_final == "completed":
                await self._mark_user_pickup(session_id)

    async def _mark_user_pickup(self, session_id: str) -> None:
        """Registra no cadastro que o brinde saiu. Só roda depois da confirmação
        da máquina — antes disso o usuário está cadastrado, não atendido."""
        session = await self.sessions.find(session_id)
        user_id = (session or {}).get("user_id")
        collection = (session or {}).get("collection")

        if not user_id or not collection:
            log.warning("pickup-user-link-missing", session_id=session_id, user_id=user_id, collection=collection)
            return

        now = now_utc()
        try:
            updated = await UserRepository(collection).mark_session_pickup(
                user_id,
                session_id,
                now,
                now + timedelta(hours=settings.PICKUP_COOLDOWN_HOURS),
            )
        except Exception as exc:
            log.error("pickup-user-mark-error", error=str(exc), session_id=session_id, user_id=user_id)
            return

        if not updated:
            log.warning("pickup-user-not-marked", session_id=session_id, user_id=user_id, collection=collection)
            return

        log.info(
            "pickup-user-marked",
            session_id=session_id,
            user_id=user_id,
            collection=collection,
            products_picked=updated.get("productsPicked"),
        )
        LogSender().log(
            "retirada_registrada_no_cadastro",
            additional={"session_id": session_id, "id": user_id, "products_picked": updated.get("productsPicked")},
            status="SUCCESS",
            tags=["retirada", "cadastro", "servidor"],
        )


def email_hash(email: str) -> str:
    return hashlib.sha256(str(email).strip().lower().encode()).hexdigest()


def as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def start_of_day_utc(value) -> datetime:
    if not value:
        value = now_utc()
    elif isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except ValueError:
            raise HTTPException(status_code=400, detail="Formato de 'day' inválido (use YYYY-MM-DD)")
    elif isinstance(value, date) and not isinstance(value, datetime):
        value = datetime.combine(value, time.min)

    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.replace(hour=0, minute=0, second=0, microsecond=0)


def user_response(doc: dict) -> UserGetResponse:
    return UserGetResponse(
        id=doc["_id"],
        name=doc.get("name"),
        email=doc["email"],
        phone=doc.get("phone"),
        status=doc.get("status", "registered"),
        registerDay=doc["registerDay"],
        canPickFrom=doc["canPickFrom"],
        pickedDay=doc.get("pickedDay"),
        productsPicked=doc.get("productsPicked", 0),
    )


class UserService:
    def __init__(self, repository: UserRepository):
        self.repository = repository

    @classmethod
    def for_collection(cls, collection: str = DEFAULT_COLLECTION) -> "UserService":
        return cls(UserRepository(collection))

    async def create_user(self, payload: UserInitRequest) -> UserInitResponse:
        repo = self.repository.primary()
        try:
            await repo.ensure_unique_email_index()
        except Exception as exc:
            log.warning("ensure-unique-email-index-failed", error=str(exc))

        if payload.encrypted and not settings.ENCRYPTION_ENABLED:
            raise HTTPException(status_code=400, detail="Criptografia desabilitada neste servidor")

        now = now_utc()
        cooldown = timedelta(hours=settings.PICKUP_COOLDOWN_HOURS)

        if payload.encrypted:
            # com criptografia ativa, name/email/phone chegam cifrados do navegador
            # (RSA+AES); o emailHash é calculado no cliente a partir do e-mail em
            # texto puro e é a única forma de dedup possível nesse modo.
            ehash = payload.emailHash
            name_value = payload.encName
            email_value = payload.encEmail
            phone_value = payload.encPhone
            log_name, log_email, log_phone = "***criptografado***", "***criptografado***", "***criptografado***"
            dedup_query = {"emailHash": ehash}
        else:
            email_lower = str(payload.email).lower()
            ehash = email_hash(email_lower)
            name_value = payload.name
            email_value = email_lower
            phone_value = payload.phone
            log_name, log_email, log_phone = payload.name, email_lower, payload.phone
            dedup_query = {"$or": [{"emailHash": ehash}, {"email": email_lower}]}

        existing = await repo.find_one(dedup_query)
        if existing:
            last_pick = existing.get("lastPick")
            if last_pick:
                can_pick_at = as_utc(last_pick) + cooldown
                if now < can_pick_at:
                    log.warning(
                        "pickup-cooldown-active",
                        id=existing["_id"],
                        last_pick=str(last_pick),
                        can_pick_at=str(can_pick_at),
                        collection=repo.collection_name,
                    )
                    LogSender().log(
                        "envio_formulario_bloqueado_cooldown",
                        additional={
                            "id": existing["_id"],
                            "email": log_email,
                            "can_pick_at": can_pick_at.isoformat(),
                        },
                        status="ERROR",
                        tags=["formulario", "cadastro", "cooldown", "servidor"],
                    )
                    raise HTTPException(
                        status_code=429,
                        detail=f"Aguarde até {can_pick_at.isoformat()} para retirar novamente",
                    )

            # name/phone são opcionais: só sobrescreve o que veio preenchido,
            # para não apagar dados de um cadastro anterior mais completo.
            # lastPick/canPickFrom NÃO entram aqui: quem os grava é a
            # confirmação da máquina, senão um cadastro abandonado já bloquearia
            # a pessoa sem ela ter recebido nada.
            pick_fields = {
                "emailHash": ehash,
                "updatedAt": now,
            }
            if name_value:
                pick_fields["name"] = name_value
            if phone_value:
                pick_fields["phone"] = phone_value

            updated = await repo.update_fields({"_id": existing["_id"]}, pick_fields)
            log.info("user-repick", id=existing["_id"], collection=repo.collection_name)
            LogSender().log(
                "formulario_enviado",
                additional={
                    "id": existing["_id"],
                    "name": log_name,
                    "email": log_email,
                    "phone": log_phone,
                    "code": payload.code,
                    "repick": True,
                },
                status="SUCCESS",
                tags=["formulario", "cadastro", "retirada_repetida", "servidor"],
            )
            return UserInitResponse(
                id=updated["_id"],
                name=updated.get("name"),
                email=updated["email"],
                status=updated.get("status", "registered"),
                registerDay=updated["registerDay"],
                canPickFrom=updated["canPickFrom"],
            )

        reg_id = str(uuid.uuid4())
        register_day = payload.registerDay or now
        doc = {
            "_id": reg_id,
            "code": payload.code,
            "name": name_value,
            "email": email_value,
            "emailHash": ehash,
            "phone": phone_value,
            "registerDay": register_day,
            # Recém-cadastrado pode retirar agora: o cooldown só começa a contar
            # quando a máquina confirmar que o brinde saiu.
            "canPickFrom": now,
            "status": "registered",
            "createdAt": now,
            "updatedAt": now,
            "pickedDay": None,
            "productsPicked": 0,
            "pickHistory": [],
            "lastPick": None,
        }

        try:
            await repo.create(doc)
        except DuplicateKeyError:
            log.warning("email-race-duplicate", email=log_email, collection=repo.collection_name)
            raise HTTPException(status_code=429, detail="Cadastro em andamento, tente novamente")

        log.info("user-created", id=reg_id, collection=repo.collection_name)
        LogSender().log(
            "formulario_enviado",
            additional={
                "id": reg_id,
                "name": log_name,
                "email": log_email,
                "phone": log_phone,
                "code": doc["code"],
                "repick": False,
            },
            status="SUCCESS",
            tags=["formulario", "cadastro", "servidor"],
        )
        return UserInitResponse(
            id=reg_id,
            name=doc.get("name"),
            email=doc["email"],
            status=doc["status"],
            registerDay=doc["registerDay"],
            canPickFrom=doc["canPickFrom"],
        )

    async def list_users(self) -> list[UserGetResponse]:
        users = await self.repository.list()
        result = [user_response(user) for user in users]
        log.info("users-listed", count=len(result), collection=self.repository.collection_name)
        return result

    async def get_user(self, user_id: str) -> UserGetResponse:
        user = await self.repository.find_by_id(user_id)
        if not user:
            log.warning("user-not-found", user_id=user_id, collection=self.repository.collection_name)
            raise HTTPException(status_code=404, detail="Registro não encontrado")
        return user_response(user)

    async def get_user_by_email(self, email: EmailStr) -> UserGetResponse:
        user = await self.repository.find_by_email(str(email))
        if not user:
            log.warning("email-not-found", email=email, collection=self.repository.collection_name)
            raise HTTPException(status_code=404, detail="Registro não encontrado")
        return user_response(user)

    async def update_user(self, user_id: str, update: UserUpdateRequest) -> UserGetResponse:
        fields = {}
        if update.name is not None:
            fields["name"] = update.name
        if not fields:
            raise HTTPException(status_code=400, detail="Nada para atualizar")

        fields["updatedAt"] = now_utc()
        user = await self.repository.update_name(user_id, fields)
        if not user:
            log.warning("user-update-not-found", user_id=user_id, collection=self.repository.collection_name)
            raise HTTPException(status_code=404, detail="Registro não encontrado")
        return user_response(user)

    async def delete_user(self, user_id: str) -> dict:
        deleted = await self.repository.delete(user_id)
        if deleted == 0:
            log.warning("user-delete-not-found", user_id=user_id, collection=self.repository.collection_name)
            raise HTTPException(status_code=404, detail="Registro não encontrado")
        return {"detail": "Registro removido com sucesso"}

    async def register_pickup(self, payload: UserPickupRequest) -> UserPickupResponse:
        from domains.machine.services import MachineService

        if not payload.id and not payload.email:
            raise HTTPException(status_code=400, detail="Informe id ou email")

        query = {"_id": payload.id} if payload.id else {"email": str(payload.email).lower()}
        user = await self.repository.find_one(query)
        if not user:
            log.warning("user-pickup-not-found", query=query, collection=self.repository.collection_name)
            raise HTTPException(status_code=404, detail="Registro não encontrado")

        day_dt = start_of_day_utc(payload.day)
        prev_pick = user.get("pickedDay")
        prev_picked_dt = start_of_day_utc(prev_pick) if prev_pick else None

        if prev_picked_dt is not None and prev_picked_dt.date() == day_dt.date():
            raise HTTPException(status_code=409, detail="Retirada já registrada para este dia")

        cycle_status = await MachineService().pickup_cycle()
        if cycle_status != "completed":
            log.warning(
                "user-pickup-not-confirmed",
                query=query,
                cycle_status=cycle_status,
                collection=self.repository.collection_name,
            )
            raise HTTPException(status_code=502, detail="Retirada não confirmada pela máquina")

        next_can_pick_dt = start_of_day_utc(day_dt + timedelta(days=1))
        modified = await self.repository.register_pickup(
            query,
            day_dt,
            int(payload.productsPicked),
            next_can_pick_dt,
            now_utc(),
        )
        if modified == 0:
            raise HTTPException(status_code=409, detail="Retirada já registrada para este dia")

        updated = await self.repository.find_one(query)
        log.info(
            "user-picked",
            id=updated["_id"],
            day=str(day_dt.date()),
            qty=int(updated.get("productsPicked", 0)),
            next_can_pick=str(next_can_pick_dt.date()),
            collection=self.repository.collection_name,
        )
        return UserPickupResponse(
            id=updated["_id"],
            email=updated["email"],
            pickedDay=day_dt,
            productsPicked=int(updated.get("productsPicked", 0)),
            status=updated.get("status", "picked"),
        )

    async def refresh_eligibility(self) -> dict:
        result = await self.repository.refresh_eligibility(now_utc(), now_utc())
        log.info(
            "eligibility-refreshed",
            matched=result.matched_count,
            modified=result.modified_count,
            collection=self.repository.collection_name,
        )
        return {"matched": result.matched_count, "modified": result.modified_count}
