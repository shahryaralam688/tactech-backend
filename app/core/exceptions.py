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
    def __init__(
        self,
        message: str,
        fields: dict[str, str] | None = None,
        *,
        status_code: int = 400,
        code: str = "VALIDATION_ERROR",
    ) -> None:
        super().__init__(message, status_code=status_code, code=code, fields=fields)


class NotFoundError(AppError):
    def __init__(self, message: str = "Not found.", *, code: str = "NOT_FOUND") -> None:
        super().__init__(message, status_code=404, code=code)


class ForbiddenError(AppError):
    def __init__(
        self,
        message: str = "You do not have access to this resource.",
        *,
        code: str = "FORBIDDEN",
    ) -> None:
        super().__init__(message, status_code=403, code=code)


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
        wait = max(1, int(retry_after))
        super().__init__(
            message,
            status_code=429,
            code="RATE_LIMITED",
            extra={"retryAfter": wait},
        )
        self.retry_after = wait


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


class AiQuotaExceededError(AppError):
    def __init__(
        self,
        message: str = "Free AI quota used up. Upgrade to continue.",
        *,
        product_hint: str = "ai.pro.monthly",
        quota: str = "chat",
    ) -> None:
        super().__init__(
            message,
            status_code=402,
            code="AI_QUOTA_EXCEEDED",
            extra={
                "action": "subscribe",
                "productHint": product_hint,
                "quota": quota,
            },
        )


class AiProviderNotConfiguredError(AppError):
    def __init__(
        self,
        message: str = "AI text provider is not configured.",
    ) -> None:
        super().__init__(message, status_code=503, code="AI_PROVIDER_NOT_CONFIGURED")


class AiCapabilityUnavailableError(AppError):
    def __init__(
        self,
        message: str,
        *,
        capability: str,
        status_code: int = 501,
    ) -> None:
        super().__init__(
            message,
            status_code=status_code,
            code="AI_CAPABILITY_UNAVAILABLE",
            extra={"capability": capability},
        )


class ProviderError(AppError):
    def __init__(self, message: str = "Payment provider is temporarily unavailable.") -> None:
        super().__init__(message, status_code=502, code="PROVIDER_ERROR")
