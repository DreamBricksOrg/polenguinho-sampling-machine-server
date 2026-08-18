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

| Direção            | Mensagem | Significado                    |
|--------------------|----------|--------------------------------|
| Servidor → Arduino | `"on"`   | Liga a máquina                 |
| Arduino → Servidor | `"on"`   | Confirmação de ligada          |
| Arduino → Servidor | `"1"`    | Produto retirado (1 unidade)   |
| Servidor → Arduino | `"off"`  | Desliga a máquina              |

> Um `"1"` que chegue antes da confirmação do `"on"` também é aceito —
> o ciclo completa normalmente.

## Config

| Variável                 | Descrição                          | Padrão |
|--------------------------|------------------------------------|--------|
| `PICKUP_TIMEOUT_SECONDS` | Espera máxima pelo `"1"` do serial | `60`   |
| `SERIAL_FAKE`            | Serial simulada (sem Arduino)      | `false`|

## Testar sem Arduino (SERIAL_FAKE)

1. No `.env`: `SERIAL_FAKE=true` — o servidor usa uma serial em memória
   (`FakeSerialComm`) que confirma o `"on"` automaticamente.
2. Percorra o fluxo normalmente até o claim.
3. Simule a retirada injetando o `"1"` (auth básica do admin):

   ```bash
   curl -u <SAMPLE_ADMIN_USER>:<SAMPLE_ADMIN_PASSWORD> \
     -X POST http://localhost:8000/api/sample/admin/serial/inject \
     -H "Content-Type: application/json" -d '{"message": "1"}'
   ```

4. O navegador navega para o thanks e o inventário decrementa. Sem injetar
   nada, o timeout de 60 s leva à tela de erro.

O endpoint `/api/sample/admin/serial/inject` só funciona com
`SERIAL_FAKE=true` (400 caso contrário). Também serve para o modo totem
(`{"message": "dropped"}`, `hand_timeout`, `out_of_stock`).

Alternativa com hardware simulado de verdade: par de portas virtuais
(com0com) + `python scripts/arduino_sim.py COM9` — exige driver assinado
aceito pelo Windows (Secure Boot pode bloquear, problema código 52).

## Observações

- O modo convive com o fluxo do totem (`docs/mode-with-forms.md`); o
  `claim.html` ramifica pelo campo `mode` da sessão.
- Queda de conexão do celular não interrompe a retirada — o ciclo roda no
  servidor. Ao reabrir o claim, a sessão já encerrada responde 409 e a
  tela de erro é exibida.
- Sessões são one-shot: reuso de link/sid não dispara novo ciclo.
