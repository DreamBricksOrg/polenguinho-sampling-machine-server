# Bloqueio de retirada repetida por cookie (12h) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Impedir que o mesmo navegador inicie `GET /api/sample/start` de novo dentro de `PICKUP_COOKIE_BLOCK_HOURS` (padrão 12h) depois de concluir uma retirada, usando um cookie simples (sem assinatura) com `session_id:timestamp`.

**Architecture:** Duas funções puras em `src/domains/users/services.py` (montar o valor do cookie e decidir se está bloqueado) cobertas por testes unitários; a rota `GET /api/sample/start` lê o cookie e barra com `error.html` quando bloqueado; a rota `GET /api/sample/session/{sid}` grava o cookie na resposta quando observa `status == "completed"` de uma sessão `mode == "qrcode_static"` (é o único ponto do fluxo que sabe o `session_id` no momento da conclusão — `/thanks` não recebe `sid` na URL, então não pode ser o ponto de gravação).

**Tech Stack:** FastAPI (Starlette `Request`/`Response`), Python stdlib (`datetime`), pytest/pytest-asyncio (padrão já usado em `tests/test_static_session.py`).

---

## Nota sobre o design aprovado

O design (`docs/superpowers/specs/2026-08-10-cookie-pickup-block-design.md`) previa gravar o
cookie em `GET /api/sample/thanks`. Ao mapear os arquivos descobri que `claim.html` navega
para `/api/sample/thanks` **sem `?sid=...`** (`src/static/sample/html/claim.html:67,88` —
`window.location.href = '/api/sample/thanks'`), então essa rota não tem como saber qual sessão
concluiu. Este plano grava o cookie em `GET /api/sample/session/{sid}` (a mesma rota que o
`claim.html` já faz polling a cada 2s e que devolve `status == "completed"`) — mesma
semântica do design (só grava quando a retirada realmente conclui), só muda o endpoint exato.
O restante do design (formato do cookie, verificação em `/start`, fail-open, nova env var,
log `servidor_start_blocked`) permanece como aprovado.

---

### Task 1: Nova variável de configuração `PICKUP_COOKIE_BLOCK_HOURS`

**Files:**
- Modify: `src/infrastructure/config.py:71`
- Modify: `.env:30` (arquivo local, não versionado — adicionar a linha manualmente)
- Modify: `.env.example:30`

- [ ] **Step 1: Adicionar o campo em `Settings`**

Em `src/infrastructure/config.py`, logo abaixo da linha `PICKUP_COOLDOWN_HOURS`:

```python
    PICKUP_COOLDOWN_HOURS: float = Field(12, env="PICKUP_COOLDOWN_HOURS")
    PICKUP_COOKIE_BLOCK_HOURS: float = Field(12, env="PICKUP_COOKIE_BLOCK_HOURS")
```

- [ ] **Step 2: Adicionar a variável no `.env.example`**

Em `.env.example`, logo abaixo de `PICKUP_COOLDOWN_HOURS=12`:

```
PICKUP_COOLDOWN_HOURS=12
PICKUP_COOKIE_BLOCK_HOURS=12
```

- [ ] **Step 3: Adicionar a mesma linha no `.env` local**

Adicionar `PICKUP_COOKIE_BLOCK_HOURS=12` no `.env` do projeto (mesmo bloco de `PICKUP_COOLDOWN_HOURS`).

- [ ] **Step 4: Verificar que a app ainda sobe sem erro de validação**

Run: `python -c "from infrastructure.config import settings; print(settings.PICKUP_COOKIE_BLOCK_HOURS)"` (executar de dentro de `src/`, ou com `PYTHONPATH=src`)
Expected: imprime `12.0` sem exceções.

- [ ] **Step 5: Commit**

```bash
git add src/infrastructure/config.py .env.example
git commit -m "feat: add PICKUP_COOKIE_BLOCK_HOURS setting"
```

(Não commitar `.env` — é local/ignorado.)

---

### Task 2: Funções puras de cookie em `services.py` (com testes)

**Files:**
- Modify: `src/domains/users/services.py` (perto de `now_utc`/`email_hash`, topo do arquivo)
- Test: `tests/test_static_session.py`

- [ ] **Step 1: Escrever os testes (falhando)**

Adicionar ao final de `tests/test_static_session.py`:

