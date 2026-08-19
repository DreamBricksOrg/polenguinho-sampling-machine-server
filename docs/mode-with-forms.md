# Modo com Formulário (QR Code + Cadastro)

Neste modo o usuário escaneia um QR Code, preenche um formulário no celular e retira a amostra no totem. O Unity controla o display do totem. O Arduino controla o dispensador físico.

---

## Fluxo Completo

```
[Totem/Unity]         [Servidor]              [Celular do Usuário]       [Arduino]
     |                    |                           |                      |
     | POST /qrcode/init  |                           |                      |
     |—————————————————→  |                           |                      |
     |  QR + long_url     |                           |                      |
     |←—————————————————  |                           |                      |
     |                    |                           |                      |
     | [exibe QR na tela] |                           |                      |
     |                    |   GET /sample/welcome?sid |                      |
     |                    |  ←————————————————————————|                      |
     |                    |   [tela boas-vindas]      |                      |
     |                    |  —————————————————————→   |                      |
     |                    |                           |                      |
     |                    |   GET /sample/terms?sid   |                      |
     |                    |  ←————————————————————————|                      |
     |                    |   [tela de termos]        |                      |
     |                    |  —————————————————————→   |                      |
     |                    |                           |                      |
     |                    |   GET /sample/form?sid    |                      |
     |                    |  ←————————————————————————|                      |
UDP "next" ←—————————————|   [marca form_shown]      |                      |
     |                    |   [tela de formulário]    |                      |
     |                    |  —————————————————————→   |                      |
     |                    |                           |                      |
     |                    |   POST /api/users/        |                      |
     |                    |  ←————————————————————————|                      |
     |                    |  ←————————————————————————|                      |
     |                    |   POST /api/sample/session/terms |                      |
     |                    |   GET /sample/continue?sid |                      |
     |                    |  ←————————————————————————|                      |
     |                    |   GET /sample/claim?sid   |                      |
     |                    |  ←————————————————————————|                      |
     |                    |                           |                      |
     | POST /sample/session/complete                  |                      |
     |                    |  ←————————————————————————|                      |
     |                    |———— Serial "drop" ————————————————————————————→  |
     |                    |←——— Serial "dropped" ————————————————————————————|
UDP "next" ←—————————————|   [sessão finalizada]     |                      |
     |                    |                           |                      |
```

---

## 1. Serial (Servidor ↔ Arduino)

### Comandos enviados pelo servidor ao Arduino

| Comando          | Quando é enviado                                 | Aguarda resposta? |
|------------------|--------------------------------------------------|-------------------|
| `"on"`           | `GET /api/sample/on` — liga a máquina            | Sim (10 s)        |
| `"off"`          | `GET /api/sample/off` — desliga a máquina        | Não               |
| `"drop"`         | Sessão completa ou rota `/drop`                  | Sim (20 s)        |
| `"admin_dispense"` | `POST /api/sample/admin/dispense`              | Não               |
| `"reset"`        | `POST /api/sample/admin/inventory` (ao atualizar estoque) | Não      |

### Respostas esperadas do Arduino ao servidor

| Resposta          | Significado                                         | Dispara no servidor           |
|-------------------|-----------------------------------------------------|-------------------------------|
| `"on"`            | Máquina ligada com sucesso (resposta ao comando `"on"`) | UDP `"machine_on"`        |
| `"dropped"`       | Produto dispensado com sucesso                      | UDP `"next"`, atualiza inventário |
| `"hand_timeout"`  | Timeout: nenhuma mão detectada no tempo esperado    | UDP `"error"`                 |
| `"out_of_stock"`  | Estoque zerado detectado pelo Arduino               | UDP `"error"`                 |

> **Timeout de drop:** se o Arduino não responder em **20 segundos**, o servidor envia UDP `"timeout"` e finaliza a sessão como `"failed"`.

---

## 2. UDP (Servidor → Unity)

Todos os UDPs são enviados para a porta configurada em `UDP_PORT` (`.env`).

| Mensagem UDP   | Quando é enviada                                                   |
|----------------|--------------------------------------------------------------------|
| `"next"`       | Usuário abriu o formulário pela primeira vez (form_shown)          |
| `"next"`       | Produto dispensado com sucesso (dropped)                           |
| `"error"`      | Arduino respondeu `hand_timeout` ou `out_of_stock`                 |
| `"timeout"`    | Arduino não respondeu em 20 s durante o drop                       |
| `"machine_on"` | Arduino confirmou que a máquina está ligada                        |

