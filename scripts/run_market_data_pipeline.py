"""
Run the full market data workflow end-to-end.

Steps:
  1) (Optional) Initialize MetaTrader5 and select the symbol
  2) Build daily snapshots via market_data.build_daily_snapshots
  3) Persist outputs to pickle and JSON
  4) (Optional) Iterate snapshots with MarketEnvironment and emit a CSV summary

Usage (preferred from repo root):
  python -m scripts.run_market_data_pipeline \
    --symbol EURUSD --start 2024-02-01 --end 2024-02-07 \
    --out-pkl data/env_data.pkl --out-json data/env_data.json --out-csv data/env_data_summary.csv

Flags:
  --dry-run       Use a dummy MetaTrader5 provider (no live terminal needed)
  --no-iterate    Skip MarketEnvironment iteration
"""

from __future__ import annotations

import argparse
import csv
import json
import pickle
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional


# Allow running directly via `python scripts/run_market_data_pipeline.py`
if __name__ == "__main__" and __package__ is None:
    import sys as _sys
    _sys.path.append(str(Path(__file__).resolve().parents[1]))


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Run market data pipeline (build + iterate)")
    p.add_argument("--symbol", required=True, help="Trading symbol (e.g. EURUSD)")
    p.add_argument("--start", required=True, help="Start date (YYYY-MM-DD)")
    p.add_argument("--end", required=True, help="End date (YYYY-MM-DD)")
    p.add_argument("--out-pkl", default="data/env_data.pkl", help="Output pickle path")
    p.add_argument("--out-json", default="data/env_data.json", help="Output JSON path")
    p.add_argument("--out-csv", default="data/env_data_summary.csv", help="Summary CSV path")
    p.add_argument("--dry-run", action="store_true", help="Use dummy MT5 (no live terminal)")
    p.add_argument("--no-iterate", action="store_true", help="Skip MarketEnvironment iteration")
    return p.parse_args()


def _ensure_dt_utc(d: date) -> datetime:
    return datetime(d.year, d.month, d.day, tzinfo=timezone.utc)


def _inject_dummy_mt5(snapshot_builder_module) -> None:
    from datetime import timedelta

    class _DummyMt5:
        TIMEFRAME_D1 = 1440

        @staticmethod
        def copy_rates_range(symbol: str, timeframe: int, start_dt: datetime, end_dt: datetime):
            start_date = start_dt.date()
            end_date = (end_dt - timedelta(seconds=1)).date()
            if start_date > end_date:
                return []
            return _DummyMt5._gen_bars(start_date, (end_date - start_date).days + 1)

        @staticmethod
        def copy_rates_from_pos(symbol: str, timeframe: int, start_pos: int, count: int):
            if count <= 0:
                return []
            end = datetime.utcnow().date()
            start = end - timedelta(days=count - 1)
            return _DummyMt5._gen_bars(start, count)

        @staticmethod
        def _gen_bars(start_date: date, days: int):
            from datetime import timedelta as _td

            items = []
            for i in range(days):
                d = start_date + _td(days=i)
                ts = int(_ensure_dt_utc(d).timestamp())
                base = 1.1000 + i * 0.0005
                items.append(
                    {
                        "time": ts,
                        "open": round(base, 5),
                        "high": round(base + 0.0010, 5),
                        "low": round(base - 0.0010, 5),
                        "close": round(base + 0.0003, 5),
                        "tick_volume": 100 + i,
                        "spread": 2,
                        "real_volume": 1000 + i,
                    }
                )
            return items

    snapshot_builder_module.mt5 = _DummyMt5()


def _serialize_dates(obj: Dict[Any, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for k, v in obj.items():
        ks = k.isoformat() if hasattr(k, "isoformat") else str(k)
        out[ks] = v
    return out


def main() -> None:
    args = _parse_args()
    start_d = date.fromisoformat(args.start)
    end_d = date.fromisoformat(args.end)
    if start_d > end_d:
        raise SystemExit("Start date must not be after end date")

    from market_data import build_daily_snapshots
    from market_data import snapshot_builder

    snapshots: Dict[date, Dict[str, Any]]

    if args.dry_run:
        _inject_dummy_mt5(snapshot_builder)
        snapshots = build_daily_snapshots(args.symbol, _ensure_dt_utc(start_d), _ensure_dt_utc(end_d))
    else:
        # Live MT5 path
        import MetaTrader5 as mt5

        if not mt5.initialize():
            raise SystemExit(f"Failed to initialize MetaTrader5: {mt5.last_error()}")
        try:
            if not mt5.symbol_select(args.symbol, True):
                raise SystemExit(f"Failed to select symbol: {args.symbol}")
            snapshots = build_daily_snapshots(args.symbol, _ensure_dt_utc(start_d), _ensure_dt_utc(end_d))
        finally:
            try:
                mt5.shutdown()
            except Exception:
                pass

    # Persist outputs
    out_pkl = Path(args.out_pkl)
    out_pkl.parent.mkdir(parents=True, exist_ok=True)
    with out_pkl.open("wb") as fh:
        pickle.dump(snapshots, fh)

    out_json = Path(args.out_json)
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(_serialize_dates(snapshots), indent=2), encoding="utf-8")

    # Optional: iterate and write summary CSV
    if not args.no_iterate:
        try:
            from market_data.environment import MarketEnvironment  # type: ignore

            env = MarketEnvironment(snapshots=snapshots)
            env.reset()
            rows = [("date", "close", "future_return")]
            while True:
                d, snap, done = env.step()
                if done and (d is None or snap is None):
                    break
                close = None
                fr = None
                if snap is not None:
                    price = snap.get("price") or {}
                    close = price.get("close")
                    fr = snap.get("future_return")
                rows.append((d.isoformat() if d else "", close, fr))

            out_csv = Path(args.out_csv)
            out_csv.parent.mkdir(parents=True, exist_ok=True)
            with out_csv.open("w", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                w.writerows(rows)
        except Exception:
            # MarketEnvironment may not exist on this branch; skip silently
            pass

    print("Market data pipeline COMPLETE")
    print(f" Symbol: {args.symbol}")
    print(f" Range:  {start_d} .. {end_d}")
    print(f" Pickle: {out_pkl}")
    print(f" JSON:   {out_json}")
    if not args.no_iterate:
        print(f" Summary CSV: {args.out_csv}")


if __name__ == "__main__":
    main()
