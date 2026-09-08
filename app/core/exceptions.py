class AppError(Exception):
    def __init__(
        self,
        message: str,
        status_code: int = 400,
        code: str | None = None,
        fields: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.code = code
        self.fields = fields


class InvalidCredentialsError(AppError):
    def __init__(self) -> None:
        super().__init__("Email or password is incorrect.", status_code=401, code="INVALID_CREDENTIALS")


class ValidationAppError(AppError):
    def __init__(self, message: str, fields: dict[str, str] | None = None) -> None:
        super().__init__(message, status_code=400, code="VALIDATION_ERROR", fields=fields)


class NotFoundError(AppError):
    def __init__(self, message: str = "Not found.") -> None:
        super().__init__(message, status_code=404, code="NOT_FOUND")


class ForbiddenError(AppError):
    def __init__(self, message: str = "You do not have access to this resource.") -> None:
        super().__init__(message, status_code=403, code="FORBIDDEN")


class UnauthorizedError(AppError):
    def __init__(self, message: str = "Authentication required.") -> None:
        super().__init__(message, status_code=401, code="UNAUTHORIZED")


class ConflictError(AppError):
    def __init__(self, message: str, fields: dict[str, str] | None = None) -> None:
        super().__init__(message, status_code=409, code="CONFLICT", fields=fields)


class FileTooLargeError(AppError):
    def __init__(self, message: str = "File is too large.") -> None:
        super().__init__(message, status_code=413, code="FILE_TOO_LARGE")


class RateLimitError(AppError):
    def __init__(self) -> None:
        super().__init__("Too many attempts. Try again shortly.", status_code=429, code="RATE_LIMITED")
