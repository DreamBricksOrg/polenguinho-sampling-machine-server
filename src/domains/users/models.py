from __future__ import annotations

from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator
from typing import Optional, Literal
from datetime import date, datetime, timedelta, timezone


Status = Literal["registered", "eligible", "picked"]  # fluxo simples


def today_utc_date() -> date:
    return datetime.now(timezone.utc).date()


class Registration(BaseModel):
    id: Optional[str] = Field(None, alias="_id")

    # Dados de cadastro
    name: str
    email: EmailStr
    birthDate: date = Field(..., description="Data de nascimento (YYYY-MM-DD)")

    # Regras de retirada
    registerDay: date = Field(default_factory=today_utc_date, description="Dia do cadastro")
    canPickFrom: date = Field(
        default_factory=lambda: today_utc_date() + timedelta(days=1),
        description="A partir de qual dia a pessoa pode pegar suco"
    )
    status: Status = Field(default="registered", description="registered|eligible|picked")

    # Controle diário de retirada
    pickedDay: Optional[date] = Field(
        None, description="Dia em que pegou suco (se pegou)"
    )
    juicesPicked: int = Field(
        default=0, ge=0, description="Quantos sucos foram retirados no pickedDay"
    )

    # Auditoria
    createdAt: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updatedAt: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @field_validator("juicesPicked")
    @classmethod
    def _validate_juices(cls, v: int) -> int:
        # limite de sanidade; ajuste se a campanha permitir mais do que isso
        if v > 1000:
            raise ValueError("juicesPicked fora do esperado")
        return v

    @model_validator(mode="after")
    def _sync_status_dates(self) -> "Registration":
        """Garante coerência entre datas e status"""
        if self.canPickFrom <= self.registerDay and self.status == "registered":
            self.canPickFrom = self.registerDay + timedelta(days=1)

        if self.pickedDay:
            self.status = "picked" if self.juicesPicked > 0 else self.status

        return self

    def mark_picked(self, day: date, count: int) -> None:
        """Marcar retirada; use no worker/serviço de atualização."""
        self.pickedDay = day
        self.juicesPicked = max(0, count)
        self.status = "picked"
        self.updatedAt = datetime.now(timezone.utc)

    def mark_eligible_if_due(self, today: Optional[date] = None) -> None:
        """Tornar elegível quando chegar a data."""
        d = today or today_utc_date()
        if d >= self.canPickFrom and self.status == "registered":
            self.status = "eligible"
            self.updatedAt = datetime.now(timezone.utc)
