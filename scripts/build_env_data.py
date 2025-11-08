"""CLI helper for building environment snapshot data.

This script supports two execution modes:
  1) Recommended: from repo root as a module
       python -m scripts.build_env_data --symbol EURUSD --start 2024-01-01 --end 2024-01-31
  2) Direct: python scripts/build_env_data.py ...
     In direct mode we add the repository root to sys.path so the
     top-level package imports (e.g., ``market_data``) resolve cleanly.
"""

from __future__ import annotations

import argparse
import json
import pickle
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Optional

# Allow running directly via `python scripts/build_env_data.py` by ensuring
# the repository root is on sys.path. Using `python -m scripts.build_env_data`
# from the repo root is still preferred.
if __name__ == "__main__" and __package__ is None:
    import sys
    sys.path.append(str(Path(__file__).resolve().parents[1]))

from market_data import build_daily_snapshots

DEFAULT_CONFIG_PATH = Path("config/settings.json")
DEFAULT_OUTPUT_PATH = Path("data/env_data.pkl")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build environment data snapshots")
    parser.add_argument("--symbol", help="Trading symbol (e.g. EURUSD)")
    parser.add_argument("--start", help="Start date (YYYY-MM-DD or ISO format)")
    parser.add_argument("--end", help="End date (YYYY-MM-DD or ISO format)")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH), help="Path to JSON config")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT_PATH), help="Output pickle path")
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    config = _load_config(Path(args.config))

    symbol = _resolve_symbol(args.symbol, config)
    if not symbol:
        raise SystemExit("A trading symbol must be supplied via --symbol or config")

    start_dt, end_dt = _resolve_date_range(args.start, args.end, config)

    # Initialize MetaTrader5 to ensure data retrieval works
    import MetaTrader5 as mt5
    if not mt5.initialize():
        raise SystemExit(f"Failed to initialize MetaTrader5: {mt5.last_error()}")
    try:
        snapshots = build_daily_snapshots(symbol, start_dt, end_dt)
    finally:
        try:
            mt5.shutdown()
        except Exception:
            pass

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("wb") as handle:
        pickle.dump(snapshots, handle)

    print(f"Saved {len(snapshots)} snapshots to {output_path}")


def _load_config(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as handle:
        try:
            return json.load(handle)
        except json.JSONDecodeError as exc:
            raise SystemExit(f"Failed to parse config: {exc}")


def _resolve_symbol(cli_symbol: Optional[str], config: Dict[str, Any]) -> Optional[str]:
    if cli_symbol:
        return cli_symbol
    return config.get("symbol")


def _resolve_date_range(
    cli_start: Optional[str], cli_end: Optional[str], config: Dict[str, Any]
) -> tuple[datetime, datetime]:
    env_config = config.get("environment_data", {}) if isinstance(config, dict) else {}
    start_value = cli_start or env_config.get("start_date")
    end_value = cli_end or env_config.get("end_date")

    end_dt = _parse_datetime(end_value) if end_value else _default_end()
    start_dt = _parse_datetime(start_value) if start_value else end_dt - timedelta(days=30)

    if start_dt > end_dt:
        raise SystemExit("Start date must not be after end date")

    return start_dt, end_dt


def _parse_datetime(value: str) -> datetime:
    dt = _ensure_datetime(value)
    if dt is None:
        raise SystemExit(f"Unable to parse datetime value: {value}")
    return dt


def _default_end() -> datetime:
    now = datetime.utcnow()
    return datetime(now.year, now.month, now.day)


def _ensure_datetime(value: Optional[Any]) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(value, tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    if isinstance(value, str):
        value = value.strip()
        if not value:
            return None
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%d-%m-%Y", "%Y-%m-%d %H:%M:%S", "%Y%m%d"):
                try:
                    return datetime.strptime(value, fmt)
                except ValueError:
                    continue
    return None


if __name__ == "__main__":
    main()

