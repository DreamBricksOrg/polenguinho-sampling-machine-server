from fastapi import APIRouter, Depends, Header
from fastapi.security import HTTPBearer, OAuth2PasswordRequestForm

from .services import AuthService
from .schemas import CreateAdminRequest, TokenResponse

router = APIRouter(prefix="/api/auth")
security = HTTPBearer()


@router.post("/login", response_model=TokenResponse)
async def login(form_data: OAuth2PasswordRequestForm = Depends()):
    return await AuthService().login(form_data)


@router.post("/create", status_code=201)
async def create_admin_user(data: CreateAdminRequest, authorization: str = Header(..., alias="Authorization")):
    return await AuthService().create_admin_user(data, authorization)
