# igw/app/config.py
from __future__ import annotations
from functools import lru_cache
from pathlib import Path
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


_ENV_PATH = Path(__file__).resolve().parents[1] / ".env"


class Settings(BaseSettings):
    """
    Global app settings (non-provider-specific).
    NOTE: provider-specific settings (e.g., BSG bank config) live under
    igw/app/providers/<provider>/<bankId>/.env and are loaded separately.
    """

    # Load env from igw/.env and ignore unknown keys
    model_config = SettingsConfigDict(
        env_file=str(_ENV_PATH),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Core / infra
    APP_ENV: str = "dev"
    DB_URL: str
    REDIS_URL: str | None = None

    # Optional flags
    DEBUG: bool = False

    # Security
    JWT_SIGNING_KEY: str
    PASSWORD_BCRYPT_ROUNDS: int = 12

    # Wallet defaults
    DEFAULT_WALLET_CURRENCIES: str = "USD,VND"
    DEFAULT_WALLET_TYPE: str = "CASH"

    # ---- Instagram auth mode ----
    # valid values: "basic_display" (your current flow)
    IG_AUTH_MODE: str = "basic_display"

    # Instagram **Basic Display** credentials (you discovered these work with scope=instagram_business_basic)
    IGBD_APP_ID: str | None = Field(default=None, env="IGBD_APP_ID")
    IGBD_APP_SECRET: str | None = Field(default=None, env="IGBD_APP_SECRET")
    IGBD_REDIRECT_URI: str | None = Field(default=None, env="IGBD_REDIRECT_URI")
    IGBD_SCOPES: str = Field(default="instagram_business_basic", env="IGBD_SCOPES")

    # -------- Back-compat LOWERCASE ALIASES (keep old code working) --------
    @property
    def db_url(self) -> str:  # legacy alias
        return self.DB_URL

    @property
    def redis_url(self) -> str | None:
        return self.REDIS_URL

    @property
    def jwt_signing_key(self) -> str:
        return self.JWT_SIGNING_KEY


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    print(f"Loaded settings (.env={'found' if _ENV_PATH.exists() else 'missing'}) from: {_ENV_PATH}")
    return s


settings = get_settings()
