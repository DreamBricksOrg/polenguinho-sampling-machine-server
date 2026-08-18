# Modo QR Code Estático — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fluxo de retirada com QR estático: sessão criada via redirect, ciclo on → espera serial `"1"` → off rodando em task background no servidor, com decremento de inventário e polling do navegador.

**Architecture:** Estende os domínios existentes (`users` para sessão/rotas, `machine` para hardware). Novo `MachineService.pickup_cycle()` roda sob `serial_lock` em `asyncio.create_task` disparada por `POST /api/sample/session/pickup`; a sessão reusa a máquina de estados atômica do Mongo (`pending → form_shown → processing → completed|failed`). `claim.html` ramifica pelo novo campo `mode` da sessão.

**Tech Stack:** FastAPI, Motor (MongoDB), pyserial, pytest + pytest-asyncio.

**Spec:** `docs/superpowers/specs/2026-07-16-static-qrcode-flow-design.md`

---

## Contexto para quem nunca viu o repo

- Código em `src/`, imports absolutos a partir de `src` (ex.: `from infrastructure.config import settings`). Testes precisam de `pythonpath = src`.
- `src/infrastructure/config.py` valida env na importação (exige `BASE_URL`, `MONGO_URI`, `DROP_CODE`; com `USE_FORM=true` exige também as vars do encurtador). Existe `.env` na raiz que o `pydantic-settings` carrega. O conftest garante defaults para rodar sem `.env`.
- `SerialComm` (`src/infrastructure/hardware/serial_comm.py`) abre a porta COM real no construtor — **testes nunca podem chamar `get_serial_comm()` de verdade**; injete o fake no global `_serial_comm` de `domains.machine.services`.
- `LogSender().log(...)` envia log para serviço externo — substitua por fake nos testes.
- Não existe pasta `tests/` ainda; a Task 1 cria a infra.
- Rodar testes: `python -m pytest tests -v` a partir da raiz do repo.

---

### Task 1: Infra de testes (pytest.ini + conftest)

**Files:**
- Create: `pytest.ini`
- Create: `tests/__init__.py` (vazio)
- Create: `tests/conftest.py`

- [ ] **Step 1: Criar `pytest.ini`**

```ini
[pytest]
pythonpath = src
asyncio_mode = auto
testpaths = tests
```

- [ ] **Step 2: Criar `tests/__init__.py` vazio e `tests/conftest.py`**

```python
import os

# Defaults para o Settings importar sem .env completo (não sobrescreve valores reais)
os.environ.setdefault("BASE_URL", "http://localhost:8000")
os.environ.setdefault("MONGO_URI", "mongodb://localhost:27017")
os.environ.setdefault("MONGO_DB", "test_db")
os.environ.setdefault("DROP_CODE", "test-drop-code")
os.environ.setdefault("USE_FORM", "false")
```

- [ ] **Step 3: Verificar que o pytest coleta sem erro**

Run: `python -m pytest tests -v`
Expected: `no tests ran` (exit code 5, sem erros de import)

- [ ] **Step 4: Commit**

```bash
git add pytest.ini tests/
git commit -m "test: infraestrutura pytest (pythonpath src, env defaults)"
```

---

### Task 2: Config `PICKUP_TIMEOUT_SECONDS` + `MachineService.pickup_cycle`

**Files:**
- Modify: `src/infrastructure/config.py` (bloco `# Machine`, ~linha 64)
- Modify: `src/domains/machine/services.py` (novo método em `MachineService`)
- Test: `tests/test_pickup_cycle.py`

- [ ] **Step 1: Escrever os testes que falham**

