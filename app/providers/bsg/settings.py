# igw/app/providers/bsg/settings.py
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Dict

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


# Base BSG settings (provider-wide, not per-bank)
_BSG_BASE_ENV = Path(__file__).resolve().parent / ".env"


class BSGBaseSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(_BSG_BASE_ENV),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Default/fallbacks
    BSG_DEFAULT_BANK_ID: str | None = None
    BSG_DEFAULT_CURRENCY: str = "USD"

    # Optional: where to build a StartGame link if you want a default host here
    BSG_CW_START_BASE_DEFAULT: str | None = None  # e.g. https://5for5media-ng-copy.nucleusgaming.com

    # You can add other shared knobs here later (timeouts, etc.)


# Per-bank settings (lives in providers/bsg/<bankId>/.env)
def _bank_env_path(bank_id: str) -> Path:
    return Path(__file__).resolve().parent / bank_id / ".env"


class BankSettings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    # Bank identity
    BSG_BANK_ID: str
    # The operator pass key used for MD5 signing/validation with BSG
    BSG_PASS_KEY: str

    # Per-bank defaults (override global)
    BSG_DEFAULT_CURRENCY: str | None = None

    # ⬇️ NEW: per-bank default game to launch (moved from app config)
    BSG_DEFAULT_GAME_ID: int

    # Optional: per-bank host for building a CW start URL (overrides global)
    BSG_CW_START_BASE: str | None = None  # e.g. https://5for5media-ng-copy.nucleusgaming.com


@lru_cache
def bsg_settings() -> BSGBaseSettings:
    s = BSGBaseSettings()
    print(f"[BSG] Loaded base settings (.env={'found' if _BSG_BASE_ENV.exists() else 'missing'}) from: {_BSG_BASE_ENV}")
    return s


# Cache each bank’s settings
_BANK_CACHE: Dict[str, BankSettings] = {}


def get_bank_settings(bank_id: str) -> BankSettings:
    bank_id = str(bank_id)
    if bank_id in _BANK_CACHE:
        return _BANK_CACHE[bank_id]
    env_path = _bank_env_path(bank_id)
    if not env_path.exists():
        raise FileNotFoundError(f"[BSG] Missing bank env: {env_path}")
    # dynamically create a model bound to a specific env file
    model_conf = SettingsConfigDict(env_file=str(env_path), env_file_encoding="utf-8", extra="ignore")
    class _BoundBankSettings(BankSettings):
        model_config = model_conf
    s = _BoundBankSettings()  # type: ignore
    _BANK_CACHE[bank_id] = s
    print(f"[BSG] Loaded bank settings (.env=found) from: {env_path}")
    return s


def list_available_banks() -> list[str]:
    base = Path(__file__).resolve().parent
    banks = []
    for p in base.iterdir():
        if p.is_dir() and (p / ".env").exists():
            banks.append(p.name)
    return sorted(banks)
