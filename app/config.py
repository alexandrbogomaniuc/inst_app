# igw/app/config.py
from __future__ import annotations

from pathlib import Path
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


def _find_env_file() -> Optional[Path]:
    """Try several locations for .env so devs can keep it in root or in igw/."""
    here = Path(__file__).resolve()
    candidates = [
        here.parents[2] / ".env",  # <project-root>/.env  (inst_app/.env)
        here.parents[1] / ".env",  # igw/.env
        Path.cwd() / ".env",       # working dir
    ]
    for c in candidates:
        if c.exists():
            return c
    return None


ENV_FILE = _find_env_file()
if ENV_FILE is None:
    # Make it loud and obvious during development
    print("WARNING: .env file not found (looked in project root, igw/, and CWD). "
          "Environment variables must be set another way.")

class Settings(BaseSettings):
    # ---- Database ----
    DB_URL: str

    # ---- Security / JWT ----
    JWT_SIGNING_KEY: str
    PASSWORD_BCRYPT_ROUNDS: int = 12

    # ---- Wallet defaults ----
    DEFAULT_WALLET_CURRENCIES: str = "USD,VND"
    DEFAULT_WALLET_TYPE: str = "CASH"

    # ---- Instagram Business Login ----
    IG_CLIENT_ID: str
    IG_CLIENT_SECRET: str
    IG_REDIRECT_URI: str
    IG_SCOPES: str = "instagram_business_basic"

    # pydantic-settings config
    model_config = SettingsConfigDict(
        env_file=str(ENV_FILE) if ENV_FILE else None,
        case_sensitive=False,
        extra="ignore",
    )


settings = Settings()
print(f"Loaded settings (.env={'found' if ENV_FILE else 'missing'}) "
      f"from: {str(ENV_FILE) if ENV_FILE else 'ENVIRONMENT'}")
