"""Load config.yaml into a plain dict with a couple of typed helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .fees import FeeModel, kalshi_fee_model

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = ROOT / "config.yaml"


def load_config(path: str | Path | None = None) -> dict[str, Any]:
    with open(path or DEFAULT_CONFIG) as f:
        return yaml.safe_load(f)


def kalshi_fees(cfg: dict[str, Any], fee_type: str = "quadratic", fee_multiplier: float | None = None) -> FeeModel:
    k = cfg["fees"]["kalshi"]
    return kalshi_fee_model(
        fee_type,
        k["default_multiplier"] if fee_multiplier is None else fee_multiplier,
        taker_rate=k["taker_rate"],
        maker_rate=k["maker_rate"],
        rounding_increment=k["rounding_increment"],
    )