```python
import asyncio

import pytest

import domains.machine.services as machine_services
from domains.machine.services import MachineService


class FakeSerial:
    """Serial fake: devolve respostas roteirizadas, grava tudo que foi enviado."""

    def __init__(self, responses=None, fail_on_send=None):
        self.responses = list(responses or [])
        self.sent = []
        self.fail_on_send = fail_on_send  # mensagem que dispara exceção ao enviar

    def send(self, msg):
        if self.fail_on_send == msg:
            raise RuntimeError("serial quebrada")
        self.sent.append(msg)

    def receive(self):
        return self.responses.pop(0) if self.responses else None


class FakeInventory:
    def __init__(self):
        self.drops = 0

    async def update_on_drop(self):
        self.drops += 1
        return True


class FakeLogSender:
    def log(self, *args, **kwargs):
        pass


@pytest.fixture
def fake_serial(monkeypatch):
    fake = FakeSerial()
    monkeypatch.setattr(machine_services, "_serial_comm", fake)
    monkeypatch.setattr(machine_services, "LogSender", FakeLogSender)
    return fake


def make_service():
    inventory = FakeInventory()
    return MachineService(inventory_service=inventory), inventory


async def test_pickup_settings_default():
    from infrastructure.config import settings
    assert settings.PICKUP_TIMEOUT_SECONDS == 60


async def test_pickup_completed_decrementa_inventario(fake_serial):
    fake_serial.responses = ["on", "1"]
    service, inventory = make_service()
    status = await service.pickup_cycle(timeout_seconds=2)
    assert status == "completed"
    assert inventory.drops == 1
    assert fake_serial.sent == ["on", "off"]


async def test_pickup_timeout_envia_off(fake_serial):
    fake_serial.responses = ["on"]  # nunca chega "1"
    service, inventory = make_service()
    status = await service.pickup_cycle(timeout_seconds=0.3)
    assert status == "failed"
    assert inventory.drops == 0
    assert fake_serial.sent == ["on", "off"]


async def test_pickup_ignora_mensagens_diferentes_de_1(fake_serial):
    fake_serial.responses = ["on", "dropped", "lixo", "1"]
    service, inventory = make_service()
    status = await service.pickup_cycle(timeout_seconds=2)
    assert status == "completed"
    assert inventory.drops == 1


async def test_pickup_sem_confirmacao_on_continua(fake_serial):
    # Arduino não responde "on", mas envia "1" depois — ciclo completa mesmo assim
    fake_serial.responses = [None, None, "1"]
    service, inventory = make_service()
    status = await service.pickup_cycle(timeout_seconds=2, on_timeout_seconds=0.3)
    assert status == "completed"
    assert inventory.drops == 1


async def test_pickup_excecao_retorna_failed_e_tenta_off(fake_serial):
    fake_serial.fail_on_send = "on"
    service, inventory = make_service()
    status = await service.pickup_cycle(timeout_seconds=0.3)
    assert status == "failed"
    assert inventory.drops == 0
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `python -m pytest tests/test_pickup_cycle.py -v`
Expected: FAIL — `AttributeError: 'Settings' object has no attribute 'PICKUP_TIMEOUT_SECONDS'` e/ou `'MachineService' object has no attribute 'pickup_cycle'`

- [ ] **Step 3: Adicionar a config**

Em `src/infrastructure/config.py`, no bloco `# Machine` (logo após `DROP_CODE`):

```python
    # Machine
    DROP_CODE: str = Field(..., env="DROP_CODE")
    PICKUP_TIMEOUT_SECONDS: int = Field(60, env="PICKUP_TIMEOUT_SECONDS")
```

- [ ] **Step 4: Implementar `pickup_cycle`**

Em `src/domains/machine/services.py`, dentro de `MachineService` (após `drop_waiting_callback`):

```python
    async def pickup_cycle(
        self,
        timeout_seconds: float | None = None,
        on_timeout_seconds: float = 10,
    ) -> str:
        """Ciclo do modo QR estático: liga a máquina, espera o serial "1"
        (produto retirado), desliga. Roda em task background — nunca preso
        a request HTTP. "off" é enviado sempre, inclusive em erro/timeout."""
        timeout = timeout_seconds if timeout_seconds is not None else settings.PICKUP_TIMEOUT_SECONDS
        log_sender = LogSender()
        async with serial_lock:
            serial_comm = get_serial_comm()
            try:
                serial_comm.send("on")
                start = time.time()
                machine_on = False
                while time.time() - start < on_timeout_seconds:
                    if serial_comm.receive() == "on":
                        machine_on = True
                        break
                    await asyncio.sleep(0.1)
                if machine_on:
                    log.info("pickup-machine-on")
                else:
                    log.warning("pickup-machine-on-timeout")

                start = time.time()
                while time.time() - start < timeout:
                    if serial_comm.receive() == "1":
                        await self.inventory.update_on_drop()
                        log_sender.log("pickup_dispensed", status="SUCCESS", tags=["pickup", "drop", "success", "server"])
                        log.info("pickup-dispensed")
                        return "completed"
                    await asyncio.sleep(0.1)

                log_sender.log("pickup_timeout", status="ERROR", tags=["pickup", "drop", "timeout", "server"])
                log.error("pickup-timeout")
                return "failed"
            except Exception as exc:
                log_sender.log("pickup_error", additional=str(exc), status="ERROR", tags=["pickup", "drop", "error", "server"])
                log.error("pickup-cycle-error", error=str(exc))
                return "failed"
            finally:
                try:
                    serial_comm.send("off")
                    log.info("pickup-machine-off")
                except Exception as off_exc:
                    log.error("pickup-off-failed", error=str(off_exc))
```