```python
from domains.users.services import (
    PICKUP_BLOCK_COOKIE_NAME,
    build_pickup_block_cookie_value,
    is_pickup_blocked,
)


def test_build_pickup_block_cookie_value_formato():
    now = datetime(2026, 8, 10, 12, 0, 0, tzinfo=timezone.utc)
    value = build_pickup_block_cookie_value("sid-123", now)
    assert value == f"sid-123:{int(now.timestamp())}"


def test_is_pickup_blocked_dentro_da_janela():
    now = datetime(2026, 8, 10, 12, 0, 0, tzinfo=timezone.utc)
    cookie_value = build_pickup_block_cookie_value("sid-123", now)
    later = now + timedelta(hours=11, minutes=59)
    assert is_pickup_blocked(cookie_value, later, hours=12) is True


def test_is_pickup_blocked_apos_a_janela():
    now = datetime(2026, 8, 10, 12, 0, 0, tzinfo=timezone.utc)
    cookie_value = build_pickup_block_cookie_value("sid-123", now)
    later = now + timedelta(hours=12, minutes=1)
    assert is_pickup_blocked(cookie_value, later, hours=12) is False


def test_is_pickup_blocked_cookie_ausente():
    now = datetime(2026, 8, 10, 12, 0, 0, tzinfo=timezone.utc)
    assert is_pickup_blocked(None, now, hours=12) is False
    assert is_pickup_blocked("", now, hours=12) is False


def test_is_pickup_blocked_cookie_malformado():
    now = datetime(2026, 8, 10, 12, 0, 0, tzinfo=timezone.utc)
    assert is_pickup_blocked("sem-dois-pontos", now, hours=12) is False
    assert is_pickup_blocked("sid-123:nao-e-numero", now, hours=12) is False
    assert is_pickup_blocked("sid-123:", now, hours=12) is False


def test_pickup_block_cookie_name():
    assert PICKUP_BLOCK_COOKIE_NAME == "sample_pickup_block"
```

No topo do arquivo `tests/test_static_session.py`, ajustar o import de `datetime` (hoje o
arquivo não importa `datetime`/`timedelta`/`timezone`):

```python
from datetime import datetime, timedelta, timezone
```

- [ ] **Step 2: Rodar os testes para confirmar que falham**

Run: `pytest tests/test_static_session.py -k pickup_block -v`
Expected: `ImportError: cannot import name 'PICKUP_BLOCK_COOKIE_NAME'` (ou `ModuleNotFoundError` equivalente) — as funções ainda não existem.

- [ ] **Step 3: Implementar as funções em `services.py`**

Em `src/domains/users/services.py`, logo abaixo da função `now_utc` (linha ~36-37):

```python
PICKUP_BLOCK_COOKIE_NAME = "sample_pickup_block"


def build_pickup_block_cookie_value(session_id: str, now: datetime) -> str:
    return f"{session_id}:{int(now.timestamp())}"


def is_pickup_blocked(cookie_value: str | None, now: datetime, hours: float) -> bool:
    if not cookie_value:
        return False
    try:
        _, ts_str = cookie_value.rsplit(":", 1)
        ts = int(ts_str)
    except (ValueError, AttributeError):
        return False
    elapsed_seconds = now.timestamp() - ts
    return 0 <= elapsed_seconds < hours * 3600
```

- [ ] **Step 4: Rodar os testes para confirmar que passam**

Run: `pytest tests/test_static_session.py -k pickup_block -v`
Expected: 6 passed.

- [ ] **Step 5: Rodar a suíte inteira para checar que nada quebrou**

Run: `pytest tests/ -v`
Expected: todos os testes existentes continuam passando.

- [ ] **Step 6: Commit**

```bash
git add src/domains/users/services.py tests/test_static_session.py
git commit -m "feat: add pure helpers for pickup-block cookie"
```

---

### Task 3: Verificar o cookie em `GET /api/sample/start`

**Files:**
- Modify: `src/domains/users/routes.py:88-94`

- [ ] **Step 1: Atualizar imports**

No topo de `src/domains/users/routes.py`, trocar:

```python
from fastapi import APIRouter, Body, HTTPException, Query, Request
```

por:

```python
from fastapi import APIRouter, Body, HTTPException, Query, Request, Response
```

E adicionar, junto aos outros imports de `.services`:

```python
from .services import (
    SessionService,
    UserService,
    PICKUP_BLOCK_COOKIE_NAME,
    build_pickup_block_cookie_value,
    is_pickup_blocked,
    now_utc,
)
```
(substitui a linha `from .services import SessionService, UserService` já existente)

Também adicionar, junto aos outros imports do topo:

```python
from infrastructure.config import settings
```

- [ ] **Step 2: Alterar a rota `/start`**

Substituir o handler atual:

```python
@session_router.get("/start")
async def start_static_session():
    doc = await SessionService().init_static_session()
    return RedirectResponse(
        url=f"/api/sample/form?sid={doc['_id']}&slug={doc['slug']}",
        status_code=302,
    )
```

por:

```python
@session_router.get("/start", response_class=HTMLResponse)
async def start_static_session(request: Request):
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
```

Note que a rota agora retorna dois tipos de resposta possíveis (`HTMLResponse` via
`TemplateResponse` quando bloqueado, `RedirectResponse` quando não bloqueado) — por isso o
`response_class=HTMLResponse` no decorator serve só de documentação para o OpenAPI, o retorno
real de cada branch já é um objeto `Response` concreto, então o FastAPI não força conversão.

