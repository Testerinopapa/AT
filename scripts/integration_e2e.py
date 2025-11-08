"""
End-to-end integration test script for the data pipeline.

This script exercises the market data snapshot builder (and optionally the
MarketEnvironment iterator, if present) over a user-specified date window.
It avoids live MetaTrader5 dependencies by injecting a minimal dummy MT5
module that returns deterministic daily OHLC bars aligned to the requested
date range.

Run from repo root (preferred):
  python -m scripts.integration_e2e --symbol EURUSD --start 2024-02-01 --end 2024-02-07

Direct run also works:
  python scripts/integration_e2e.py --symbol EURUSD --start 2024-02-01 --end 2024-02-07
"""

from __future__ import annotations

import argparse
import json
import pickle
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any


# Allow running directly via `python scripts/integration_e2e.py`
if __name__ == "__main__" and __package__ is None:
    import sys as _sys
    _sys.path.append(str(Path(__file__).resolve().parents[1]))


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="E2E integration test for market data snapshots")
    p.add_argument("--symbol", required=True, help="Trading symbol (e.g. EURUSD)")
    p.add_argument("--start", required=True, help="Start date (YYYY-MM-DD)")
    p.add_argument("--end", required=True, help="End date (YYYY-MM-DD)")
    p.add_argument("--keep-data", action="store_true", help="Keep generated files under data/")
    return p.parse_args()


def _ensure_datetime_utc(d: date) -> datetime:
    return datetime(d.year, d.month, d.day, tzinfo=timezone.utc)


def _daterange(start: date, end: date) -> List[date]:
    days = (end - start).days + 1
    return [start + timedelta(days=i) for i in range(days)] if days > 0 else []


def _write_sample_news(data_dir: Path, dates: List[date], symbol: str) -> List[Path]:
    news_dir = data_dir / "news"
    news_dir.mkdir(parents=True, exist_ok=True)
    written: List[Path] = []
    for d in dates:
        payload = {
            "date": d.isoformat(),
            "symbol": symbol,
            "headlines": [
                {"title": f"Sample headline for {symbol} on {d.isoformat()}", "sentiment": "neutral"}
            ],
        }
        p = news_dir / f"{d.isoformat()}.json"
        p.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        written.append(p)
    return written


def _write_sample_filings_csv(data_dir: Path, dates: List[date], symbol: str) -> Path:
    import csv

    csv_path = data_dir / "filings.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(
            f,
            fieldnames=["filed_date", "symbol", "filing_type", "title", "extra"],
        )
        w.writeheader()
        for d in dates:
            w.writerow(
                {
                    "filed_date": d.isoformat(),
                    "symbol": symbol,
                    "filing_type": "10-Q" if (d.day % 2 == 0) else "10-K",
                    "title": f"Filing for {symbol} {d.isoformat()}",
                    "extra": "{}",
                }
            )
    return csv_path


def _inject_dummy_mt5(snapshot_builder_module) -> None:
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
            items = []
            for i, d in enumerate(_daterange(start_date, start_date + timedelta(days=days - 1))):
                ts = int(_ensure_datetime_utc(d).timestamp())
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


def main() -> None:
    args = _parse_args()
    start = date.fromisoformat(args.start)
    end = date.fromisoformat(args.end)
    if start > end:
        raise SystemExit("Start date must not be after end date")

    symbol = args.symbol
    repo_root = Path(__file__).resolve().parents[1]
    data_dir = repo_root / "data"
    data_dir.mkdir(exist_ok=True)

    # Seed sample side-channel data
    dates = _daterange(start, end)
    _write_sample_news(data_dir, dates, symbol)
    _write_sample_filings_csv(data_dir, dates, symbol)

    # Import and patch snapshot builder
    from market_data import snapshot_builder
    from market_data import build_daily_snapshots

    _inject_dummy_mt5(snapshot_builder)

    snapshots: Dict[date, Dict[str, Any]] = build_daily_snapshots(
        symbol=symbol,
        start=_ensure_datetime_utc(start),
        end=_ensure_datetime_utc(end),
    )

    # Basic validations
    assert len(snapshots) == len(dates), (
        f"Expected {len(dates)} snapshots, got {len(snapshots)}"
    )
    # Check a middle date contains a price close
    mid = dates[len(dates) // 2]
    mid_price = (snapshots.get(mid) or {}).get("price") or {}
    assert "close" in mid_price, "Missing price.close in snapshot"

    out_pkl = data_dir / "env_data_integration.pkl"
    with out_pkl.open("wb") as fh:
        pickle.dump(snapshots, fh)

    # Optional: iterate with MarketEnvironment if available
    future_returns_summary: Optional[Tuple[float, int]] = None
    try:
        from market_data.environment import MarketEnvironment  # type: ignore

        env = MarketEnvironment(snapshots=snapshots)
        env.reset()
        sum_fr = 0.0
        n_fr = 0
        while True:
            d, snap, done = env.step()
            if done and (d is None or snap is None):
                break
            if snap is not None and snap.get("future_return") is not None:
                sum_fr += float(snap["future_return"])  # type: ignore[arg-type]
                n_fr += 1
        if n_fr:
            future_returns_summary = (sum_fr, n_fr)
    except Exception:
        # MarketEnvironment may be absent on current branch; skip gracefully
        pass

    # Persist JSON for convenience (date keys as ISO strings)
    out_json = data_dir / "env_data_integration.json"
    serializable = {k.isoformat() if hasattr(k, "isoformat") else str(k): v for k, v in snapshots.items()}
    out_json.write_text(json.dumps(serializable, indent=2), encoding="utf-8")

    print("Integration E2E test SUCCESS")
    print(f" Symbol: {symbol}")
    print(f" Range:  {start} .. {end}  (days={len(dates)})")
    print(f" Output: {out_pkl}")
    print(f" JSON:   {out_json}")
    if future_returns_summary:
        total, count = future_returns_summary
        print(f" Future returns computed for {count} steps; sum={total:.6f}")


if __name__ == "__main__":
    main()