Observação: no teste de exceção (`fail_on_send="on"`), o `finally` envia `"off"` com sucesso porque o fake só falha na mensagem `"on"` — por isso `sent == []` não é verificado ali.

- [ ] **Step 5: Rodar e ver passar**

Run: `python -m pytest tests/test_pickup_cycle.py -v`
Expected: 6 passed

- [ ] **Step 6: Commit**

```bash
git add src/infrastructure/config.py src/domains/machine/services.py tests/test_pickup_cycle.py
git commit -m "feat(machine): pickup_cycle (on -> espera serial 1 -> off) com timeout configuravel"
```

---

### Task 3: Schemas de sessão (mode + pickup)

**Files:**
- Modify: `src/domains/users/schemas.py` (bloco `# ---------- Session ----------`)
- Test: coberto pelos testes da Task 4 (schemas puros, sem lógica)

- [ ] **Step 1: Adicionar schemas**

Em `src/domains/users/schemas.py`, no bloco Session:

```python
class SessionPickupRequest(BaseModel):
    session_id: str
    slug: str


class SessionPickupResponse(BaseModel):
    status: str
    session_id: str
```

E em `SessionGetResponse`, adicionar o campo `mode` (após `status`):

```python
    mode: Optional[str] = None
```

- [ ] **Step 2: Commit**

```bash
git add src/domains/users/schemas.py
git commit -m "feat(users): schemas SessionPickup e campo mode na sessao"
```

---

### Task 4: `SessionService.init_static_session`, `start_pickup` e `mode` no get

**Files:**
- Modify: `src/domains/users/services.py` (classe `SessionService`)
- Test: `tests/test_static_session.py`

- [ ] **Step 1: Escrever os testes que falham**

