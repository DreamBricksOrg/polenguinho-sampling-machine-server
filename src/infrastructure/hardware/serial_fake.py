"""Serial fake para rodar o servidor sem Arduino (SERIAL_FAKE=true no .env).

Mesma interface do SerialComm (send/receive). Mensagens do "Arduino" são
injetadas via POST /api/sample/admin/serial/inject — ex.: {"message": "1"}
para simular a retirada do produto no modo QR estático.
"""

from collections import deque

import structlog

log = structlog.get_logger()


class FakeSerialComm:
    def __init__(self):
        self._incoming = deque()
        self.sent = []

    def send(self, msg):
        msg = msg.strip()
        self.sent.append(msg)
        log.info("fake-serial-send", message=msg)
        if msg == "on":
            # Arduino real confirma "on" — o fake confirma na hora
            self._incoming.append("on")

    def receive(self):
        return self._incoming.popleft() if self._incoming else None

    def inject(self, msg: str):
        msg = msg.strip().lower()
        self._incoming.append(msg)
        log.info("fake-serial-inject", message=msg)