- [ ] **Step 3: Rodar as rotas registradas para garantir que o módulo ainda importa**

Run: `pytest tests/test_routes_registered.py -v`
Expected: PASS (o teste só verifica que os paths existem, mas qualquer erro de import/sintaxe
no módulo já faria esse teste falhar na coleta).

- [ ] **Step 4: Commit**

```bash
git add src/domains/users/routes.py
git commit -m "feat: block /api/sample/start via pickup-block cookie"
```

---

### Task 4: Gravar o cookie em `GET /api/sample/session/{sid}` quando a retirada conclui

**Files:**
- Modify: `src/domains/users/routes.py:107-109`

- [ ] **Step 1: Alterar a rota `/session/{sid}`**

Substituir:

```python
@session_router.get("/session/{sid}", response_model=SessionGetResponse)
async def get_session_info(sid: str):
    return await SessionService().get_session_info(sid)
```

por:

```python
@session_router.get("/session/{sid}", response_model=SessionGetResponse)
async def get_session_info(sid: str, response: Response):
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
    return info
```

Isso funciona porque, quando o handler retorna um objeto que **não** é um `Response` (aqui,
`info` é um `SessionGetResponse`/Pydantic model), o FastAPI usa o objeto `response` injetado
para montar a resposta final — headers/cookies setados nele são preservados. Esse é o padrão
documentado do FastAPI para setar cookies em endpoints que devolvem JSON.

- [ ] **Step 2: Rodar as rotas registradas de novo**

Run: `pytest tests/test_routes_registered.py -v`
Expected: PASS.

- [ ] **Step 3: Rodar a suíte inteira**

Run: `pytest tests/ -v`
Expected: todos os testes passam (nenhum teste existente cobre `get_session_info` via HTTP, só
via `SessionService` diretamente em `tests/test_static_session.py`, que não é afetado — a
mudança é só na camada de rota).

- [ ] **Step 4: Commit**

```bash
git add src/domains/users/routes.py
git commit -m "feat: set pickup-block cookie when qrcode_static session completes"
```

---

### Task 5: Teste manual do fluxo ponta a ponta (SERIAL_FAKE)

**Files:** nenhum arquivo novo — validação manual seguindo `docs/mode-qrcode-static.md`.

- [ ] **Step 1: Subir a app com `SERIAL_FAKE=true` e `USE_FORM=true`**

Run: `python -m uvicorn main:app --reload --app-dir src` (ou o comando que `start.ps1` usa)

- [ ] **Step 2: Completar o fluxo uma vez**

Acessar `GET /api/sample/start` no navegador, seguir termos → form → claim, injetar `"1"` via
`POST /api/sample/admin/serial/inject` (ver `docs/mode-qrcode-static.md`), aguardar chegar em
`/api/sample/thanks`.

- [ ] **Step 3: Confirmar que o cookie foi gravado**

Nas DevTools do navegador (Application → Cookies), verificar que existe o cookie
`sample_pickup_block` com valor `"<session_id>:<timestamp>"` e `Max-Age` de 12h.

- [ ] **Step 4: Tentar `GET /api/sample/start` de novo**

Expected: renderiza `error.html` (tela "já retirou"), **não** cria uma nova sessão nem
redireciona pro form.

- [ ] **Step 5: Apagar o cookie manualmente e repetir**

Apagar `sample_pickup_block` nas DevTools, acessar `/api/sample/start` de novo.
Expected: fluxo normal, cria nova sessão, redireciona pro form (confirma o fail-open e que o
bloqueio é mesmo só client-side).

---

## Self-Review

**Spec coverage:**
- Formato do cookie (`session_id:timestamp`, sem assinatura) → Task 2.
- Nova env var `PICKUP_COOKIE_BLOCK_HOURS` → Task 1.
- Verificação em `/start`, fail-open, `error.html` → Task 3.
- Gravação ao concluir retirada (ajustado de `/thanks` para `/session/{sid}`, ver nota no topo
  do plano) → Task 4.
- Atributos do cookie (`httponly`, `samesite`, `secure`, `path`, `max_age`) → Task 4.
- Log `servidor_start_blocked` → Task 3.
- Testes cobrindo cookie ausente/válido/expirado/malformado → Task 2.
- Fora de escopo (totem/`qrcode/init`, cooldown por e-mail) → não tocado em nenhuma task.

**Placeholder scan:** nenhum "TBD"/"adicionar validação apropriada" — todos os steps têm
código completo.

**Type consistency:** `PICKUP_BLOCK_COOKIE_NAME`, `build_pickup_block_cookie_value`,
`is_pickup_blocked` usados com a mesma assinatura em Task 2, 3 e 4.
