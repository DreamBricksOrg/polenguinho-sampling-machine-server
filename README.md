# Projeto Sampling Machine

---

## 🎛️ Modos de Operação

O servidor controla a máquina de amostras via **serial (Arduino)** e **UDP (Unity)**, e pode operar em dois modos:

### Somente Máquina (botão físico / Unity sem formulário)

Sem QR Code ou cadastro: o usuário aperta um botão físico (ou toca no Unity) e a máquina dispensa direto.

```
Botão/Unity → POST /api/sample/drop/wait?drop_code=XXX → Arduino ("drop") → "dropped" → UDP "next"
```

- `GET /api/sample/on` / `GET /api/sample/off` — liga/desliga a máquina
- `POST /api/sample/drop/wait?drop_code=` — dispara o drop e aguarda callback serial (recomendado)
- `POST /api/sample/drop?drop_code=` — dispara o drop sem aguardar (fire and forget)
- `POST /api/sample/admin/dispense` / `POST /api/sample/admin/inventory` — dispensa e estoque via painel admin

📄 Detalhes completos: [docs/mode-machine-only.md](./docs/mode-machine-only.md)

### Com Formulário (QR Code + Cadastro)

O usuário escaneia um QR Code, preenche o formulário no celular e retira a amostra no totem. O Unity controla o display; o Arduino, o dispensador.

```
Unity → POST /api/sample/qrcode/init → QR Code → celular preenche form →
POST /api/sample/session/complete → Arduino ("drop") → "dropped" → UDP "next"
```

- `POST /api/sample/qrcode/init` — gera QR e inicia sessão
- `GET /api/sample/session/{session_id}` — consulta status (`pending → form_shown → processing → completed/failed`)
- Rotas do celular (`/welcome`, `/terms`, `/form`, `/claim`, `/api/users/...`) são chamadas automaticamente pelo frontend HTML

📄 Detalhes completos: [docs/mode-with-forms.md](./docs/mode-with-forms.md)

### Configurações comuns (`.env`)

| Variável          | Descrição                                | Padrão  |
|-------------------|-------------------------------------------|---------|
| `UDP_PORT`        | Porta UDP para o Unity                    | `5004`  |
| `SERIAL_PORT`     | Porta serial do Arduino                   | `COM3`  |
| `SERIAL_BAUDRATE` | Baudrate                                  | `9600`  |
| `DROP_CODE`       | Código de autenticação das rotas de drop  | — (obrigatório) |

---

## Pré-requisitos

* Python 3.10+
* Docker

---

## 📦 Instalação e execução em modo de desenvolvimento

1. Clone o repositório e entre na pasta:

   ```bash
   git clone git@github.com:DreamBricksOrg/sampling-machine-server.git
   cd sampling-machine-server
   ```

2. Crie um virtualenv e instale dependências:

   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```

3. Configure seu `.env` (veja [exemplo de `.env.example`](./.env.example)).

4. Inicie a aplicação:

   Rode assim para debuggar

   ```bash
   PYTHONPATH=src uvicorn src.main:create_app \
     --factory \
     --host 0.0.0.0 \
     --port 8000 \
     --reload \
     --log-level debug
   ```

  Use log-level info para ambientes de produção, ou stack tracing com Datadog ou Sentry.

  No Windows, use `start.ps1` (mesmo comportamento, lê o `.env` automaticamente).

## 🐳 Docker

```bash
docker build -t sampling-machine-server .
docker run -d \
  --name sampling-machine-server \
  -p 8000:8000 \
  --env-file .env \
  -v "$(pwd)/src/static":/app/src/static \
  sampling-machine-server
```

Ou com Docker Compose:

```bash
docker compose up -d --build
```

---

