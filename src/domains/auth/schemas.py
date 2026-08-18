from pydantic import BaseModel, Field

class TokenResponse(BaseModel):
    accessToken: str
    expiresIn: int

class CreateAdminRequest(BaseModel):
    username: str = Field(..., min_length=3)
    password: str = Field(..., min_length=8)
