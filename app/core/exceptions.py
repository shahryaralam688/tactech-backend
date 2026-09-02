class AppError(Exception):
    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class InvalidCredentialsError(AppError):
    def __init__(self) -> None:
        super().__init__("Email or password is incorrect.", status_code=401)


class ValidationAppError(AppError):
    def __init__(self, message: str) -> None:
        super().__init__(message, status_code=400)


class NotFoundError(AppError):
    def __init__(self, message: str = "Not found.") -> None:
        super().__init__(message, status_code=404)


class ForbiddenError(AppError):
    def __init__(self, message: str = "You do not have access to this resource.") -> None:
        super().__init__(message, status_code=403)


class UnauthorizedError(AppError):
    def __init__(self, message: str = "Authentication required.") -> None:
        super().__init__(message, status_code=401)


class RateLimitError(AppError):
    def __init__(self) -> None:
        super().__init__("Too many attempts. Try again shortly.", status_code=429)
