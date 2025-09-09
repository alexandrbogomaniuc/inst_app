from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Optional

from dotenv import dotenv_values
from pydantic import BaseModel, Field, AliasChoices
from pydantic_settings import BaseSettings, SettingsConfigDict

_BASE_DIR = Path(__file__).resolve().parent


class BsgBaseSettings(BaseSettings):
    """
    Provider-wide defaults from igw/app/providers/bsg/.env
    """
    model_config = SettingsConfigDict(
        env_file=str(_BASE_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    BSG_DEFAULT_BANK_ID: Optional[int] = None
    BSG_CW_START_BASE_DEFAULT: Optional[str] = None

    # Fallback token lifetimes if a bank doesn't specify its own values
    BSG_TOKEN_GAME_EXP_MIN_DEFAULT: int = 60
    BSG_TOKEN_LOBBY_EXP_MIN_DEFAULT: int = 1440


class BankModel(BaseModel):
    """
    Per-bank configuration from igw/app/providers/bsg/<bankId>/.env
    Accepts legacy names via aliases.
    """
    BSG_BANK_ID: int = Field(validation_alias=AliasChoices("BSG_BANK_ID", "bsg_bank_id", "BANK_ID"))
    BSG_PASS_KEY: str = Field(validation_alias=AliasChoices("BSG_PASS_KEY", "PASS_KEY", "pass_key"))
    BSG_PROTOCOL: str = Field(default="xml", validation_alias=AliasChoices("BSG_PROTOCOL", "PROTOCOL", "protocol"))
    BSG_DEFAULT_GAME_ID: int = Field(validation_alias=AliasChoices("BSG_DEFAULT_GAME_ID", "DEFAULT_GAME_ID", "gameId"))

    BSG_CW_START_BASE: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("BSG_CW_START_BASE", "CW_START_BASE", "START_HOST")
    )
    BSG_DEFAULT_CURRENCY: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("BSG_DEFAULT_CURRENCY", "DEFAULT_CURRENCY", "currency")
    )

    # Per-bank overrides for token lifetimes (minutes)
    BSG_TOKEN_GAME_EXP_MIN: Optional[int] = Field(
        default=None,
        validation_alias=AliasChoices("BSG_TOKEN_GAME_EXP_MIN", "TOKEN_GAME_EXP_MIN")
    )
    BSG_TOKEN_LOBBY_EXP_MIN: Optional[int] = Field(
        default=None,
        validation_alias=AliasChoices("BSG_TOKEN_LOBBY_EXP_MIN", "TOKEN_LOBBY_EXP_MIN")
    )


@lru_cache
def bsg_settings() -> BsgBaseSettings:
    s = BsgBaseSettings()
    env_path = Path(BsgBaseSettings.model_config["env_file"])  # type: ignore[index]
    print(f"[BSG] Loaded base settings (.env={'found' if env_path.exists() else 'missing'}) from: {env_path}")
    return s


def _bank_env_path(bank_id: int) -> Path:
    return _BASE_DIR / str(bank_id) / ".env"


def list_available_banks() -> List[int]:
    banks: List[int] = []
    for child in _BASE_DIR.iterdir():
        if child.is_dir() and child.name.isdigit() and (_BASE_DIR / child.name / ".env").exists():
            banks.append(int(child.name))
    return sorted(banks)


def resolve_bank_id(query_param_bank_id: Optional[int]) -> int:
    if query_param_bank_id:
        return int(query_param_bank_id)
    base = bsg_settings()
    if base.BSG_DEFAULT_BANK_ID:
        return int(base.BSG_DEFAULT_BANK_ID)
    banks = list_available_banks()
    if not banks:
        raise RuntimeError("No BSG bank directories (.env) found")
    return banks[0]


def get_bank_settings(bank_id: Optional[int]) -> BankModel:
    resolved = resolve_bank_id(bank_id)
    env_path = _bank_env_path(resolved)

    env: Dict[str, str] = {}
    if env_path.exists():
        env = {k: v for k, v in dotenv_values(env_path).items() if v is not None}

    # Ensure required id is present even if legacy names were used
    env.setdefault("BSG_BANK_ID", str(resolved))

    try:
        model = BankModel.model_validate(env)
    except Exception as e:
        missing = ", ".join(
            k for k in ("BSG_BANK_ID", "BSG_PASS_KEY", "BSG_DEFAULT_GAME_ID") if k not in env
        )
        raise RuntimeError(f"Invalid bank .env at {env_path}. Missing keys: {missing}. Error: {e}") from e

    return model
