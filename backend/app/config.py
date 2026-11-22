from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "dev"
    api_cors_origins: str = "*"

    database_url: str = "postgresql+psycopg://raw2reel:raw2reel@localhost:5432/raw2reel"
    redis_url: str = "redis://localhost:6379/0"
    work_dir: str = "./work"

    firebase_project_id: str = ""
    firebase_credentials_file: str = ""
    auth_dev_bypass: bool = False

    r2_account_id: str = ""
    r2_access_key_id: str = ""
    r2_secret_access_key: str = ""
    r2_bucket: str = "raw2reel"
    r2_presign_expires_seconds: int = 3600

    instagram_cookies_file: str = ""
    instagram_max_duration_seconds: int = 180
    instagram_max_filesize_mb: int = 200
    instagram_fallback_api_url: str = ""
    instagram_fallback_api_token: str = ""

    # Speech-to-text (faster-whisper). large-v3-turbo is ~8x faster than large-v3 on CPU with
    # similar accuracy; switch to large-v3 if Hindi/Hinglish quality needs it.
    whisper_model: str = "large-v3-turbo"
    whisper_compute_type: str = "int8"
    whisper_cpu_threads: int = 4
    # Voice notes (speak your script) want speed over the last bit of accuracy: ~6 s vs ~25 s
    voice_whisper_model: str = "small"
    models_dir: str = "/app/models"

    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-5-5"
    # Guard rails on spend: AI calls per user per day (style analysis, answers, edit plans)
    ai_daily_limit: int = 20
    # USD per million tokens (input, output) for the cost estimate in ai_usage
    ai_price_in_per_m: float = 2.0
    ai_price_out_per_m: float = 10.0

    @property
    def is_prod(self) -> bool:
        return self.app_env == "prod"

    @property
    def dev_bypass_enabled(self) -> bool:
        return self.auth_dev_bypass and not self.is_prod

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.api_cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
