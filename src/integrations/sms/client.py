import logging
from typing import Final

import phonenumbers
import requests
from phonenumbers import NumberParseException

from infrastructure.config import settings
from shared.exceptions import AppError


logger = logging.getLogger(__name__)

SMS_SUCCESS_STATUS: Final[str] = "success"
SMS_MESSAGE_TYPE: Final[int] = 9


def format_to_e164(phone_number: str, country_code: str = "BR") -> str:
    try:
        parsed = phonenumbers.parse(phone_number, country_code)
    except NumberParseException as exc:
        logger.warning(
            "sms.format_error",
            extra={
                "phone_number": phone_number,
                "country_code": country_code,
                "error": str(exc),
            },
        )
        raise AppError(
            "Número de telefone inválido.",
            "sms_invalid_phone_number",
            422,
            {"phone_number": phone_number},
        ) from exc

    if not phonenumbers.is_valid_number(parsed):
        logger.warning(
            "sms.invalid_number",
            extra={
                "phone_number": phone_number,
                "country_code": country_code,
            },
        )
        raise AppError(
            "Número de telefone inválido.",
            "sms_invalid_phone_number",
            422,
            {"phone_number": phone_number},
        )

    return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)


def _get_sms_config() -> tuple[str, str, int]:
    api_url = getattr(settings, "SMS_API_URL", None)
    api_key = getattr(settings, "SMS_API_KEY", None)
    timeout = int(getattr(settings, "SMS_TIMEOUT_SECONDS", 10))

    if not api_url or not api_key:
        logger.error(
            "sms.config_missing",
            extra={
                "has_api_url": bool(api_url),
                "has_api_key": bool(api_key),
            },
        )
        raise AppError(
            "Configuração de SMS ausente.",
            "sms_config_missing",
            500,
        )

    return api_url, api_key, timeout


def send_sms_message(message: str, destination_number: str) -> bool:
    api_url, api_key, timeout = _get_sms_config()
    formatted_number = format_to_e164(destination_number)

    payload = {
        "key": api_key,
        "type": SMS_MESSAGE_TYPE,
        "number": formatted_number,
        "msg": message,
    }

    try:
        response = requests.post(api_url, json=payload, timeout=timeout)
        response_data = response.json()
    except requests.RequestException:
        logger.exception(
            "sms.request_exception",
            extra={
                "destination_number": formatted_number,
                "api_url": api_url,
            },
        )
        return False
    except ValueError:
        logger.exception(
            "sms.invalid_json_response",
            extra={
                "destination_number": formatted_number,
                "status_code": getattr(response, "status_code", None),
            },
        )
        return False

    success = response.status_code == 200 and response_data.get("status") == SMS_SUCCESS_STATUS

    if success:
        logger.info(
            "sms.sent",
            extra={
                "destination_number": formatted_number,
                "status_code": response.status_code,
            },
        )
        return True

    logger.error(
        "sms.failure",
        extra={
            "destination_number": formatted_number,
            "status_code": response.status_code,
            "response_data": response_data,
        },
    )
    return False


def send_queue_registration_sms(destination_number: str, queue_number: int, qr_code_url: str | None = None) -> bool:
    """
    Enviar quando a pessoa entra na fila.
    """
    body = (
        "Você entrou na fila da maquina.\n"
        f"Seu número na fila é {queue_number}."
    )
    if qr_code_url:
        body += f"\nAcompanhe sua posição em: {qr_code_url}"

    return send_sms_message(body, destination_number)


def send_queue_fifth_position_sms(destination_number: str, queue_number: int) -> bool:
    """
    Enviar quando a pessoa estiver na 5ª posição da fila.
    """
    body = (
        "Falta pouco para sua vez na maquina.\n"
        f"Seu número na fila é {queue_number} e você está entre os próximos 5."
    )
    return send_sms_message(body, destination_number)


def send_queue_next_up_sms(destination_number: str, queue_number: int) -> bool:
    """
    Enviar quando a pessoa for a próxima a jogar.
    """
    body = (
        "Sua vez na maquina está chegando.\n"
        f"Prepare-se: seu número da fila é {queue_number} e você é o próximo."
    )
    return send_sms_message(body, destination_number)
