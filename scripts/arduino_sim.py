"""Simulador do Arduino para testes sem hardware.

Uso com um par com0com (ex.: COM8 <-> COM9):
  - servidor com SERIAL_PORT=COM8 no .env
  - simulador na outra ponta:  python scripts/arduino_sim.py COM9

Comportamento:
  - responde "on" ao comando "on" (confirmação de máquina ligada)
  - imprime tudo que o servidor envia ("off", "drop", "reset", ...)
  - o que você digitar + Enter é enviado ao servidor:
      1        -> simula produto retirado (modo QR estático)
      dropped  -> simula drop concluído (modo totem)
      hand_timeout / out_of_stock -> simula erros do modo totem
"""

import sys
import threading

import serial

PORT = sys.argv[1] if len(sys.argv) > 1 else "COM9"
BAUDRATE = int(sys.argv[2]) if len(sys.argv) > 2 else 9600

ser = serial.Serial(PORT, BAUDRATE, timeout=0.1)
print(f"[arduino-sim] escutando em {PORT} @ {BAUDRATE}")
print("[arduino-sim] digite 1 + Enter para simular a retirada do produto\n")


def reader():
    while True:
        line = ser.readline().decode("utf-8", errors="ignore").strip()
        if not line:
            continue
        print(f"<- servidor: {line}")
        if line == "on":
            ser.write(b"on\n")
            print("-> sim: on (confirmacao)")


threading.Thread(target=reader, daemon=True).start()

for cmd in sys.stdin:
    cmd = cmd.strip()
    if not cmd:
        continue
    ser.write(cmd.encode("utf-8") + b"\n")
    print(f"-> sim: {cmd}")
