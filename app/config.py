# igw/app/config.py
from functools import lru_cache
from pathlib import Path
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
    DEBUG: bool = False

    # Security
    JWT_SIGNING_KEY: str
    PASSWORD_BCRYPT_ROUNDS: int = 12

    # Wallet defaults
    DEFAULT_WALLET_CURRENCIES: str = "USD,VND"
    DEFAULT_WALLET_TYPE: str = "CASH"

    # Which Instagram auth flow to use: "basic_display" or "business_login"
    IG_AUTH_MODE: str = Field("basic_display", env="IG_AUTH_MODE")

    # --- Instagram Basic Display (Instagram-branded consent page) ---
    IGBD_APP_ID: str | None = Field(default=None, env="IGBD_APP_ID")
    IGBD_APP_SECRET: str | None = Field(default=None, env="IGBD_APP_SECRET")
    IGBD_REDIRECT_URI: str | None = Field(default=None, env="IGBD_REDIRECT_URI")
    IGBD_SCOPES: str = Field("user_profile", env="IGBD_SCOPES")

    # --- Instagram API with Facebook Login (kept for future use) ---
    IG_CLIENT_ID: str | None = Field(default=None, env="IG_CLIENT_ID")
    IG_CLIENT_SECRET: str | None = Field(default=None, env="IG_CLIENT_SECRET")
    IG_REDIRECT_URI: str | None = Field(default=None, env="IG_REDIRECT_URI")
    IG_SCOPES: str = Field("public_profile,email", env="IG_SCOPES")
    GRAPH_VERSION: str = Field("v21.0", env="GRAPH_VERSION")

    # ---------- Back-compat LOWERCASE aliases ----------
    @property
    def db_url(self) -> str:
        return self.DB_URL

    @property
    def jwt_signing_key(self) -> str:
        return self.JWT_SIGNING_KEY

    # Business login aliases
    @property
    def ig_client_id(self) -> str | None:
        return self.IG_CLIENT_ID

    @property
    def ig_client_secret(self) -> str | None:
        return self.IG_CLIENT_SECRET

    @property
    def ig_redirect_uri(self) -> str | None:
        return self.IG_REDIRECT_URI

    @property
    def ig_scopes(self) -> str:
        return self.IG_SCOPES

    # Basic Display aliases
    @property
    def igbd_app_id(self) -> str | None:
        return self.IGBD_APP_ID

    @property
    def igbd_app_secret(self) -> str | None:
        return self.IGBD_APP_SECRET

    @property
    def igbd_redirect_uri(self) -> str | None:
        return self.IGBD_REDIRECT_URI

    @property
    def igbd_scopes(self) -> str:
        return self.IGBD_SCOPES


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    env_path = Path(Settings.model_config["env_file"])  # type: ignore[index]
    print(f"Loaded settings (.env={'found' if env_path.exists() else 'missing'}) from: {env_path}")
    return s


settings = get_settings()
