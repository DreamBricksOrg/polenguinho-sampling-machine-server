from pydantic import BaseModel, HttpUrl

class ShortenerLoginResponse(BaseModel):
    accessToken: str
    expiresIn: int

class ShortenerCreateRequest(BaseModel):
    name: str
    url: HttpUrl

class ShortenerCreateResponse(BaseModel):
    slug: str
    qr_png: HttpUrl
    qr_svg: HttpUrl
