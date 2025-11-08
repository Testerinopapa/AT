"""Helpers for building daily market data snapshots."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, Iterable, Optional, Tuple
import csv
import json
import sqlite3

import MetaTrader5 as mt5


DATA_DIR = Path(__file__).resolve().parent.parent / "data"


@dataclass
class PriceBar:
    """Container for OHLC price data."""

    time: datetime
    open: float
    high: float
    low: float
    close: float
    tick_volume: Optional[int] = None
    spread: Optional[int] = None
    real_volume: Optional[int] = None

    def to_dict(self) -> Dict[str, float]:
        return {
            "time": self.time.isoformat(),
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "adjusted_close": self.close,
            "tick_volume": self.tick_volume,
            "spread": self.spread,
            "real_volume": self.real_volume,
        }


def build_daily_snapshots(symbol: str, start: datetime, end: datetime) -> Dict[date, Dict]:
    """Build market environment snapshots for the given date range.

    The builder fetches adjusted prices from MetaTrader5 (mirroring the
    behaviour of :meth:`strategies.base_strategy.BaseStrategy.get_market_data`)
    and enriches each daily entry with previously ingested news and SEC filing
    data stored under :mod:`data`.

    Args:
        symbol: The market symbol (e.g. "EURUSD").
        start: Inclusive start datetime for the snapshot window.
        end: Inclusive end datetime for the snapshot window.

    Returns:
        Mapping of ``date`` to the combined snapshot payload.
    """

    if start is None or end is None:
        raise ValueError("start and end must be provided")

    start_date = _coerce_to_date(start)
    end_date = _coerce_to_date(end)

    if start_date > end_date:
        raise ValueError("start must not be after end")

    price_data = _load_price_data(symbol, start_date, end_date)
    news_data = _load_news_data(symbol, start_date, end_date)
    filing_q_data, filing_k_data = _load_filing_data(symbol, start_date, end_date)

    snapshots: Dict[date, Dict] = {}
    current = start_date
    while current <= end_date:
        snapshots[current] = {
            "price": price_data.get(current),
            "news": news_data.get(current, {}),
            "filing_q": filing_q_data.get(current),
            "filing_k": filing_k_data.get(current),
        }
        current += timedelta(days=1)

    return snapshots


def _coerce_to_date(value: datetime | date) -> date:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        if value.tzinfo is not None:
            value = value.astimezone(timezone.utc)
        return value.date()
    raise TypeError(f"Unsupported date value: {value!r}")


def _load_price_data(symbol: str, start: date, end: date) -> Dict[date, Dict]:
    """Fetch OHLC bars from MetaTrader5 and bucket them by calendar date.

    Attempts to fetch an exact date range; falls back to recent-count fetch.
    """

    if start > end:
        return {}

    price_by_date: Dict[date, Dict] = {}

    # Preferred: exact date range (inclusive of end day)
    start_dt = datetime(start.year, start.month, start.day, tzinfo=timezone.utc)
    end_dt_exclusive = datetime(end.year, end.month, end.day, tzinfo=timezone.utc) + timedelta(days=1)

    rates = None
    try:
        rates = mt5.copy_rates_range(symbol, mt5.TIMEFRAME_D1, start_dt, end_dt_exclusive)
    except Exception:
        rates = None

    # Fallback: fetch recent N days and filter
    if rates is None:
        day_count = (end - start).days + 1
        if day_count <= 0:
            return {}
        try:
            rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_D1, 0, day_count)
        except Exception:
            rates = None

    # rates may be a list/tuple or a numpy array; avoid truthiness on arrays
    if rates is None:
        return price_by_date
    try:
        if len(rates) == 0:
            return price_by_date
    except TypeError:
        # If object has no len(), fall back to empty mapping
        return price_by_date

    for rate in rates:
        bar_time = _extract_rate_value(rate, "time")
        if bar_time is None:
            continue
        bar_dt = datetime.fromtimestamp(int(bar_time), tz=timezone.utc)
        bar_date = bar_dt.date()
        if not (start <= bar_date <= end):
            continue

        bar = PriceBar(
            time=bar_dt,
            open=float(_extract_rate_value(rate, "open") or 0.0),
            high=float(_extract_rate_value(rate, "high") or 0.0),
            low=float(_extract_rate_value(rate, "low") or 0.0),
            close=float(_extract_rate_value(rate, "close") or 0.0),
            tick_volume=_to_optional_int(_extract_rate_value(rate, "tick_volume")),
            spread=_to_optional_int(_extract_rate_value(rate, "spread")),
            real_volume=_to_optional_int(_extract_rate_value(rate, "real_volume")),
        )
        price_by_date[bar_date] = bar.to_dict()

    return price_by_date


def _load_news_data(symbol: str, start: date, end: date) -> Dict[date, Dict]:
    """Load previously captured news events from CSV/JSON storage."""

    news_by_date: Dict[date, Dict] = {}

    csv_path = DATA_DIR / "news.csv"
    if csv_path.exists():
        with csv_path.open("r", encoding="utf-8") as csvfile:
            reader = csv.DictReader(csvfile)
            for row in reader:
                row_date = _extract_date_from_row(row, ("date", "published_at", "timestamp"))
                if row_date is None or not (start <= row_date <= end):
                    continue
                if symbol and row.get("symbol") and row["symbol"].upper() != symbol.upper():
                    continue
                payload = {k: _safe_json_loads(v) for k, v in row.items() if k is not None}
                news_by_date.setdefault(row_date, {"items": []})["items"].append(payload)

    json_path = DATA_DIR / "news.json"
    if json_path.exists():
        with json_path.open("r", encoding="utf-8") as jsonfile:
            data = json.load(jsonfile)
            entries = data if isinstance(data, list) else data.get("items", []) if isinstance(data, dict) else []
            for entry in entries:
                parsed_dt = _ensure_datetime(entry.get("date") or entry.get("published_at"))
                if parsed_dt is None:
                    continue
                row_date = _coerce_to_date(parsed_dt)
                if not (start <= row_date <= end):
                    continue
                if symbol and entry.get("symbol") and entry["symbol"].upper() != symbol.upper():
                    continue
                news_by_date.setdefault(row_date, {"items": []})["items"].append(entry)

    return news_by_date


def _load_filing_data(symbol: str, start: date, end: date) -> Tuple[Dict[date, Dict], Dict[date, Dict]]:
    """Load SEC filing data from CSV or SQLite sources."""

    filing_q: Dict[date, Dict] = {}
    filing_k: Dict[date, Dict] = {}

    csv_path = DATA_DIR / "filings.csv"
    if csv_path.exists():
        with csv_path.open("r", encoding="utf-8") as csvfile:
            reader = csv.DictReader(csvfile)
            for row in reader:
                row_date = _extract_date_from_row(row, ("filed_date", "date", "period"))
                if row_date is None or not (start <= row_date <= end):
                    continue
                if symbol and row.get("symbol") and row["symbol"].upper() != symbol.upper():
                    continue
                filing_type = (row.get("filing_type") or row.get("type") or "").upper()
                payload = {k: _safe_json_loads(v) for k, v in row.items()}
                _store_filing(row_date, filing_type, payload, filing_q, filing_k)

    sqlite_path = DATA_DIR / "filings.sqlite"
    if sqlite_path.exists():
        conn = sqlite3.connect(sqlite_path)
        conn.row_factory = sqlite3.Row
        try:
            cursor = conn.execute(
                "SELECT * FROM filings WHERE date(filed_date) BETWEEN ? AND ?",
                (start.isoformat(), end.isoformat()),
            )
            for row in cursor.fetchall():
                row_dict = dict(row)
                row_date = _extract_date_from_row(row_dict, ("filed_date", "date", "period"))
                if row_date is None or not (start <= row_date <= end):
                    continue
                if symbol and row_dict.get("symbol") and row_dict["symbol"].upper() != symbol.upper():
                    continue
                filing_type = (row_dict.get("filing_type") or row_dict.get("type") or "").upper()
                payload = {k: _safe_json_loads(v) for k, v in row_dict.items()}
                _store_filing(row_date, filing_type, payload, filing_q, filing_k)
        finally:
            conn.close()

    return filing_q, filing_k


def _store_filing(
    row_date: date,
    filing_type: str,
    payload: Dict,
    filing_q: Dict[date, Dict],
    filing_k: Dict[date, Dict],
) -> None:
    if "10-Q" in filing_type or filing_type.endswith("Q"):
        filing_q.setdefault(row_date, {"items": []})["items"].append(payload)
    elif "10-K" in filing_type or filing_type.endswith("K"):
        filing_k.setdefault(row_date, {"items": []})["items"].append(payload)


def _extract_date_from_row(row: Dict, keys: Iterable[str]) -> Optional[date]:
    for key in keys:
        if key in row and row[key]:
            parsed = _ensure_datetime(row[key])
            if parsed is None:
                continue
            return _coerce_to_date(parsed)
    return None


def _ensure_datetime(value: Optional[object]) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day)
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


def _safe_json_loads(value: object) -> object:
    if not isinstance(value, str):
        return value
    text = value.strip()
    if not text:
        return value
    if text.startswith("{") or text.startswith("["):
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return value
    return value


def _extract_rate_value(rate: object, key: str) -> Optional[object]:
    try:
        return rate[key]  # type: ignore[index]
    except (KeyError, TypeError, IndexError, ValueError):
        return getattr(rate, key, None)


def _to_optional_int(value: Optional[object]) -> Optional[int]:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None

