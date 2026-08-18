# Design — Bloqueio de retirada repetida por cookie (12h)

**Data:** 2026-08-10
**Status:** aprovado em conversa

## Objetivo

Impedir que a mesma pessoa (mesmo navegador/dispositivo) inicie o fluxo de
retirada novamente dentro de um período configurável (padrão 12h) logo após
concluir uma retirada com sucesso. O bloqueio acontece **antes** do
formulário de cadastro, em `GET /api/sample/start`, evitando que a pessoa
gaste tempo preenchendo o cadastro para só depois ser barrada.

Esse bloqueio é uma camada adicional e independente do cooldown por e-mail
já existente em `UserService.create_user` (`PICKUP_COOLDOWN_HOURS`, ver
`src/domains/users/services.py`). O cooldown por e-mail continua existindo;
o cookie apenas adianta a barreira para antes do cadastro, funcionando
mesmo que a pessoa pretenda usar um e-mail diferente.

## Fluxo

```
[Celular]                          [Servidor]
    |                                  |
    | ... fluxo normal completa ...    |
    | GET /api/sample/thanks           | seta cookie sample_pickup_block
    |←—————————————————————————————————|   valor = "{session_id}:{epoch}"
    |                                  |
    | (dentro de 12h)                  |
    | GET /api/sample/start            |
    |————————————————————————————————→ | lê cookie; now - epoch < 12h?
    |                                  |   sim → renderiza error.html
    | error.html                       |   (não cria sessão nova)
    |←—————————————————————————————————|
    |                                  |
    | (depois de 12h, ou sem cookie)   |
    | GET /api/sample/start            |
    |————————————————————————————————→ | segue fluxo normal (cria sessão,
    | 302 → /form?sid=..&slug=..       |   redireciona pro form)
    |←—————————————————————————————————|
```

## Decisões

1. **Sem assinatura/criptografia no cookie.** O valor é texto simples
   `"{session_id}:{timestamp_epoch}"`. É editável via DevTools — aceito
   deliberadamente: é uma camada de conveniência para reduzir retiradas
   repetidas por acidente/pressa, não um controle de segurança. O cooldown
   por e-mail no cadastro continua sendo a barreira mais difícil de burlar.

2. **Onde grava o cookie: `GET /api/sample/thanks`.** Essa rota só é
   alcançada quando `claim.html` observa `status == "completed"` via
   polling — ou seja, só grava o cookie quando a retirada realmente foi
   concluída (produto dispensado), não em tentativas incompletas ou
   falhas.

3. **Onde verifica: `GET /api/sample/start`.** Antes de chamar
   `SessionService().init_static_session()`, lê `request.cookies.get(
   "sample_pickup_block")`. Se presente e dentro da janela de bloqueio,
   renderiza `error.html` diretamente (sem criar sessão nova, sem
   redirect). Reaproveita o template `error.html` existente — sua imagem
   atual (`JA_RETIROU_TEXTO.png`) já é semanticamente adequada para esse
   caso, sem necessidade de alteração.

4. **Parsing tolerante (fail-open).** Cookie ausente, malformado (não
   bate o padrão `"<str>:<int>"`) ou com timestamp inválido → tratado como
   "não bloqueado", segue o fluxo normal. Erros de parsing não devem
   quebrar o endpoint.

5. **Nova variável de ambiente: `PICKUP_COOKIE_BLOCK_HOURS`** (default
   `12`, float, mesmo padrão de `PICKUP_COOLDOWN_HOURS`). Independente
   dessa última — controla exclusivamente a janela do cookie.

6. **Atributos do cookie:** `httponly=True`, `samesite="lax"`,
   `secure=(settings.ENV != "dev")`, `path="/api/sample"`,
   `max_age=int(PICKUP_COOKIE_BLOCK_HOURS * 3600)`.

7. **Logging.** Ao bloquear em `/start`, log via `LogSender().log(
   "servidor_start_blocked", ...)`, seguindo o padrão `servidor_{pagina}`
   já adotado nas outras rotas de página deste fluxo (`servidor_form`,
   `servidor_claim`, `servidor_error`).

## Fora de escopo

- Fluxo do totem/QR dinâmico (`POST /api/sample/qrcode/init`) — o pedido
  foi restrito a `GET /api/sample/start` (modo QR estático).
- Qualquer alteração no cooldown por e-mail existente.
- Qualquer forma de invalidar o bloqueio remotamente (ex.: admin limpar o
  cookie de alguém) — não foi pedido.

## Testes

Estender `tests/test_static_session.py`:
- Sem cookie → `/start` segue fluxo normal (cria sessão, 302).
- Cookie com timestamp recente (< 12h) → `/start` retorna `error.html`,
  sem criar sessão nova.
- Cookie com timestamp antigo (>= 12h) → `/start` segue fluxo normal.
- Cookie malformado (ex.: valor sem `:`, timestamp não numérico) → `/start`
  segue fluxo normal (fail-open).
- `GET /api/sample/thanks` seta o cookie `sample_pickup_block` com
  `session_id` e timestamp atual na resposta.
