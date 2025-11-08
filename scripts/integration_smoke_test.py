"""
Integration smoke test for key components introduced in the fork.

This script avoids live MetaTrader5 calls by injecting a dummy MT5 module
that returns predictable daily OHLC bars. It then exercises the
`market_data.build_daily_snapshots` API and writes a small pickle output.

Usage:
  python scripts/integration_smoke_test.py

Options:
  --start YYYY-MM-DD   Start date (default: 2024-01-01)
  --days N             Number of days (default: 5)
  --symbol SYMBOL      Market symbol (default: EURUSD)
  --keep-data          Keep generated files under data/ (default: cleanup)
"""

from __future__ import annotations

import argparse
import pickle
import shutil
from dataclasses import dataclass
from datetime import date, datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, List


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Integration smoke test")
    p.add_argument("--start", default="2024-01-01", help="Start date (YYYY-MM-DD)")
    p.add_argument("--days", default="5", help="Number of days to generate")
    p.add_argument("--symbol", default="EURUSD", help="Symbol to test")
    p.add_argument("--keep-data", action="store_true", help="Keep generated data files")
    return p.parse_args()


def _to_dt_utc(d: date) -> datetime:
    return datetime(d.year, d.month, d.day, tzinfo=timezone.utc)


def _daterange(start: date, days: int) -> List[date]:
    return [start + timedelta(days=i) for i in range(days)]


def _write_sample_news(data_dir: Path, dates: List[date], symbol: str) -> List[Path]:
    news_dir = data_dir / "news"
    news_dir.mkdir(parents=True, exist_ok=True)
    written: List[Path] = []
    for d in dates:
        payload = {
            "date": d.isoformat(),
            "symbol": symbol,
            "headlines": [
                {"title": f"Headline for {symbol} on {d.isoformat()}", "sentiment": "neutral"}
            ],
        }
        p = news_dir / f"{d.isoformat()}.json"
        p.write_text(__import__("json").dumps(payload, indent=2), encoding="utf-8")
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
        def copy_rates_from_pos(symbol: str, timeframe: int, start_pos: int, count: int):
            if count <= 0:
                return []
            # Generate `count` daily bars ending today (UTC), ascending by time
            end = datetime.utcnow().date()
            start = end - timedelta(days=count - 1)
            return _DummyMt5._gen_bars(start, count)

        @staticmethod
        def copy_rates_range(symbol: str, timeframe: int, start_dt: datetime, end_dt: datetime):
            # Generate bars aligned to requested UTC date window [start_dt, end_dt)
            start_date = start_dt.date()
            end_date = (end_dt - timedelta(seconds=1)).date()
            if start_date > end_date:
                return []
            days = (end_date - start_date).days + 1
            return _DummyMt5._gen_bars(start_date, days)

        @staticmethod
        def _gen_bars(start_date: date, days: int):
            items = []
            for i, d in enumerate(_daterange(start_date, days)):
                ts = int(_to_dt_utc(d).timestamp())
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

    # Inject the dummy object as the mt5 module used by snapshot_builder
    snapshot_builder_module.mt5 = _DummyMt5()


def main() -> None:
    args = _parse_args()
    start = datetime.strptime(args.start, "%Y-%m-%d").date()
    days = int(args.days)
    symbol = args.symbol

    # Resolve repo and data paths (market_data/../data)
    repo_root = Path(__file__).resolve().parents[1]
    data_dir = repo_root / "data"
    data_dir.mkdir(exist_ok=True)

    # Prepare small local dataset (news + filings)
    dates = _daterange(start, days)
    news_files = _write_sample_news(data_dir, dates, symbol)
    filings_csv = _write_sample_filings_csv(data_dir, dates, symbol)

    # Import and patch snapshot builder
    from market_data import snapshot_builder
    from market_data import build_daily_snapshots

    _inject_dummy_mt5(snapshot_builder)

    start_dt = _to_dt_utc(dates[0])
    end_dt = _to_dt_utc(dates[-1])

    snapshots: Dict[date, Dict] = build_daily_snapshots(symbol, start_dt, end_dt)
    count = len(snapshots)

    # Basic validations
    assert count == days, f"Expected {days} snapshots, got {count}"
    any_day = dates[len(dates) // 2]
    assert any_day in snapshots, "Mid-range date missing in snapshots"
    assert "price" in snapshots[any_day], "Snapshot missing price key"

    # Persist a small pickle for a quick smoke artifact
    out_path = data_dir / "env_data_test.pkl"
    with out_path.open("wb") as handle:
        pickle.dump(snapshots, handle)

    print("Integration smoke test SUCCESS")
    print(f" Symbol: {symbol}")
    print(f" Range:  {dates[0]} .. {dates[-1]}  (days={days})")
    print(f" Output: {out_path}")

    if not args.keep_data:
        # Clean up files we created; leave the data directory in place if pre-existing
        try:
            for p in news_files:
                p.unlink(missing_ok=True)
            filings_csv.unlink(missing_ok=True)
            out_path.unlink(missing_ok=True)
            news_dir = data_dir / "news"
            if news_dir.exists() and not any(news_dir.iterdir()):
                news_dir.rmdir()
            # Only remove data/ if empty and we created it solely for this run
            if not any(data_dir.iterdir()):
                data_dir.rmdir()
        except Exception as e:
            print(f"Warning: cleanup skipped due to: {e}")


if __name__ == "__main__":
    main()
