from pydantic import BaseModel, EmailStr, Field, AnyUrl, HttpUrl, model_validator
from typing import Optional, Literal
from datetime import datetime


Status = Literal["registered", "picked"]


# ---------- Session ----------
class SessionCompleteRequest(BaseModel):
    session_id: str
    slug: str


class SessionCompleteResponse(BaseModel):
    status: str
    session_id: str


class SessionPickupRequest(BaseModel):
    session_id: str
    slug: str


class SessionPickupResponse(BaseModel):
    status: str
    session_id: str


class QRCodeInitResponse(BaseModel):
    session_id: str
    short_url: HttpUrl
    slug: str
    qr_png: HttpUrl
    qr_svg: HttpUrl


class SessionGetResponse(BaseModel):
    session_id: str
    slug: str
    status: Literal["pending", "form_shown", "processing", "completed", "failed", "aborted"]
    mode: Optional[str] = None
    short_url: Optional[AnyUrl] = None
    created_at: datetime
    form_opened_at: Optional[datetime] = None
    processing_started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


# ---------- Requests ----------
class UserInitRequest(BaseModel):
    name: str = Field(..., min_length=1)
    email: Optional[EmailStr] = None
    phone: Optional[str] = Field(None, description="Celular no formato (99) 99999-9999")
    code: str
    registerDay: Optional[datetime] = None

    # Preenchidos pelo formulário quando ENCRYPTION_ENABLED=true: name/email/phone
    # acima são ignorados e os campos abaixo (cifrados no navegador com RSA+AES)
    # são usados no lugar. emailHash vem do SHA-256 do e-mail em texto puro,
    # calculado no cliente, para permitir a deduplicação sem expor o e-mail.
    encrypted: bool = False
    encName: Optional[str] = None
    encEmail: Optional[str] = None
    encPhone: Optional[str] = None
    emailHash: Optional[str] = None

    @model_validator(mode="after")
    def _check_encrypted_or_plain(self) -> "UserInitRequest":
        if self.encrypted:
            if not (self.encName and self.encEmail and self.emailHash):
                raise ValueError("Cadastro criptografado requer encName, encEmail e emailHash")
        elif not self.email:
            raise ValueError("email é obrigatório")
        return self


class UserUpdateRequest(BaseModel):
    name: Optional[str] = Field(None, min_length=1)

class UserPickupRequest(BaseModel):
    """Usado pelo worker ou endpoint para registrar a retirada de sucos."""
    id: Optional[str] = None
    email: Optional[EmailStr] = None
    day: datetime = Field(..., description="Dia da retirada")
    productsPicked: int = Field(..., ge=1, description="Quantidade retirada nesse dia")


# ---------- Responses ----------
# email é `str` (não EmailStr) porque, com ENCRYPTION_ENABLED=true, o valor
# armazenado/retornado é o texto cifrado (RSA+AES), que não tem formato de e-mail.
class UserInitResponse(BaseModel):
    id: str
    name: str
    email: str
    status: Status
    registerDay: datetime
    canPickFrom: datetime


class UserGetResponse(BaseModel):
    id: str
    name: str
    email: str
    phone: Optional[str] = None
    status: Status
    registerDay: datetime
    canPickFrom: datetime
    pickedDay: Optional[datetime] = None
    productsPicked: int = 0

class UserPickupResponse(BaseModel):
    id: str
    email: str
    pickedDay: datetime
    productsPicked: int
    status: Status  # deve vir "picked"