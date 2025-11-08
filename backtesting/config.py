"""Configuration utilities for Backtrader/MetaTrader5 backtests."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional

import MetaTrader5 as mt5

try:  # pragma: no cover - Python < 3.9 fallback
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
except ImportError:  # pragma: no cover
    ZoneInfo = None  # type: ignore

    class ZoneInfoNotFoundError(Exception):
        """Fallback exception when zoneinfo is unavailable."""


MT5_TIMEFRAME_MAP: Dict[str, int] = {
    "M1": mt5.TIMEFRAME_M1,
    "M5": mt5.TIMEFRAME_M5,
    "M15": mt5.TIMEFRAME_M15,
    "M30": mt5.TIMEFRAME_M30,
    "H1": mt5.TIMEFRAME_H1,
    "H4": mt5.TIMEFRAME_H4,
    "D1": mt5.TIMEFRAME_D1,
}


def _resolve_timezone(name: str) -> Optional[ZoneInfo]:
    """Resolve a timezone name into a ``ZoneInfo`` object when available."""

    if not name:
        return None

    if ZoneInfo is None:
        print(
            f"⚠️  zoneinfo module not available; unable to localize timezone '{name}'."
        )
        return None

    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError:
        print(f"⚠️  Unknown timezone '{name}'. Falling back to naive datetimes.")
        return None


def _parse_datetime(candidate: Any, tzinfo: Optional[ZoneInfo]) -> Optional[datetime]:
    """Parse ISO datetime strings or timestamps into datetime objects."""

    if candidate in (None, ""):
        return None

    if isinstance(candidate, (int, float)):
        try:
            return datetime.fromtimestamp(candidate, tz=tzinfo)
        except (OverflowError, OSError, ValueError):
            print(f"⚠️  Invalid timestamp '{candidate}' in backtest history config.")
            return None

    if isinstance(candidate, str):
        try:
            parsed = datetime.fromisoformat(candidate)
        except ValueError:
            print(f"⚠️  Unable to parse datetime string '{candidate}'.")
            return None

        if parsed.tzinfo is None and tzinfo is not None:
            parsed = parsed.replace(tzinfo=tzinfo)

        return parsed

    print(f"⚠️  Unsupported datetime value '{candidate}' ({type(candidate).__name__}).")
    return None


def parse_backtest_config(raw_config: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Normalize backtest configuration and apply sensible defaults."""

    default_timezone_name = "UTC"
    default_timezone = _resolve_timezone(default_timezone_name)

    normalized: Dict[str, Any] = {
        "timeframe_key": "H1",
        "timeframe": MT5_TIMEFRAME_MAP.get("H1", mt5.TIMEFRAME_H1),
        "history": {
            "start": None,
            "start_raw": None,
            "end": None,
            "end_raw": None,
            "timezone_name": default_timezone_name,
            "timezone": default_timezone,
            "align_to_broker_timezone": False,
        },
        "initial_cash": 100000.0,
        "commission": {
            "model": "percentage",
            "rate": 0.0002,
            "per_trade": 0.0,
        },
    }

    if not isinstance(raw_config, dict):
        return normalized

    timeframe_key = str(raw_config.get("timeframe", normalized["timeframe_key"])).upper()
    if timeframe_key not in MT5_TIMEFRAME_MAP:
        print(
            "⚠️  Unsupported backtest timeframe "
            f"'{timeframe_key}'. Defaulting to {normalized['timeframe_key']}."
        )
        timeframe_key = normalized["timeframe_key"]

    normalized["timeframe_key"] = timeframe_key
    normalized["timeframe"] = MT5_TIMEFRAME_MAP.get(timeframe_key, normalized["timeframe"])

    history_raw = raw_config.get("history", {})
    if not isinstance(history_raw, dict):
        history_raw = {}

    timezone_name = str(
        history_raw.get("timezone", normalized["history"]["timezone_name"])
    )
    timezone_obj = _resolve_timezone(timezone_name)

    history = normalized["history"]
    history["timezone_name"] = timezone_name
    history["timezone"] = timezone_obj
    history["align_to_broker_timezone"] = bool(
        history_raw.get(
            "align_to_broker_timezone", history["align_to_broker_timezone"]
        )
    )

    history["start_raw"] = history_raw.get("start")
    history["end_raw"] = history_raw.get("end")
    history["start"] = _parse_datetime(history["start_raw"], timezone_obj)
    history["end"] = _parse_datetime(history["end_raw"], timezone_obj)

    try:
        normalized["initial_cash"] = float(
            raw_config.get("initial_cash", normalized["initial_cash"])
        )
    except (TypeError, ValueError):
        print(
            "⚠️  Invalid initial_cash "
            f"'{raw_config.get('initial_cash')}'. Using default {normalized['initial_cash']}."
        )

    commission_raw = raw_config.get("commission", {})
    commission_cfg = normalized["commission"]
    if isinstance(commission_raw, dict):
        if "model" in commission_raw:
            commission_cfg["model"] = str(commission_raw["model"]).strip().lower()
        if "rate" in commission_raw:
            try:
                commission_cfg["rate"] = float(commission_raw["rate"])
            except (TypeError, ValueError):
                print(
                    "⚠️  Invalid commission rate "
                    f"'{commission_raw.get('rate')}'. Using default {commission_cfg['rate']}."
                )
        if "per_trade" in commission_raw:
            try:
                commission_cfg["per_trade"] = float(commission_raw["per_trade"])
            except (TypeError, ValueError):
                fallback_value = commission_cfg.get("per_trade")
                print(
                    "⚠️  Invalid commission per_trade "
                    f"'{commission_raw.get('per_trade')}'. Using default {fallback_value}."
                )

    return normalized


def format_history_bound(history_section: Dict[str, Any], bound: str) -> str:
    """Return a human-friendly representation of a history boundary."""

    dt_obj = history_section.get(bound)
    if dt_obj is not None:
        return dt_obj.isoformat()

    raw_value = history_section.get(f"{bound}_raw")
    return raw_value if raw_value not in (None, "") else "not set"


__all__ = [
    "MT5_TIMEFRAME_MAP",
    "format_history_bound",
    "parse_backtest_config",
]
