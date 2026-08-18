from typing import Any, Dict, List, Optional, Literal
from pydantic import BaseModel, Field


LogLevel = Literal["DEBUG","INFO","WARNING","ERROR","CRITICAL"]


class LogIn(BaseModel):
    message: str = Field(..., description="Mensagem do evento")
    level: LogLevel = "DEBUG"
    sessionId: Optional[str] = None
    userId: Optional[str] = None
    tags: Optional[List[str]] = None
    data: Optional[Dict[str, Any]] = None  # livre: slug, short_url, formato, etc.


class LogOut(BaseModel):
    ok: bool
