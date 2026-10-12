class AppError(Exception):
    def __init__(
        self,
        message: str,
        status_code: int = 400,
        code: str | None = None,
        fields: dict[str, str] | None = None,
        *,
        extra: dict | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.code = code
        self.fields = fields
        self.extra = extra


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
    def __init__(
        self,
        message: str,
        fields: dict[str, str] | None = None,
        *,
        code: str = "CONFLICT",
    ) -> None:
        super().__init__(message, status_code=409, code=code, fields=fields)


class FileTooLargeError(AppError):
    def __init__(self, message: str = "File is too large.") -> None:
        super().__init__(message, status_code=413, code="PAYLOAD_TOO_LARGE")


class RateLimitError(AppError):
    def __init__(
        self,
        message: str = "Too many attempts. Try again shortly.",
        *,
        retry_after: int = 60,
    ) -> None:
        super().__init__(message, status_code=429, code="RATE_LIMITED")
        self.retry_after = max(1, int(retry_after))


class PayloadTooLargeError(AppError):
    def __init__(self, message: str = "File is too large.") -> None:
        super().__init__(message, status_code=413, code="PAYLOAD_TOO_LARGE")


class UnsupportedMediaError(AppError):
    def __init__(self, message: str = "Unsupported media type.") -> None:
        super().__init__(message, status_code=415, code="UNSUPPORTED_MEDIA")


class ProviderUnavailableError(AppError):
    def __init__(self, message: str = "AI provider is temporarily unavailable.") -> None:
        super().__init__(message, status_code=503, code="PROVIDER_UNAVAILABLE")


class AiRequiredError(AppError):
    def __init__(
        self,
        message: str = "AI Coach Pro is required to continue.",
        *,
        product_hint: str = "ai.pro.monthly",
    ) -> None:
        super().__init__(
            message,
            status_code=402,
            code="AI_REQUIRED",
            extra={
                "action": "subscribe",
                "productHint": product_hint,
            },
        )


class ProviderError(AppError):
    def __init__(self, message: str = "Payment provider is temporarily unavailable.") -> None:
        super().__init__(message, status_code=502, code="PROVIDER_ERROR")
