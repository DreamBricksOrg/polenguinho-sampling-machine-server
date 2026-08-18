import asyncio
import time
from datetime import datetime, timezone

import structlog
from infrastructure.config import settings
from integrations.logcenter.log_sender import LogSender
from infrastructure.hardware.serial_comm import SerialComm
from infrastructure.hardware.udp_sender import UDPSender
from .repositories import InventoryRepository

log = structlog.get_logger()
_udp_sender: UDPSender | None = None
_serial_comm: SerialComm | None = None
serial_lock = asyncio.Lock()


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def get_udp_sender() -> UDPSender:
    global _udp_sender
    if _udp_sender is None:
        _udp_sender = UDPSender(port=settings.UDP_PORT)
    return _udp_sender


def get_serial_comm() -> SerialComm:
    global _serial_comm
    if _serial_comm is None:
        if settings.SERIAL_FAKE:
            from infrastructure.hardware.serial_fake import FakeSerialComm
            _serial_comm = FakeSerialComm()
        else:
            _serial_comm = SerialComm(port=settings.SERIAL_PORT, baudrate=settings.SERIAL_BAUDRATE)
    return _serial_comm


class InventoryService:
    def __init__(self, repository: InventoryRepository | None = None):
        self.repository = repository or InventoryRepository()

    async def update_on_drop(self) -> bool:
        try:
            inventory_data = self.repository.load()
            old_quantity = inventory_data.get("current_quantity", 0)
            inventory_data["current_quantity"] = max(0, old_quantity - 1)
            inventory_data["total_dispensed"] = inventory_data.get("total_dispensed", 0) + 1
            inventory_data["last_updated"] = now_utc().isoformat()
            self.repository.save(inventory_data)
            log.info(
                "inventory-dispensed",
                old_quantity=old_quantity,
                new_quantity=inventory_data["current_quantity"],
                total_dispensed=inventory_data["total_dispensed"],
            )
            return True
        except Exception as exc:
            log.error("inventory-update-error", error=str(exc))
            return False

    async def update(self, data: dict, log_sender: LogSender) -> dict:
        current_data = self.repository.load()
        old_quantity = current_data.get("current_quantity", 0)
        updated_data = {
            **current_data,
            **data,
            "previous_quantity": old_quantity,
            "quantity_change": data.get("current_quantity", 0) - old_quantity,
            "last_updated": now_utc().isoformat(),
        }
        self.repository.save(updated_data)

        if "current_quantity" in data:
            log_sender.log("estoque_atualizado", additional={"old": old_quantity, "new": data["current_quantity"]}, status="SUCCESS", tags=["estoque", "atualizacao", "servidor"])
            async with serial_lock:
                get_serial_comm().send("reset")
            log.info(
                "inventory-updated",
                old_quantity=old_quantity,
                new_quantity=data["current_quantity"],
                quantity_change=updated_data["quantity_change"],
                total_dispensed=updated_data.get("total_dispensed", 0),
            )
        return {"status": "inventory_updated"}


