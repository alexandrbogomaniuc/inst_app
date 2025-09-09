# igw/app/providers/bsg/settings.py
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import List, Optional

from fastapi import HTTPException
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Folder layout:
# igw/app/providers/bsg/.env                -> base settings
# igw/app/providers/bsg/<bankId>/.env       -> per-bank settings (e.g., 6111/.env)

_BASE_DIR = Path(__file__).resolve().parent


class BSGBaseSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(_BASE_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Global defaults (can be omitted in base .env)
    BSG_DEFAULT_BANK_ID: Optional[int] = None
    BSG_CW_START_BASE_DEFAULT: Optional[str] = None
    BSG_TOKEN_GAME_EXP_MIN: int = 60  # minutes


class BankModel(BaseSettings):
    """
    Per-bank settings. We map BANK_ID from env key BSG_BANK_ID to match your .env.
    Example igw/app/providers/bsg/6111/.env:
      BSG_BANK_ID=6111
      BSG_PROTOCOL=xml
      BSG_PASS_KEY=OkykCptT7qPBT8sN
      BSG_DEFAULT_GAME_ID=30217
      BSG_DEFAULT_CURRENCY=USD
      BSG_CW_START_BASE=https://5for5media-ng-copy.nucleusgaming.com
    """
    model_config = SettingsConfigDict(
        env_file=None,                # we fill in per call
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # NB: your env uses BSG_BANK_ID, we alias it to BANK_ID
    BANK_ID: int = Field(..., alias="BSG_BANK_ID")

    BSG_PROTOCOL: str = "xml"  # "xml" or "json"
    BSG_PASS_KEY: str

    BSG_DEFAULT_GAME_ID: int
    BSG_DEFAULT_CURRENCY: str = "USD"

    # Optional: override the CW start host for this bank
    BSG_CW_START_BASE: Optional[str] = None


def _bank_dir(bank_id: int) -> Path:
    return _BASE_DIR / str(bank_id)


def _bank_env_path(bank_id: int) -> Path:
    return _bank_dir(bank_id) / ".env"


@lru_cache
def bsg_settings() -> BSGBaseSettings:
    s = BSGBaseSettings()
    env_path = Path(BSGBaseSettings.model_config["env_file"])  # type: ignore[index]
    print(f"[BSG] Loaded base settings (.env={'found' if env_path.exists() else 'missing'}) from: {env_path}")
    return s


def list_available_banks() -> List[int]:
    ids: List[int] = []
    for child in _BASE_DIR.iterdir():
        if not child.is_dir():
            continue
        if not child.name.isdigit():
            continue
        if (_BASE_DIR / child.name / ".env").exists():
            ids.append(int(child.name))
    return sorted(ids)


@lru_cache
def get_bank_settings(bank_id: int) -> BankModel:
    env_file = _bank_env_path(bank_id)
    if not env_file.exists():
        raise HTTPException(status_code=500, detail=f"Bank env not found for {bank_id}: {env_file}")
    m = BankModel.model_validate({}, context=None)  # create instance with defaults
    # rebuild with proper env_file through model_copy(update=...)
    m.model_config = SettingsConfigDict(
        env_file=str(env_file),
        env_file_encoding="utf-8",
        extra="ignore",
    )
    # Reconstruct with the env file applied
    m = BankModel()  # pydantic-settings reads env_file from model_config
    # Force a load by reassigning model_config to ensure env_file is used
    m.model_config = SettingsConfigDict(
        env_file=str(env_file),
        env_file_encoding="utf-8",
        extra="ignore",
    )
    # Finally instantiate again to pick env values
    m = BankModel()
    print(f"[BSG] Loaded bank settings (.env={'found' if env_file.exists() else 'missing'}) from: {env_file}")
    return m


def resolve_bank_id(incoming_bank_id: Optional[int]) -> int:
    """
    Decide which bank id to use:
      1) use incoming if provided and exists,
      2) else use base default if set and exists,
      3) else fall back to the first available configured bank,
      4) else 500.
    """
    available = set(list_available_banks())

    if incoming_bank_id and incoming_bank_id in available:
        return incoming_bank_id

    base = bsg_settings()
    if base.BSG_DEFAULT_BANK_ID and base.BSG_DEFAULT_BANK_ID in available:
        return int(base.BSG_DEFAULT_BANK_ID)

    if available:
        return sorted(available)[0]

    raise HTTPException(status_code=500, detail="No BSG banks configured")
