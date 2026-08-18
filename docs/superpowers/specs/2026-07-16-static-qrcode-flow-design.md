# Design — Modo QR Code Estático (retirada sem Unity)

**Data:** 2026-07-16
**Status:** aprovado em conversa (abordagem A)

## Objetivo

Novo fluxo de retirada em que o QR Code é **estático** (impresso, URL fixa). O usuário escaneia, aceita termos, se cadastra e, na tela de claim, o **servidor** liga a máquina, espera a mensagem serial `"1"` e desliga — tudo em uma task em background, desacoplada do navegador. O modo atual (QR dinâmico do totem/Unity, `docs/mode-with-forms.md`) continua funcionando em paralelo.

## Fluxo

```
[Celular]                          [Servidor]                        [Arduino]
    |                                  |                                 |
    | GET /api/sample/start            |                                 |
    |————————————————————————————————→ | cria sessão (mode=qrcode_static)|
    | 302 → /terms?sid=..&slug=..      |                                 |
    |←————————————————————————————————|                                 |
    | [termos] → [cadastro/form]       | (form_shown, como hoje)         |
    | [claim]                          |                                 |
    | POST /api/sample/session/pickup  |                                 |
    |————————————————————————————————→ | form_shown → processing         |
    | { "status": "processing" }       | spawn task background:          |
    |←————————————————————————————————|   Serial "on" (espera "on" 10s) |
    |                                  |   espera "1" até 60s ——————————→|
    | polling GET /session/{sid}       |←——— Serial "1" —————————————————|
    | (a cada ~2s)                     |   inventário -1                 |
    |                                  |   Serial "off"                  |
    |                                  |   finaliza completed/failed     |
    | status=completed → thanks.html   |                                 |
    | status=failed    → error.html    |                                 |
```

## Decisões

1. **Sessão nasce em endpoint de redirect** — `GET /api/sample/start` cria o documento de sessão no Mongo e responde `302` para `/api/sample/terms?sid=<uuid>&slug=<slug>`. Sem encurtador (QR é fixo); o `slug` é gerado localmente (token aleatório curto) e mantém o papel de segredo fraco nas transições.
2. **Campo `mode` na sessão** — `"qrcode_static"` neste fluxo; ausente/`"totem"` no fluxo atual. `GET /api/sample/session/{sid}` passa a retornar `mode`, e o `claim.html` ramifica por ele.
3. **Ciclo de hardware roda no servidor** — o endpoint `POST /api/sample/session/pickup` valida e agenda `asyncio.create_task`; o navegador não segura request longo. Queda de conexão do celular não interrompe a retirada.
4. **Timeout de espera do `"1"`: 60 s** — configurável via `PICKUP_TIMEOUT_SECONDS` (`.env`, padrão `60`).
5. **`"off"` é enviado sempre** — tanto no sucesso quanto no timeout/erro.
6. **Ao receber `"1"`** — decrementa inventário (`InventoryService.update_on_drop`, -1 / +1 dispensado) e finaliza a sessão como `completed`.
7. **Reuso das páginas existentes** — `terms.html` e `form.html` sem mudança; `claim.html` ganha o branch novo; `thanks.html` é criada.
8. **Limpeza** — remover diretórios vazios `src/domains/qrcode/` e `src/static/qrcode/` (sobras de tentativa anterior).

## Componentes

### 1. `SessionService` (`src/domains/users/services.py`)

- `init_static_session()` — cria doc de sessão: mesmos campos do `init_qrcode()` + `"mode": "qrcode_static"`, `slug` = `secrets.token_urlsafe(6)`, sem `short_url`/QR.
- `start_pickup(req)` — análogo ao `complete_session`:
  - `try_start_processing(session_id, slug)` (atômico, one-shot, valida slug; 404/400/409 como hoje);
  - `asyncio.create_task(self._run_pickup(session_id))` e retorna `{"status": "processing"}`;
  - `_run_pickup`: chama `MachineService().pickup_cycle()`, e no `finally` chama `sessions.finalize(session_id, status_final)`.

### 2. `MachineService` (`src/domains/machine/services.py`)

- `pickup_cycle(timeout_seconds) -> str` — sob `serial_lock` (um único acquire para o ciclo inteiro, evitando corrida entre `on` e a espera):
  1. envia `"on"`, espera resposta `"on"` até 10 s (se não vier, segue mesmo assim — logado como warning);
  2. loop lendo serial até `timeout_seconds` (padrão `settings.PICKUP_TIMEOUT_SECONDS`);
  3. `"1"` recebido → `inventory.update_on_drop()`, envia `"off"`, retorna `"completed"`;
  4. timeout → envia `"off"`, retorna `"failed"`;
  5. exceção → tenta enviar `"off"` (best effort), retorna `"failed"`.
  - Logs via `structlog` + `LogSender` nos mesmos moldes de `drop_waiting_callback`.

### 3. Rotas (`src/domains/users/routes.py`, `session_router`)

| Método | Rota                          | Função                                             |
|--------|-------------------------------|----------------------------------------------------|
| GET    | `/api/sample/start`           | Cria sessão estática, 302 → terms com sid+slug     |
| POST   | `/api/sample/session/pickup`  | Body `{session_id, slug}`; agenda ciclo, retorna processing |
| GET    | `/api/sample/thanks`          | Serve `thanks.html`                                |

`GET /api/sample/session/{sid}` inclui `mode` no response (`SessionGetResponse`).

### 4. Frontend

- `claim.html` — no load: busca `/api/sample/session/{sid}`;
  - `mode != "qrcode_static"` → comportamento atual (`/session/complete`);
  - `mode == "qrcode_static"` → `POST /session/pickup`, depois polling de `/session/{sid}` a cada 2 s por até 90 s:
    - `completed` → redirect `/api/sample/thanks`;
    - `failed`/`aborted` ou 90 s de polling → tela de erro existente.
- `thanks.html` — página estática de agradecimento, mesmo CSS (`sample-root.css`).

### 5. Config (`src/infrastructure/config.py`)

- `PICKUP_TIMEOUT_SECONDS: int = 60`.

## Estados da sessão (inalterados)

`pending → form_shown → processing → completed | failed` — mesmas transições atômicas via `find_one_and_update` (`repositories.py`); nenhum estado novo.

## Tratamento de erros

| Situação                                | Comportamento                                            |
|-----------------------------------------|----------------------------------------------------------|
| `sid` inválido em `/session/pickup`     | 404                                                      |
| `slug` não confere                      | 400                                                      |
| Sessão já em processing/encerrada       | 409 (one-shot preservado)                                |
| Arduino não responde `"on"`             | Warning; ciclo continua esperando `"1"` mesmo assim      |
| `"1"` não chega em 60 s                 | `"off"` enviado, sessão `failed`, claim mostra erro      |
| Exceção na serial durante o ciclo       | `"off"` best-effort, sessão `failed`                     |
| Celular perde conexão durante polling   | Ciclo continua no servidor; ao reabrir claim, sessão já está encerrada (409 → tela de erro) |

## Testes

- Unit `pickup_cycle`: serial fake respondendo `"1"` (completed + inventário -1), nada (failed + `"off"` enviado), exceção (failed).
- Unit `start_pickup`: transição one-shot (segunda chamada → 409), slug errado → 400.
- Unit `init_static_session`: doc com `mode`, sem chamada ao encurtador.
- Manual: fluxo completo com Arduino ou mock serial.

## Fora de escopo

- UDP/Unity neste modo (mensagens UDP existentes do form são inócuas e permanecem).
- Retry na tela de claim após falha.
- Alterações no fluxo do totem/QR dinâmico.