```python
import asyncio

import pytest
from fastapi import HTTPException

from domains.machine.services import MachineService
from domains.users.schemas import SessionPickupRequest
from domains.users.services import SessionService


class FakeSessionRepository:
    """Réplica em memória da SessionRepository (mesma semântica atômica)."""

    def __init__(self):
        self.docs = {}

    async def create(self, doc):
        self.docs[doc["_id"]] = dict(doc)

    async def find(self, session_id):
        doc = self.docs.get(session_id)
        return dict(doc) if doc else None

    async def try_start_processing(self, session_id, slug, now):
        doc = self.docs.get(session_id)
        if not doc or doc["slug"] != slug or doc["status"] != "form_shown" or doc.get("processing"):
            return None
        doc.update(processing=True, status="processing", processing_started_at=now)
        return dict(doc)

    async def finalize(self, session_id, status, now):
        doc = self.docs.get(session_id)
        if doc:
            doc.update(status=status, processing=False, completed_at=now)


class FakeLogSender:
    def log(self, *args, **kwargs):
        pass


@pytest.fixture
def repo():
    return FakeSessionRepository()


@pytest.fixture
def service(repo, monkeypatch):
    import domains.users.services as users_services
    monkeypatch.setattr(users_services, "LogSender", FakeLogSender)
    return SessionService(session_repository=repo)


async def seed_form_shown(service, repo):
    doc = await service.init_static_session()
    repo.docs[doc["_id"]]["status"] = "form_shown"
    return doc


async def test_init_static_session_cria_doc(service, repo):
    doc = await service.init_static_session()
    saved = repo.docs[doc["_id"]]
    assert saved["mode"] == "qrcode_static"
    assert saved["status"] == "pending"
    assert saved["short_url"] is None
    assert len(saved["slug"]) >= 6


async def test_get_session_info_retorna_mode(service, repo):
    doc = await service.init_static_session()
    info = await service.get_session_info(doc["_id"])
    assert info.mode == "qrcode_static"


async def test_start_pickup_completa_sessao(service, repo, monkeypatch):
    async def fake_cycle(self, *args, **kwargs):
        return "completed"

    monkeypatch.setattr(MachineService, "pickup_cycle", fake_cycle)
    doc = await seed_form_shown(service, repo)

    resp = await service.start_pickup(SessionPickupRequest(session_id=doc["_id"], slug=doc["slug"]))
    assert resp.status == "processing"

    # aguarda a task background finalizar
    for _ in range(50):
        if repo.docs[doc["_id"]]["status"] == "completed":
            break
        await asyncio.sleep(0.05)
    assert repo.docs[doc["_id"]]["status"] == "completed"


async def test_start_pickup_falha_finaliza_failed(service, repo, monkeypatch):
    async def fake_cycle(self, *args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(MachineService, "pickup_cycle", fake_cycle)
    doc = await seed_form_shown(service, repo)

    await service.start_pickup(SessionPickupRequest(session_id=doc["_id"], slug=doc["slug"]))
    for _ in range(50):
        if repo.docs[doc["_id"]]["status"] == "failed":
            break
        await asyncio.sleep(0.05)
    assert repo.docs[doc["_id"]]["status"] == "failed"


async def test_start_pickup_one_shot(service, repo, monkeypatch):
    async def fake_cycle(self, *args, **kwargs):
        await asyncio.sleep(0.2)
        return "completed"

    monkeypatch.setattr(MachineService, "pickup_cycle", fake_cycle)
    doc = await seed_form_shown(service, repo)

    await service.start_pickup(SessionPickupRequest(session_id=doc["_id"], slug=doc["slug"]))
    with pytest.raises(HTTPException) as exc:
        await service.start_pickup(SessionPickupRequest(session_id=doc["_id"], slug=doc["slug"]))
    assert exc.value.status_code == 409


async def test_start_pickup_slug_errado(service, repo):
    doc = await seed_form_shown(service, repo)
    with pytest.raises(HTTPException) as exc:
        await service.start_pickup(SessionPickupRequest(session_id=doc["_id"], slug="errado"))
    assert exc.value.status_code == 400


async def test_start_pickup_sid_inexistente(service):
    with pytest.raises(HTTPException) as exc:
        await service.start_pickup(SessionPickupRequest(session_id="nao-existe", slug="x"))
    assert exc.value.status_code == 404
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `python -m pytest tests/test_static_session.py -v`
Expected: FAIL — `AttributeError: 'SessionService' object has no attribute 'init_static_session'`

- [ ] **Step 3: Implementar em `src/domains/users/services.py`**

Adicionar `import asyncio` e `import secrets` no topo do arquivo (junto de `import uuid`).

Atualizar os imports de schemas para incluir `SessionPickupRequest, SessionPickupResponse`.

Em `get_session_info`, adicionar `mode=session.get("mode"),` na construção do `SessionGetResponse` (após `status`).

Novos métodos na `SessionService` (após `open_form`):

```python
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

        LogSender().log("pickup_started")
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
```

- [ ] **Step 4: Rodar e ver passar (suite inteira)**

Run: `python -m pytest tests -v`
Expected: todos passam (Task 2 + Task 4)

- [ ] **Step 5: Commit**

```bash
git add src/domains/users/services.py tests/test_static_session.py
git commit -m "feat(users): sessao estatica com pickup em task background"
```

---

### Task 5: Rotas `/start`, `/session/pickup`, `/thanks`

**Files:**
- Modify: `src/domains/users/routes.py`
- Test: `tests/test_routes_registered.py`

- [ ] **Step 1: Escrever o teste que falha**

```python
def test_novas_rotas_registradas():
    from domains.users.routes import session_router

    paths = {route.path for route in session_router.routes}
    assert "/api/sample/start" in paths
    assert "/api/sample/session/pickup" in paths
    assert "/api/sample/thanks" in paths
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `python -m pytest tests/test_routes_registered.py -v`
Expected: FAIL — `AssertionError` (rotas ausentes)

- [ ] **Step 3: Implementar as rotas**

Em `src/domains/users/routes.py`:

Adicionar ao import de starlette: `from starlette.responses import HTMLResponse, RedirectResponse`
Adicionar aos imports de schemas: `SessionPickupRequest, SessionPickupResponse`

Novas rotas (após `init_qrcode`):

