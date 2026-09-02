from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "TacTech"
    app_env: str = "development"
    log_level: str = "INFO"

    database_url: str
    redis_url: str

    jwt_secret: str
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 15
    refresh_token_expire_days: int = 30

    cors_origins: str = "http://localhost,http://127.0.0.1"

    seed_trainer_password: str = Field(default="trainer123")
    seed_trainee_password: str = Field(default="trainee123")

    login_rate_limit: int = 10
    login_rate_window_seconds: int = 60

    @field_validator("jwt_secret")
    @classmethod
    def jwt_secret_must_be_set(cls, value: str) -> str:
        if not value or value in {"replace-with-a-long-random-secret", "change-me"}:
            raise ValueError("JWT_SECRET must be set to a strong random value")
        if len(value) < 32:
            raise ValueError("JWT_SECRET must be at least 32 characters")
        return value

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
