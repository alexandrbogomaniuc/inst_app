# igw/app/config.py
from functools import lru_cache
from pathlib import Path
from typing import Literal, Optional
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Load env from igw/.env and ignore unknown keys
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

    # Which login flow to use: "instagram_login" (direct IG) or "facebook_login" (Business via FB)
    OAUTH_FLOW: Literal["instagram_login", "facebook_login"] = "instagram_login"

    # ---- Instagram Login product (direct Instagram OAuth on instagram.com) ----
    # Add the "Instagram Login" product in the Meta dashboard and use those credentials here.
    IGBD_APP_ID: Optional[str] = None
    IGBD_APP_SECRET: Optional[str] = None
    IG_REDIRECT_URI: str = Field(..., env="IG_REDIRECT_URI")
    IG_SCOPES: str = Field("user_profile", env="IG_SCOPES")  # IG Login accepts user_profile (optionally user_media)

    # ---- Facebook Login (Instagram API with Facebook Login; Business/Creator) ----
    IG_CLIENT_ID: Optional[str] = None      # This is your Facebook App ID
    IG_CLIENT_SECRET: Optional[str] = None  # Facebook App secret
    GRAPH_VERSION: str = "v21.0"            # used for facebook.com dialog if you switch back

    # -------- Back-compat LOWERCASE ALIASES (legacy code safety) --------
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
    def ig_client_id(self) -> Optional[str]:
        return self.IG_CLIENT_ID

    @property
    def ig_client_secret(self) -> Optional[str]:
        return self.IG_CLIENT_SECRET

    @property
    def ig_redirect_uri(self) -> str:
        return self.IG_REDIRECT_URI

    @property
    def ig_scopes(self) -> str:
        return self.IG_SCOPES


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    env_path = Path(Settings.model_config["env_file"])  # type: ignore[index]
    print(f"Loaded settings (.env={'found' if env_path.exists() else 'missing'}) from: {env_path}")
    return s


settings = get_settings()
