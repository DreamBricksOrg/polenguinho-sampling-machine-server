# Modo Somente Máquina (Botão Físico / Unity sem Formulário)

Neste modo não há QR Code nem cadastro. O usuário aperta um botão físico (ou toca na tela do Unity) e a máquina dispensa diretamente. O servidor é usado apenas para controle de hardware e inventário.

---

## Fluxo Completo

```
[Botão/Unity]              [Servidor]                 [Arduino]
     |                         |                           |
     | GET /api/sample/on      |                           |
     |————————————————————→    |                           |
     |                         |——— Serial "on" ————————→  |
     |                         |←—— Serial "on" ———————————|
     | UDP "machine_on"        |                           |
     |←————————————————————————|                           |
     |                         |                           |
     |  [usuário aperta botão] |                           |
     |                         |                           |
     | POST /api/sample/drop/wait?drop_code=XXX&slug=btn1  |
     |————————————————————→    |                           |
     |                         |——— Serial "drop" ——————→  |
     |                         |                           |
     |                         |←—— Serial "dropped" ——————|
     | UDP "next"              |                           |
     |←————————————————————————|                           |
     | { "status": "completed" }                           |
     |←————————————————————————|                           |
     |                         |                           |
     | GET /api/sample/off     |                           |
     |————————————————————→    |                           |
     |                         |——— Serial "off" ———————→  |
     |                         |                           |
```

---

## 1. Serial (Servidor ↔ Arduino)

### Comandos enviados pelo servidor ao Arduino

| Comando            | Rota que dispara                             | Aguarda resposta? | Timeout |
|--------------------|----------------------------------------------|-------------------|---------|
| `"on"`             | `GET /api/sample/on`                         | Sim               | 10 s    |
| `"off"`            | `GET /api/sample/off`                        | Não               | —       |
| `"drop"`           | `POST /api/sample/drop` ou `/drop/wait`      | `/drop` não; `/drop/wait` sim | 20 s |
| `"admin_dispense"` | `POST /api/sample/admin/dispense`            | Não               | —       |
| `"reset"`          | `POST /api/sample/admin/inventory`           | Não               | —       |

### Respostas que o Arduino deve enviar ao servidor

| Resposta          | Quando enviar                                                       |
|-------------------|---------------------------------------------------------------------|
| `"on"`            | Após receber `"on"` e a máquina estar pronta                        |
| `"dropped"`       | Produto dispensado fisicamente com sucesso                          |
| `"hand_timeout"`  | Tempo expirou esperando detecção de mão / produto não retirado      |
| `"out_of_stock"`  | Sensor detectou estoque vazio                                        |

> O servidor aguarda `"dropped"`, `"hand_timeout"` ou `"out_of_stock"`. Qualquer outra string é ignorada e o loop continua até o timeout de 20 s.

---

## 2. UDP (Servidor → Unity)

Porta configurada em `UDP_PORT` (padrão: `5004`).

| Mensagem UDP   | Quando é enviada                                    | Tipo de envio       |
|----------------|-----------------------------------------------------|---------------------|
| `"machine_on"` | Arduino confirmou `"on"`                            | com confirmação     |
| `"next"`       | Produto dispensado com sucesso (`"dropped"`)         | com confirmação     |
| `"error"`      | Arduino respondeu `"hand_timeout"` ou `"out_of_stock"` | com confirmação  |
| `"timeout"`    | Arduino não respondeu em 20 s no drop               | com confirmação     |

### O que o Unity deve fazer com cada mensagem

| Mensagem       | Ação sugerida no Unity                                              |
|----------------|---------------------------------------------------------------------|
| `"machine_on"` | Liberar interação (mostrar botão / habilitar tela)                  |
| `"next"`       | Mostrar animação de sucesso / "pegue sua amostra"                   |
| `"error"`      | Mostrar tela de erro / "procure um atendente"                       |
| `"timeout"`    | Mostrar tela de timeout / tentar novamente                          |

---

## 3. REST — Referência Completa para Unity + Arduino

### Ligar a máquina

```
GET /api/sample/on
```

Aguarda até 10 s o Arduino responder `"on"`.

**Response:**
```json
{ "status": "machine_on" }
// ou
{ "status": "machine_dont_respond" }
```

---

### Desligar a máquina

```
GET /api/sample/off
```

Envia `"off"` sem aguardar resposta.

**Response:**
```json
{ "status": "machine_turned_off" }
```

---

### Drop sem aguardar callback (fire and forget)

```
POST /api/sample/drop?drop_code=SEU_DROP_CODE
```

Envia `"drop"` serial e retorna imediatamente. O Arduino processa no próprio ritmo. **Use este quando o Unity já trata o UDP de retorno.**

**Response:**
```json
{ "status": "drop_sent" }
```