> **`send_with_confirmation`** vs **`send`**: mensagens críticas (`next`, `error`, `timeout`, `machine_on`) usam confirmação (reenvio até ACK). O `"next"` enviado ao abrir o form usa `send` simples.

---

## 3. REST — Endpoints relevantes para o Unity (Totem)

Base URL: `http://<servidor>:<porta>`

### Iniciar sessão / gerar QR

```
POST /api/sample/qrcode/init
```

**Response:**
```json
{
  "session_id": "uuid",
  "long_url": "https://samplemachine.ngrok.app/api/sample/welcome?sid=uuid&slug=abc",
  "short_url": "https://samplemachine.ngrok.app/api/sample/welcome?sid=uuid&slug=abc",
  "slug": "abc",
  "qr_png": null,
  "qr_svg": null
}
```

Use `long_url` para exibir/gerar o QR Code no Unity. `short_url` é mantido apenas como compatibilidade e recebe o mesmo valor.

---

### Consultar status da sessão

```
GET /api/sample/session/{session_id}
```

**Response:**
```json
{
  "session_id": "uuid",
  "slug": "abc",
  "status": "pending | form_shown | processing | completed | failed | aborted",
  "created_at": "2024-01-01T00:00:00Z",
  "form_opened_at": "...",
  "processing_started_at": "...",
  "completed_at": "..."
}
```

Use para polling opcional — mas prefira o UDP para reatividade em tempo real.

---

### Ligar / desligar máquina

```
GET /api/sample/on
GET /api/sample/off
```

Chame no startup e shutdown do totem.

---

### Dispensar via admin (sem sessão)

```
POST /api/sample/admin/dispense
```

Dispensa diretamente, sem aguardar callback serial. Útil para testes manuais.

---

### Atualizar estoque

```
POST /api/sample/admin/inventory
Content-Type: application/json

{
  "current_quantity": 100,
  "total_dispensed": 0
}
```

Envia `"reset"` via serial após salvar.

---

## 4. REST — Endpoints relevantes para o Celular (automático via HTML)

Estes são chamados pelo frontend HTML automaticamente — você não precisa implementar no Unity.

| Método | Rota                           | O que faz                            |
|--------|--------------------------------|--------------------------------------|
| GET    | `/api/sample/welcome?sid=`     | Exibe landing page, salva sid        |
| GET    | `/api/sample/terms?sid=`       | Exibe termos                         |
| GET    | `/api/sample/form?sid=`        | Exibe form, bloqueia por cookie/IP, marca sessao, envia UDP |
| POST   | `/api/users/?collection=machine` | Cadastra usuário                   |
| GET    | `/api/sample/continue?sid=`    | Exibe tela intermediária pós-cadastro |
| GET    | `/api/sample/claim?sid=`       | Exibe tela de retirada               |
| POST   | `/api/sample/session/terms`    | Marca aceite/cadastro concluído |

`POST /api/sample/session/complete` é chamado pelo Unity em `RESULTADO.cs`, não pelo celular. Ele completa a sessão e dispara o `drop`. O bloqueio por cookie/IP só é gravado quando o celular consulta uma sessão com status `completed`, depois da confirmação serial de que o brinde caiu.

---

## 5. Ciclo de estados da sessão

```
pending → form_shown → processing → completed
                                 ↘ failed
```

| Estado       | O que aconteceu                                          |
|--------------|----------------------------------------------------------|
| `pending`    | Sessão criada, QR gerado, aguardando abertura do form    |
| `form_shown` | Form foi aberto no celular, UDP `"next"` enviado         |
| `processing` | `/session/complete` chamado, drop em andamento           |
| `completed`  | Arduino confirmou `"dropped"`, produto dispensado        |
| `failed`     | Erro serial, timeout ou exceção durante o drop           |

---

## 6. Configurações de ambiente relevantes

| Variável         | Descrição                              | Padrão                                         |
|------------------|----------------------------------------|------------------------------------------------|
| `UDP_PORT`       | Porta UDP para enviar ao Unity         | `5004`                                         |
| `SERIAL_PORT`    | Porta serial do Arduino                | `COM3`                                         |
| `SERIAL_BAUDRATE`| Baudrate da serial                     | `9600`                                         |
| `CADASTRO_BASE_URL` | Base da URL do QR (aponta para `/welcome`) | `https://samplemachine.ngrok.app/api/sample/welcome` |
| `DROP_CODE`      | Código de segurança para rotas de drop | — (obrigatório)                                |