```python
@session_router.get("/start")
async def start_static_session():
    doc = await SessionService().init_static_session()
    return RedirectResponse(
        url=f"/api/sample/terms?sid={doc['_id']}&slug={doc['slug']}",
        status_code=302,
    )


@session_router.post("/session/pickup", response_model=SessionPickupResponse)
async def start_pickup(payload: SessionPickupRequest):
    return await SessionService().start_pickup(payload)


@session_router.get("/thanks", response_class=HTMLResponse)
async def html_thanks(request: Request):
    return _render_logged_page(request, "thanks.html", "thanks_page_accessed", "thanks")
```

- [ ] **Step 4: Rodar suite inteira**

Run: `python -m pytest tests -v`
Expected: todos passam

- [ ] **Step 5: Commit**

```bash
git add src/domains/users/routes.py tests/test_routes_registered.py
git commit -m "feat(users): rotas /start, /session/pickup e /thanks"
```

---

### Task 6: Página `thanks.html`

**Files:**
- Create: `src/static/sample/html/thanks.html`

- [ ] **Step 1: Criar a página**

Segue o padrão visual das outras páginas (`claim.html` como referência: container + text-content, CSS compartilhado):

```html
<!DOCTYPE html>
<html lang="pt-BR">

<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Sample Machine - Obrigado</title>
    <link rel="stylesheet" href="/templates/sample/css/sample-root.css">
    <link rel="stylesheet" href="/templates/sample/css/claim.css">
</head>

<body>
    <div class="container">

        <div class="text-content">
            <p>OBRIGADO!</p>
            <p>AMOSTRA RETIRADA</p>
            <p>COM SUCESSO</p>
        </div>

    </div>
</body>

</html>
```

- [ ] **Step 2: Verificação rápida**

Com o servidor rodando (`python src/main.py` ou uvicorn conforme o projeto), abrir `http://localhost:8000/api/sample/thanks` e conferir a renderização. Se não for possível rodar o servidor agora, adiar para o teste manual da Task 8.

- [ ] **Step 3: Commit**

```bash
git add src/static/sample/html/thanks.html
git commit -m "feat(static): pagina thanks.html"
```

---

### Task 7: Branch por `mode` no `claim.html` + polling

**Files:**
- Modify: `src/static/sample/html/claim.html` (substituir o `<script>`)

- [ ] **Step 1: Substituir o script do claim**

Trocar o bloco `<script>...</script>` inteiro de `src/static/sample/html/claim.html` por:

```html
    <script>
        const POLL_INTERVAL_MS = 2000;
        const POLL_MAX_MS = 90000;

        function goToError() {
            window.location.href = '/templates/sample/html/error.html';
        }

        async function fetchSession(sessionId) {
            const res = await fetch(`/api/sample/session/${sessionId}`);
            if (!res.ok) throw new Error(`session fetch ${res.status}`);
            return res.json();
        }

        // Fluxo atual (totem/Unity): dispara o drop e o Unity cuida do resto
        async function completeSession(sessionId, slug) {
            try {
                await fetch('/api/sample/session/complete', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ session_id: sessionId, slug }),
                });
            } catch (_) {}
        }

        // Fluxo QR estático: agenda o ciclo no servidor e acompanha por polling
        async function startPickupAndPoll(sessionId, slug) {
            const res = await fetch('/api/sample/session/pickup', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ session_id: sessionId, slug }),
            });
            if (!res.ok) throw new Error(`pickup ${res.status}`);

            const started = Date.now();
            while (Date.now() - started < POLL_MAX_MS) {
                await new Promise(resolve => setTimeout(resolve, POLL_INTERVAL_MS));
                const session = await fetchSession(sessionId);
                if (session.status === 'completed') {
                    window.location.href = '/api/sample/thanks';
                    return;
                }
                if (session.status === 'failed' || session.status === 'aborted') {
                    goToError();
                    return;
                }
            }
            goToError();
        }

        async function init() {
            const sessionId = localStorage.getItem('session_id');
            const slug = localStorage.getItem('slug');
            if (!sessionId || !slug) return;

            try {
                const session = await fetchSession(sessionId);
                if (session.mode === 'qrcode_static') {
                    await startPickupAndPoll(sessionId, slug);
                } else {
                    await completeSession(sessionId, slug);
                }
            } catch (_) {
                goToError();
            }
        }

        document.addEventListener('DOMContentLoaded', init);
    </script>
```

