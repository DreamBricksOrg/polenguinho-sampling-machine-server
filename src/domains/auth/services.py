from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from fastapi import HTTPException
from fastapi.security import OAuth2PasswordRequestForm

from infrastructure.config import settings
from .repositories import AdminAuthRepository
from .schemas import CreateAdminRequest, TokenResponse


class AuthService:
    def __init__(self, repository: AdminAuthRepository | None = None):
        self.repository = repository or AdminAuthRepository()

    def generate_jwt(self, username: str, role: str) -> str:
        expire = datetime.now(timezone.utc) + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
        payload = {"sub": username, "role": role, "exp": expire}
        return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)

    async def login(self, form_data: OAuth2PasswordRequestForm) -> TokenResponse:
        user = await self.repository.find_by_username(form_data.username)
        if not user:
            raise HTTPException(401, "Credenciais inválidas")
        if not bcrypt.checkpw(form_data.password.encode(), user["password"].encode()):
            raise HTTPException(401, "Credenciais inválidas")

        token = self.generate_jwt(user["username"], user.get("role", "user"))
        return TokenResponse(accessToken=token, expiresIn=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60)

    async def create_admin_user(self, data: CreateAdminRequest, authorization: str) -> dict:
        parts = authorization.split()
        if len(parts) != 2 or parts[0].lower() != "bearer":
            raise HTTPException(400, "Authorization header malformado")
        if parts[1] != settings.ADMIN_CREATION_TOKEN:
            raise HTTPException(403, "Token de criação inválido")

        existing = await self.repository.find_by_username(data.username)
        if existing:
            raise HTTPException(400, "Username já existe")

        hashed = bcrypt.hashpw(data.password.encode(), bcrypt.gensalt()).decode()
        await self.repository.create(data.username, hashed)
        return {"success": True, "message": "Usuário criado"}
