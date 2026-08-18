# Usando o `logcenter-sdk` em um projeto Flask básico

O `logcenter-sdk` é a lib usada para enviar logs estruturados para o LogCenter. O core dela (`LogCenterSender`) é **assíncrono** (baseado em `asyncio`), então em um projeto Flask (que é síncrono/WSGI) você deve usar o método `send_sync`. O middleware ASGI que a lib oferece (`LogCenterAuditMiddleware`) **não funciona em Flask** — é específico para Starlette/uvicorn.

## 1. Instalação

```bash
pip install logcenter-sdk
```

## 2. Configuração (`LogCenterConfig`)

```python
from logcenter_sdk import LogCenterConfig

config = LogCenterConfig(
    base_url="https://logcenter.exemplo.com",  # sem "/" no final
    project_id="meu-projeto",
    api_key="minha-api-key",       # opcional
    enabled=True,                  # desliga o envio sem remover o código
)
```

Campos relevantes de `LogCenterConfig`:

| Campo | Default | Descrição |
|---|---|---|
| `base_url` | — | URL base do LogCenter |
| `project_id` | — | Identificador do projeto |
| `api_key` | `None` | Header de autenticação |
| `timeout_s` | `10.0` | Timeout das requisições |
| `enabled` | `True` | Se `False`, `send()` é um no-op |
| `spool_dir` | `.logcenter` | Onde ficam os logs não enviados (fila offline) |
| `spool_max_bytes` | 25 MB | Tamanho máximo do spool |
| `flush_batch_size` | `200` | Itens por lote ao reenviar o spool |
| `flush_interval_s` | `10.0` | Intervalo do flush em background |

Também é possível criar a config direto de variáveis de ambiente com o prefixo `LOGCENTER_`:

```python
config = LogCenterConfig.from_env()
# lê LOGCENTER_BASE_URL, LOGCENTER_PROJECT_ID, LOGCENTER_API_KEY,
# LOGCENTER_TIMEOUT_S, LOGCENTER_SPOOL_DIR, LOGCENTER_FLUSH_INTERVAL_S, LOGCENTER_ENABLED
```

## 3. Estrutura mínima do projeto

```
meu_projeto/
├── app.py
├── log_sender.py
└── requirements.txt
```

`requirements.txt`:
```
flask
logcenter-sdk
```

## 4. Criando o sender (`log_sender.py`)

```python
import os
from logcenter_sdk import LogCenterConfig, LogCenterSender

config = LogCenterConfig(
    base_url=os.getenv("LOG_API", "").rstrip("/"),
    project_id=os.getenv("LOG_PROJECT_ID", ""),
    api_key=os.getenv("LOG_API_KEY"),
    enabled=bool(os.getenv("LOG_API") and os.getenv("LOG_PROJECT_ID")),
)

sender = LogCenterSender(config)


def log(message: str, *, level: str = "INFO", status: str | None = None,
        tags: list[str] | None = None, data: dict | None = None) -> None:
    """Envio síncrono de log (usa asyncio.run internamente)."""
    sender.send_sync(level, message, status=status, tags=tags, data=data)
```

`send_sync` funciona bem em Flask porque cada request roda sem um event loop ativo — a lib cria um (`asyncio.run(...)`) para cada chamada. Isso é aceitável para logging pontual; se o volume de logs for alto, considere enviar de forma assíncrona em uma thread separada (seção 6).

## 5. Usando na aplicação (`app.py`)

```python
from flask import Flask, request, jsonify
from log_sender import log, sender

app = Flask(__name__)


@app.route("/ping")
def ping():
    log("Ping recebido", tags=["health"])
    return jsonify(status="ok")


@app.errorhandler(Exception)
def handle_exception(exc):
    log(
        "Erro não tratado",
        level="ERROR",
        status="ERROR",
        tags=["exception"],
        data={"path": request.path, "method": request.method, "exception": exc.__class__.__name__},
    )
    return jsonify(error="internal error"), 500


if __name__ == "__main__":
    app.run(debug=True)
```

## 6. Fila offline (spool) e flush periódico

Se o envio falhar (rede fora, LogCenter indisponível), o payload é gravado em `spool_dir` (`.logcenter/spool.jsonl` por padrão) automaticamente — não precisa de nada extra para isso.

Para reenviar o spool periodicamente em Flask (que não tem um loop assíncrono rodando o tempo todo como o FastAPI/Starlette), rode o flush em uma thread própria com seu próprio event loop, por exemplo usando `APScheduler` ou uma thread simples:

```python
import asyncio
import threading
import time

def _flush_loop():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    while True:
        loop.run_until_complete(sender.flush_spool())
        time.sleep(config.flush_interval_s)

threading.Thread(target=_flush_loop, daemon=True).start()
```

Coloque essa thread para iniciar junto com a aplicação (ex.: antes do `app.run(...)`).

## 7. Variáveis de ambiente sugeridas

```
LOG_API=https://logcenter.exemplo.com
LOG_PROJECT_ID=meu-projeto
LOG_API_KEY=minha-api-key
```

## 8. Níveis e status

- `level`: `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`, `FATAL` (default `INFO`).
- `status`: se omitido, é inferido automaticamente — `ERROR` para níveis `ERROR`/`CRITICAL`/`FATAL`, `OK` para os demais.
- `tags`: lista livre de strings para facilitar busca/filtro no LogCenter (ex.: `["startup"]`, `["exception"]`).
- `data`: dicionário livre com contexto adicional (payload, path, etc).