class MachineService:
    def __init__(
        self,
        inventory_service: InventoryService | None = None,
    ):
        self.inventory = inventory_service or InventoryService()

    async def drop(self) -> None:
        async with serial_lock:
            get_serial_comm().send("drop")
        await self.inventory.update_on_drop()
        log.info("drop-sent")

    async def drop_value(self, quantity: int, timeout_seconds: float = 20) -> dict:
        log_sender = LogSender()
        udp_sender = get_udp_sender()
        async with serial_lock:
            serial_comm = get_serial_comm()
            serial_comm.send(str(quantity))
            start = time.time()
            while time.time() - start < timeout_seconds:
                response = serial_comm.receive()
                if response is not None:
                    try:
                        response_value = int(response)
                        if response_value == -1:
                            log_sender.log("erro_serial", additional="falha_na_dispensa", status="ERROR", tags=["serial", "dispensa", "erro", "servidor"])
                            log.error("serial-error", error="drop_failed", response=response_value)
                            udp_sender.send_with_confirmation("error")
                            return {"status": "failed", "quantity_requested": quantity, "quantity_dispensed": 0}
                        elif response_value >= quantity:
                            log.info("product-dropped", response=response_value, quantity=quantity)
                            for _ in range(response_value):
                                await self.inventory.update_on_drop()
                            log_sender.log("valor_dispensado", additional={"requested": quantity, "dispensed": response_value}, status="SUCCESS", tags=["dispensa", "servidor"])
                            udp_sender.send_with_confirmation("next")
                            return {"status": "completed", "quantity_requested": quantity, "quantity_dispensed": response_value}
                    except ValueError:
                        pass
                await asyncio.sleep(0.1)
        log_sender.log("tempo_esgotado_serial", status="ERROR", tags=["serial", "dispensa", "tempo_esgotado", "servidor"])
        log.error("serial-timeout")
        udp_sender.send_with_confirmation("timeout")
        return {"status": "failed", "quantity_requested": quantity, "quantity_dispensed": 0}

    async def drop_waiting_callback(self) -> str:
        log_sender = LogSender()
        udp_sender = get_udp_sender()
        async with serial_lock:
            serial_comm = get_serial_comm()
            serial_comm.send("drop")
            start = time.time()
            while time.time() - start < 20:
                response = serial_comm.receive()
                if response == "dropped":
                    log_sender.log("produto_dispensado", status="SUCCESS", tags=["produto", "dispensa", "sucesso", "servidor"])
                    log.info("product-dropped")
                    await self.inventory.update_on_drop()
                    udp_sender.send_with_confirmation("next")
                    return "completed"
                if response in ["hand_timeout", "out_of_stock"]:
                    log_sender.log("erro_serial", additional=response, status="ERROR", tags=["serial", "dispensa", "erro", "servidor"])
                    log.error("serial-error", error=response)
                    udp_sender.send_with_confirmation("error")
                    return "failed"
                await asyncio.sleep(0.1)
        log_sender.log("tempo_esgotado_serial", status="ERROR", tags=["serial", "dispensa", "tempo_esgotado", "servidor"])
        log.error("serial-timeout")
        udp_sender.send_with_confirmation("timeout")
        return "failed"

    async def pickup_cycle(
        self,
        timeout_seconds: float | None = None,
        on_timeout_seconds: float = 10,
    ) -> str:
        """Ciclo do modo QR estático: liga a máquina, espera o serial "1"
        (produto retirado), desliga. Roda em task background — nunca preso
        a request HTTP. "off" é enviado sempre, inclusive em erro/timeout."""
        timeout = timeout_seconds if timeout_seconds is not None else settings.PICKUP_TIMEOUT_SECONDS
        log_sender = LogSender()
        async with serial_lock:
            serial_comm = get_serial_comm()
            try:
                serial_comm.send("on")
                start = time.time()
                machine_on = False
                picked_up = False
                while time.time() - start < on_timeout_seconds:
                    response = serial_comm.receive()
                    if response == "on":
                        machine_on = True
                        break
                    if response == "1":
                        # "1" pode chegar antes da confirmação do "on" — não descartar
                        picked_up = True
                        break
                    await asyncio.sleep(0.1)
                if machine_on:
                    log.info("pickup-machine-on")
                elif not picked_up:
                    log.warning("pickup-machine-on-timeout")

                start = time.time()
                while picked_up or time.time() - start < timeout:
                    if picked_up or serial_comm.receive() == "1":
                        await self.inventory.update_on_drop()
                        log_sender.log("retirada_dispensada", status="SUCCESS", tags=["retirada", "dispensa", "sucesso", "servidor"])
                        log.info("pickup-dispensed")
                        return "completed"
                    await asyncio.sleep(0.1)

                log_sender.log("tempo_esgotado_retirada", status="ERROR", tags=["retirada", "dispensa", "tempo_esgotado", "servidor"])
                log.error("pickup-timeout")
                return "failed"
            except Exception as exc:
                log_sender.log("erro_retirada", additional=str(exc), status="ERROR", tags=["retirada", "dispensa", "erro", "servidor"])
                log.error("pickup-cycle-error", error=str(exc))
                return "failed"
            finally:
                try:
                    serial_comm.send("off")
                    log.info("pickup-machine-off")
                except Exception as off_exc:
                    log.error("pickup-off-failed", error=str(off_exc))

    async def admin_dispense(self, message: str) -> dict:
        async with serial_lock:
            get_serial_comm().send(message)
        await self.inventory.update_on_drop()
        LogSender().log("dispensa_acionada_pelo_admin", status="SUCCESS")
        log.info("admin-dispensed")
        return {"status": "admin_dispense"}

    async def send_serial_message(self, message: str, timeout_seconds: float = 10) -> dict:
        async with serial_lock:
            serial_comm = get_serial_comm()
            serial_comm.send(message)
            start_time = time.time()
            while time.time() - start_time < timeout_seconds:
                response = serial_comm.receive()
                if response is not None:
                    log.info("serial-message-response", message=message, response=response)
                    return {
                        "status": "received",
                        "message": message,
                        "response": response,
                    }
                await asyncio.sleep(0.1)

        log.error("serial-message-timeout", message=message, timeout_seconds=timeout_seconds)
        return {
            "status": "timeout",
            "message": message,
            "response": None,
        }

    async def turn_on(self) -> dict:
        log_sender = LogSender()
        async with serial_lock:
            serial_comm = get_serial_comm()
            udp_sender = get_udp_sender()
            serial_comm.send("on")
            start_time = time.time()
            while time.time() - start_time < 10:
                response = serial_comm.receive()
                if response == "on":
                    udp_sender.send_with_confirmation("machine_on")
                    log_sender.log("maquina_ligada", status="SUCCESS", tags=["maquina", "ligar", "sucesso", "servidor"])
                    log.info("machine-on")
                    return {"status": "machine_on"}
                await asyncio.sleep(0.1)
        log.error("machine-on-timeout")
        log_sender.log("tempo_esgotado_ligar_maquina", status="ERROR", tags=["maquina", "ligar", "tempo_esgotado", "servidor"])
        return {"status": "machine_dont_respond"}

    async def turn_off(self) -> dict:
        async with serial_lock:
            get_serial_comm().send("off")
        LogSender().log("maquina_desligada", status="SUCCESS", tags=["maquina", "desligar", "sucesso", "servidor"])
        log.info("machine-off")
        return {"status": "machine_turned_off"}

 