**Erros:**
```json
// drop_code errado
{ "detail": "Drop code inválido" }   // HTTP 403
```

---

### Drop aguardando callback (recomendado para máquina sem forms)

```
POST /api/sample/drop/wait?drop_code=SEU_DROP_CODE&slug=identificador_opcional
```

Envia `"drop"` e aguarda até 20 s a resposta serial. Retorna apenas quando o Arduino responde ou o timeout expira.

**Query params:**
| Param       | Obrigatório | Descrição                                        |
|-------------|-------------|--------------------------------------------------|
| `drop_code` | Sim         | Código secreto definido em `DROP_CODE` no `.env` |
| `slug`      | Não         | Identificador livre (ex: `"btn1"`, `"totem_a"`) usado nos logs |

**Response:**
```json
{ "status": "completed" }  // Arduino respondeu "dropped"
{ "status": "failed" }     // hand_timeout, out_of_stock ou timeout de 20s
```

> Enquanto esta requisição está em curso, nenhuma outra operação serial pode ocorrer (serial_lock). Planeje timeouts no Unity acima de 20 s (sugerido: 25 s).

---

### Dispensa administrativa (sem drop_code, sem espera)

```
POST /api/sample/admin/dispense
```

Envia `"admin_dispense"` serial e atualiza inventário imediatamente. Use para testes manuais ou liberação pelo operador via painel.

**Response:**
```json
{ "status": "admin_dispense" }
```

---

### Ler inventário atual

O inventário é um arquivo JSON em `src/static/sample/assets/inventory.json`.

**Leitura direta via GET estático:**
```
GET /static/sample/assets/inventory.json
```

**Response:**
```json
{
  "current_quantity": 87,
  "total_dispensed": 13,
  "last_updated": "2024-01-15T14:30:00",
  "previous_quantity": 88,
  "quantity_change": -1
}
```

---

### Atualizar estoque (após reabastecimento)

```
POST /api/sample/admin/inventory
Content-Type: application/json

{
  "current_quantity": 100,
  "total_dispensed": 13
}
```

Salva o novo estoque e envia `"reset"` ao Arduino via serial.

**Response:**
```json
{ "status": "inventory_updated" }
```

---

## 4. Protocolo Arduino — Resumo para Implementação

```
┌──────────────────────────────────────────────────────────────────┐
│  Recebe: "on"                                                    │
│  → Inicializa hardware                                           │
│  → Envia: "on"                                                   │
├──────────────────────────────────────────────────────────────────┤
│  Recebe: "drop"                                                  │
│  → Aciona mecanismo de dispensação                               │
│  → SE produto saiu com sucesso:  envia "dropped"                 │
│  → SE sem estoque detectado:     envia "out_of_stock"            │
│  → SE ninguém retirou (timeout): envia "hand_timeout"            │
├──────────────────────────────────────────────────────────────────┤
│  Recebe: "admin_dispense"                                        │
│  → Mesma lógica de "drop", mas sem resposta serial obrigatória   │
├──────────────────────────────────────────────────────────────────┤
│  Recebe: "off"                                                   │
│  → Desliga / coloca em standby                                   │
├──────────────────────────────────────────────────────────────────┤
│  Recebe: "reset"                                                 │
│  → Reinicia contadores ou estado interno de estoque              │
└──────────────────────────────────────────────────────────────────┘
```

**Baudrate:** `9600` (padrão, configurável em `SERIAL_BAUDRATE`)
**Porta:** `COM3` (padrão, configurável em `SERIAL_PORT`)
**Encoding:** ASCII / UTF-8, terminado por `\n` ou conforme implementação de `SerialComm`

---

## 5. Sequência típica no Unity (pseudocódigo)

```csharp
// Startup
await POST("/api/sample/on");
// aguarda UDP "machine_on" antes de liberar tela

// Usuário aperta botão
DisableButton();
var result = await POST("/api/sample/drop/wait?drop_code=XXX&slug=totem_a", timeout: 25s);

if (result.status == "completed") {
    ShowSuccess();   // ou aguarda UDP "next"
} else {
    ShowError();     // ou aguarda UDP "error" / "timeout"
}

EnableButton();

// Shutdown
await GET("/api/sample/off");
```

---

## 6. Configurações de ambiente relevantes

| Variável         | Descrição                                | Padrão  |
|------------------|------------------------------------------|---------|
| `UDP_PORT`       | Porta UDP para Unity                     | `5004`  |
| `SERIAL_PORT`    | Porta serial do Arduino                  | `COM3`  |
| `SERIAL_BAUDRATE`| Baudrate                                 | `9600`  |
| `DROP_CODE`      | Código de autenticação das rotas de drop | — (obrigatório no `.env`) |
