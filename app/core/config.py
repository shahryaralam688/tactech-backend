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

    public_base_url: str = ""
    upload_dir: str = "uploads"
    max_upload_bytes: int = 5 * 1024 * 1024
    password_reset_expire_minutes: int = 60

    # AI coach — demo default is groq (free/fast). Switch to openai when ready.
    ai_provider: str = "groq"  # groq | openai | mock
    groq_api_key: str = ""
    groq_chat_model: str = "llama-3.1-8b-instant"
    groq_stt_model: str = "whisper-large-v3"
    openai_api_key: str = ""
    openai_chat_model: str = "gpt-4o-mini"
    openai_stt_model: str = "whisper-1"
    openai_tts_model: str = "tts-1"
    openai_embedding_model: str = "text-embedding-3-small"
    ai_tts_provider: str = "edge"  # edge | openai | none
    ai_tts_voice: str = "en-US-JennyNeural"
    ai_max_context_chunks: int = 8
    ai_chat_temperature: float = 0.4
    ai_chat_max_tokens: int = 700
    groq_vision_model: str = "meta-llama/llama-4-scout-17b-16e-instruct"
    openai_vision_model: str = "gpt-4o-mini"
    webrtc_stun_urls: str = "stun:stun.l.google.com:19302,stun:stun1.l.google.com:19302"

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
