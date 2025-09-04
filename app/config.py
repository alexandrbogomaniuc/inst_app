# igw/app/config.py
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Central app settings. Loads env from igw/.env.
    We keep canonical IG_* names (Instagram Basic Display)
    and back-compat aliases (IGBD_* and lowercase helpers).
    """

    # Load .env from igw/.env and ignore unknown keys
    model_config = SettingsConfigDict(
        env_file=str(Path(__file__).resolve().parents[1] / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Core / infra
    APP_ENV: str = "dev"
    DB_URL: str
    REDIS_URL: Optional[str] = None

    # Optional convenience flags present in your .env
    DEBUG: bool = False
    PYTHONPATH: Optional[str] = None

    # Security
    JWT_SIGNING_KEY: str
    PASSWORD_BCRYPT_ROUNDS: int = 12

    # Wallet defaults
    DEFAULT_WALLET_CURRENCIES: str = "USD,VND"
    DEFAULT_WALLET_TYPE: str = "CASH"

    # Instagram Basic Display (canonical)
    IG_CLIENT_ID: str = Field(..., env="IG_CLIENT_ID")
    IG_CLIENT_SECRET: str = Field(..., env="IG_CLIENT_SECRET")
    IG_REDIRECT_URI: str = Field(..., env="IG_REDIRECT_URI")
    IG_SCOPES: str = Field("user_profile", env="IG_SCOPES")

    # (Optional) Facebook/Graph (unused by Basic Display but kept)
    FB_APP_ID: Optional[str] = Field(None, env="FB_APP_ID")
    FB_APP_SECRET: Optional[str] = Field(None, env="FB_APP_SECRET")
    GRAPH_VERSION: str = Field("v20.0", env="GRAPH_VERSION")

    # -------- Back-compat LOWERCASE helpers --------
    @property
    def db_url(self) -> str:
        return self.DB_URL

    @property
    def redis_url(self) -> Optional[str]:
        return self.REDIS_URL

    @property
    def jwt_signing_key(self) -> str:
        return self.JWT_SIGNING_KEY

    @property
    def ig_client_id(self) -> str:
        return self.IG_CLIENT_ID

    @property
    def ig_client_secret(self) -> str:
        return self.IG_CLIENT_SECRET

    @property
    def ig_redirect_uri(self) -> str:
        return self.IG_REDIRECT_URI

    @property
    def ig_scopes(self) -> str:
        return self.IG_SCOPES

    # -------- Back-compat IGBD_* aliases (used by older code) --------
    @property
    def IGBD_APP_ID(self) -> str:
        return self.IG_CLIENT_ID

    @property
    def IGBD_APP_SECRET(self) -> str:
        return self.IG_CLIENT_SECRET

    @property
    def IGBD_REDIRECT_URI(self) -> str:
        return self.IG_REDIRECT_URI

    @property
    def IGBD_SCOPES(self) -> str:
        return self.IG_SCOPES


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    env_path = Path(Settings.model_config["env_file"])  # type: ignore[index]
    print(f"Loaded settings (.env={'found' if env_path.exists() else 'missing'}) from: {env_path}")
    return s


settings = get_settings()
