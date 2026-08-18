from pydantic import BaseModel, Field


class DropRequest(BaseModel):
    drop_code: str


class SerialMessageRequest(BaseModel):
    drop_code: str
    message: str = Field(..., min_length=1, description="Mensagem enviada para a serial")
    timeout_seconds: float = Field(10, gt=0, le=60, description="Tempo máximo aguardando resposta")


class DropValueRequest(BaseModel):
    drop_code: str
    quantity: int = Field(..., gt=0, description="Quantidade a ser dispensada")
    timeout_seconds: float = Field(20, gt=0, le=140, description="Tempo máximo aguardando resposta")
