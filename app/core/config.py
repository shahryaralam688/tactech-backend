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
    # Avatar / media CDN (S3-compatible: AWS S3, Cloudflare R2, GCS HMAC).
    # When bucket is set, custom avatars upload to object storage; otherwise local + PUBLIC_BASE_URL.
    media_s3_bucket: str = ""
    media_s3_region: str = "auto"
    media_s3_endpoint_url: str = ""  # e.g. https://<account>.r2.cloudflarestorage.com
    media_s3_access_key_id: str = ""
    media_s3_secret_access_key: str = ""
    media_cdn_base_url: str = ""  # public HTTPS CDN origin, e.g. https://cdn.tactech.app
    media_s3_prefix: str = "avatars"
    default_avatar_asset: str = "Avatar_01_Color"

    # AI coach — free defaults: mock (no key) | huggingface | groq | openai
    ai_provider: str = "auto"  # auto | mock | huggingface | groq | openai
    hf_token: str = ""
    hf_chat_model: str = "meta-llama/Llama-3.1-8B-Instruct"
    hf_vision_model: str = "google/gemma-3-4b-it"
    groq_api_key: str = ""
    groq_chat_model: str = "openai/gpt-oss-20b"
    groq_stt_model: str = "whisper-large-v3"
    openai_api_key: str = ""
    openai_chat_model: str = "gpt-4o-mini"
    openai_stt_model: str = "whisper-1"
    openai_tts_model: str = "tts-1"
    openai_embedding_model: str = "text-embedding-3-small"
    ai_embedding_dimensions: int = 1536
    ai_tts_provider: str = "edge"  # edge | openai | none
    ai_tts_voice: str = "en-US-JennyNeural"
    ai_max_context_chunks: int = 8
    ai_chat_temperature: float = 0.65
    ai_chat_max_tokens: int = 450
    groq_vision_model: str = "openai/gpt-oss-20b"
    openai_vision_model: str = "gpt-4o-mini"
    webrtc_stun_urls: str = "stun:stun.l.google.com:19302,stun:stun1.l.google.com:19302"
    webrtc_turn_urls: str = ""
    webrtc_turn_username: str = ""
    webrtc_turn_credential: str = ""

    # AI coach rate limits (per user, sliding fixed window)
    coach_chat_rate_limit: int = 30
    coach_image_rate_limit: int = 10
    coach_voice_rate_limit: int = 20
    coach_rtc_rate_limit: int = 10
    coach_rate_window_seconds: int = 60

    # Human chat
    chat_message_max_chars: int = 4000
    chat_upload_max_bytes: int = 8 * 1024 * 1024  # default image
    chat_image_max_bytes: int = 8 * 1024 * 1024
    chat_video_max_bytes: int = 50 * 1024 * 1024
    chat_voice_max_bytes: int = 5 * 1024 * 1024
    chat_file_max_bytes: int = 15 * 1024 * 1024
    chat_rate_limit: int = 60
    chat_media_rate_limit: int = 20
    chat_rtc_rate_limit: int = 10
    chat_rate_window_seconds: int = 60
    chat_rtc_idle_seconds: int = 90
    chat_rtc_max_seconds: int = 60 * 60
    chat_edit_window_seconds: int = 15 * 60
    chat_delete_everyone_seconds: int = 60 * 60

    # Phase 2 — Trainer Boost (Stripe Checkout). Empty = billing routes return clear 400.
    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""
    stripe_publishable_key: str = ""
    stripe_success_url: str = "tactech://billing/boost/success?session_id={CHECKOUT_SESSION_ID}"
    stripe_cancel_url: str = "tactech://billing/boost/cancel"
    # Seed / staging price ids (override in .env after creating Stripe Prices)
    stripe_price_boost_7d: str = ""
    stripe_price_boost_30d: str = ""

    # Phase 3 — Trainee AI (Apple IAP). Empty keys → verify returns clear 400 (tests inject fake).
    apple_bundle_id: str = ""
    apple_issuer_id: str = ""
    apple_key_id: str = ""
    apple_private_key_p8: str = ""  # PEM contents; use \n for newlines in .env
    apple_environment: str = "Sandbox"  # Sandbox | Production
    # 0 = hard paywall (recommended production default); 3 = weekly free tease
    ai_free_tease_messages_per_week: int = 0
    # Returned on 402 AI_REQUIRED as productHint for iOS Subscribe CTA
    ai_product_hint: str = "ai.pro.monthly"

    # AI Gateway — swappable text + vision stubs (freemium quotas separate from provider)
    # gemini | groq | openai | auto (gemini→groq→mock)
    ai_text_provider: str = "auto"
    gemini_api_key: str = ""
    gemini_chat_model: str = "gemini-2.0-flash"
    ai_vision_pose_provider: str = "stub"
    ai_vision_food_provider: str = "stub"
    # Free daily AI chat messages without Pro (0 = no daily free; fall back to weekly tease / hard paywall)
    ai_free_chat_daily_limit: int = 10
    # Lifetime free structured plan generations for solo trainees (not monthly)
    ai_free_plan_generations: int = 1

    # APNs (device push). Empty → socket inbox still works; push logged as skipped.
    apns_key_id: str = ""
    apns_team_id: str = ""
    apns_bundle_id: str = ""  # defaults to apple_bundle_id when empty
    apns_private_key_p8: str = ""  # PEM; \n for newlines in .env
    apns_environment: str = "sandbox"  # sandbox | production

    # Phase 4 — Pakistan local boost wallets (JazzCash / Easypaisa)
    jazzcash_merchant_id: str = ""
    jazzcash_password: str = ""
    jazzcash_integrity_salt: str = ""
    jazzcash_return_url: str = "tactech://billing/boost/success"
    jazzcash_ipn_url: str = ""
    jazzcash_checkout_url: str = "https://sandbox.jazzcash.com.pk/CustomerPortal/transactionmanagement/merchantform/"

    easypaisa_store_id: str = ""
    easypaisa_hash_key: str = ""
    easypaisa_return_url: str = "tactech://billing/boost/success"
    easypaisa_ipn_url: str = ""
    easypaisa_checkout_url: str = ""

    boost_success_url: str = "tactech://billing/boost/success?attempt_id={ATTEMPT_ID}"
    boost_cancel_url: str = "tactech://billing/boost/cancel"

    # Phase 7 — coach verification (admin review via X-Admin-Key)
    admin_api_key: str = ""
    verify_doc_retention_days: int = 90
    verify_upload_max_bytes: int = 10 * 1024 * 1024
    verify_upload_ttl_seconds: int = 3600

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
