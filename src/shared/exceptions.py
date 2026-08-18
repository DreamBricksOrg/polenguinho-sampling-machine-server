class AppError(Exception):
    def __init__(
        self,
        message: str,
        code: str = "app_error",
        status_code: int = 400,
        details: dict | None = None,
    ):
        super().__init__(message)
        self.message = message
        self.code = code
        self.status_code = status_code
        self.details = details or {}


class AuthError(AppError):
    def __init__(
        self,
        message: str = "Não autorizado.",
        code: str = "auth_error",
        details: dict | None = None,
    ):
        super().__init__(
            message=message,
            code=code,
            status_code=401,
            details=details,
        )