Nota: o caminho `/templates/sample/html/error.html` é válido — `src/main.py:114` monta `/templates` sobre `src/static`.

- [ ] **Step 2: Commit**

```bash
git add src/static/sample/html/claim.html
git commit -m "feat(static): claim ramifica por mode e faz polling no fluxo QR estatico"
```

---

### Task 8: Limpeza, documentação e verificação de ponta a ponta

**Files:**
- Delete: `src/domains/qrcode/` e `src/static/qrcode/` (vazios, só `__pycache__`; nada os referencia — verificado por grep)
- Create: `docs/mode-qrcode-static.md`

- [ ] **Step 1: Remover diretórios vazios**

```bash
rm -rf src/domains/qrcode src/static/qrcode
```

- [ ] **Step 2: Criar `docs/mode-qrcode-static.md`**

```markdown
# Modo QR Code Estático (sem Unity)

QR Code impresso com URL fixa. O usuário escaneia, aceita os termos, se
cadastra e retira a amostra. O servidor controla o hardware em uma task
background — nada depende do navegador ficar aberto.

## Fluxo

1. QR estático aponta para `GET /api/sample/start`
2. Servidor cria sessão (`mode: "qrcode_static"`, sem encurtador) e
   redireciona 302 para `/api/sample/terms?sid=<uuid>&slug=<slug>`
3. Termos → Cadastro (`form.html`, marca `form_shown`) → Claim
4. `claim.html` detecta `mode == "qrcode_static"` e chama
   `POST /api/sample/session/pickup` (`{session_id, slug}`)
5. Servidor valida (one-shot, slug) e agenda o ciclo em background:
   - Serial `"on"` (aguarda confirmação `"on"` por 10 s; segue mesmo sem ela)
   - Espera serial `"1"` por até `PICKUP_TIMEOUT_SECONDS` (padrão 60 s)
   - Recebeu `"1"` → inventário -1, sessão `completed`
   - Timeout/erro → sessão `failed`
   - Serial `"off"` é enviado SEMPRE ao final
6. `claim.html` faz polling de `GET /api/sample/session/{sid}` a cada 2 s
   (máx. 90 s): `completed` → `/api/sample/thanks`; `failed` → tela de erro

## Protocolo Arduino neste modo

| Direção  | Mensagem | Significado                          |
|----------|----------|--------------------------------------|
| Servidor → Arduino | `"on"`  | Liga a máquina                 |
| Arduino → Servidor | `"on"`  | Confirmação de ligada          |
| Arduino → Servidor | `"1"`   | Produto retirado (1 unidade)   |
| Servidor → Arduino | `"off"` | Desliga a máquina              |

## Config

| Variável                 | Descrição                          | Padrão |
|--------------------------|------------------------------------|--------|
| `PICKUP_TIMEOUT_SECONDS` | Espera máxima pelo `"1"` do serial | `60`   |

## Observações

- O modo convive com o fluxo do totem (`docs/mode-with-forms.md`); o
  `claim.html` ramifica pelo campo `mode` da sessão.
- Queda de conexão do celular não interrompe a retirada — o ciclo roda no
  servidor. Ao reabrir o claim, a sessão já encerrada responde 409 e a
  tela de erro é exibida.
- Sessões são one-shot: reuso de link/sid não dispara novo ciclo.
```

- [ ] **Step 3: Rodar a suite completa**

Run: `python -m pytest tests -v`
Expected: todos passam

- [ ] **Step 4: Teste manual de ponta a ponta (com Arduino ou mock serial)**

1. Subir o servidor com `.env` válido
2. Abrir `http://localhost:8000/api/sample/start` no navegador → deve redirecionar para termos com `sid`/`slug` na URL
3. Aceitar termos → preencher cadastro → chegar no claim
4. Observar logs: `pickup-machine-on` (ou warning), depois espera do `"1"`
5. Simular o Arduino enviando `1\n` na serial → logs `pickup-dispensed`, inventário decrementado em `src/static/sample/assets/inventory.json`, navegador navega para thanks
6. Repetir o fluxo sem enviar `"1"` → após 60 s, sessão `failed`, navegador na tela de erro, log `pickup-timeout`, `"off"` enviado

- [ ] **Step 5: Commit final**

```bash
git add -A
git commit -m "docs: modo QR code estatico; remove diretorios qrcode vazios"
```
