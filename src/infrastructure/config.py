from pydantic import Field, model_validator
from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    # Mode
    USE_FORM: bool = Field(True, env="USE_FORM")

    BASE_URL: str = Field(..., env="BASE_URL")
    APP_NAME: str = Field("Sample Machine", env="APP_NAME")
    ENV: str = Field("dev", env="ENV")
    HOST: str = Field("0.0.0.0", env="HOST")
    PORT: int = Field(8000, env="PORT")

    # Mongo — obrigatório apenas com USE_FORM=true
    MONGO_URI: Optional[str] = Field(default=None, env="MONGO_URI")
    MONGO_DB: str = Field("users_db", env="MONGO_DB")
    MONGO_DEBUG: bool = Field(False, env="MONGO_DEBUG")

    # JWT — obrigatório apenas com USE_FORM=true
    JWT_SECRET: Optional[str] = Field(default=None, env="JWT_SECRET")
    JWT_ALGORITHM: str = Field("HS256", env="JWT_ALGORITHM")
    ACCESS_TOKEN_EXPIRE_MINUTES: int = Field(60 * 24, env="ACCESS_TOKEN_EXPIRE_MINUTES")
    ADMIN_CREATION_TOKEN: Optional[str] = Field(default=None, env="ADMIN_CREATION_TOKEN")

    # Sentry
    SENTRY_DSN: Optional[str] = Field(default=None, env="SENTRY_DSN")

    # Cache — obrigatório apenas com USE_FORM=true
    REDIS_URL: Optional[str] = Field(default=None, env="REDIS_URL")

    # LogCenter
    LOG_API: Optional[str] = Field(default=None, env="LOG_API")
    LOG_API_KEY: Optional[str] = Field(default=None, env="LOG_API_KEY")
    LOG_PROJECT_ID: Optional[str] = Field(default=None, env="LOG_PROJECT_ID")
    DEVICE_ID_HEADER: Optional[str] = Field(default=None, env="DEVICE_ID_HEADER")
    API_KEY_HEADER: Optional[str] = Field(default=None, env="API_KEY_HEADER")

    # Admin simples (sem USE_FORM)
    SAMPLE_ADMIN_USER: str = Field("sampleadmin", env="SAMPLE_ADMIN_USER")
    SAMPLE_ADMIN_PASSWORD: str = Field("31773177", env="SAMPLE_ADMIN_PASSWORD")

    # Shortener — obrigatório apenas com USE_FORM=true
    SHORTENER_BASE_URL: str = Field("https://go.dbpe.com.br", env="SHORTENER_BASE_URL")
    SHORTENER_USER: Optional[str] = Field(default=None, env="SHORTENER_USER")
    SHORTENER_PASSWORD: Optional[str] = Field(default=None, env="SHORTENER_PASSWORD")

    # Mongo
    MONGO_TLS: bool = Field(True, env="MONGO_TLS")

    # Cadastro
    CADASTRO_BASE_URL: str = Field("https://samplemachine.ngrok.app/api/sample/welcome", env="CADASTRO_BASE_URL")

    # Serial
    SERIAL_PORT: str = Field("COM3", env="SERIAL_PORT")
    SERIAL_BAUDRATE: int = Field(9600, env="SERIAL_BAUDRATE")
    SERIAL_FAKE: bool = Field(False, env="SERIAL_FAKE")

    # UDP
    UDP_PORT: int = Field(5004, env="UDP_PORT")

    # SMS
    SMS_API_URL: Optional[str] = Field(default=None, env="SMS_API_URL")
    SMS_API_KEY: Optional[str] = Field(default=None, env="SMS_API_KEY")
    SMS_TIMEOUT_SECONDS: int = Field(default=10, env="SMS_TIMEOUT_SECONDS")

    # Machine
    DROP_CODE: str = Field(..., env="DROP_CODE")
    PICKUP_TIMEOUT_SECONDS: int = Field(60, env="PICKUP_TIMEOUT_SECONDS")
    PICKUP_COOLDOWN_HOURS: float = Field(12, env="PICKUP_COOLDOWN_HOURS")
    PICKUP_COOKIE_BLOCK_HOURS: float = Field(12, env="PICKUP_COOKIE_BLOCK_HOURS")

    # Horário de funcionamento (formato 24h, ex.: 10 às 20)
    SAMPLE_OPEN_HOUR: int = Field(10, env="SAMPLE_OPEN_HOUR")
    SAMPLE_CLOSE_HOUR: int = Field(20, env="SAMPLE_CLOSE_HOUR")
    SAMPLE_TIMEZONE: str = Field("America/Sao_Paulo", env="SAMPLE_TIMEZONE")

    # Criptografia dos dados do formulário (RSA+AES no navegador) — opcional, desligada por padrão
    ENCRYPTION_ENABLED: bool = Field(False, env="ENCRYPTION_ENABLED")

    @model_validator(mode="after")
    def check_form_deps(self) -> "Settings":
        if self.USE_FORM:
            missing = [
                name for name, val in {
                    "MONGO_URI": self.MONGO_URI,
                    "JWT_SECRET": self.JWT_SECRET,
                    "ADMIN_CREATION_TOKEN": self.ADMIN_CREATION_TOKEN,
                    "REDIS_URL": self.REDIS_URL,
                    "SHORTENER_USER": self.SHORTENER_USER,
                    "SHORTENER_PASSWORD": self.SHORTENER_PASSWORD
                }.items() if not val
            ]
            if missing:
                raise ValueError(f"USE_FORM=true requer as variáveis: {', '.join(missing)}")
        return self

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"


settings = Settings()