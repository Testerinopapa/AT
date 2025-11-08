"""Market data environment for iterating snapshot dictionaries."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from trade_logger import TradeLogger

Snapshot = Dict[str, Any]


def _coerce_to_date(value: Any) -> date:
    """Coerce various date-like inputs to :class:`datetime.date`."""

    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, str):
        return date.fromisoformat(value)
    raise TypeError(f"Unsupported date key: {value!r}")


@dataclass
class MarketEnvironment:
    """Iterator-style helper for walking ordered market snapshots."""

    snapshots: Dict[Any, Snapshot]
    start: Optional[Any] = None
    end: Optional[Any] = None
    trade_logger: Optional[TradeLogger] = None
    _ordered: List[Tuple[date, Snapshot]] = field(init=False, default_factory=list)
    _index: int = field(init=False, default=0)

    def __post_init__(self) -> None:
        if self.trade_logger is None:
            self.trade_logger = TradeLogger()

        start_date = _coerce_to_date(self.start) if self.start is not None else None
        end_date = _coerce_to_date(self.end) if self.end is not None else None

        processed: List[Tuple[date, Snapshot]] = []
        for key, raw_snapshot in self.snapshots.items():
            snapshot_date = _coerce_to_date(key)
            if start_date and snapshot_date < start_date:
                continue
            if end_date and snapshot_date > end_date:
                continue

            normalized = self._validate_and_normalize(snapshot_date, raw_snapshot)
            processed.append((snapshot_date, normalized))

        processed.sort(key=lambda item: item[0])
        closes = [self._extract_close(snapshot) for _, snapshot in processed]

        enriched: List[Tuple[date, Snapshot]] = []
        for idx, (snapshot_date, snapshot) in enumerate(processed):
            future_return = None
            current_close = closes[idx]
            next_close = closes[idx + 1] if idx + 1 < len(closes) else None

            if current_close is not None and next_close is not None:
                if current_close == 0:
                    self._log_warning(
                        f"Close price for {snapshot_date.isoformat()} is zero; cannot compute future return."
                    )
                else:
                    future_return = (next_close - current_close) / current_close

            enriched_snapshot = dict(snapshot)
            enriched_snapshot["future_return"] = future_return
            enriched.append((snapshot_date, enriched_snapshot))

        self._ordered = enriched
        self.reset()

    def reset(self) -> Optional[Tuple[date, Snapshot]]:
        """Reset the internal pointer to the beginning of the sequence."""

        self._index = 0
        if not self._ordered:
            return None
        return self._ordered[0]

    def step(self) -> Tuple[Optional[date], Optional[Snapshot], bool]:
        """Return the next snapshot in sequence along with a ``done`` flag."""

        if not self._ordered:
            return None, None, True

        if self._index >= len(self._ordered):
            return None, None, True

        current_date, snapshot = self._ordered[self._index]
        self._index += 1
        done = self._index >= len(self._ordered)
        return current_date, snapshot, done

    def _validate_and_normalize(self, snapshot_date: date, snapshot: Snapshot) -> Snapshot:
        if not isinstance(snapshot, dict):
            raise TypeError(f"Snapshot for {snapshot_date.isoformat()} must be a mapping")

        if "price" not in snapshot:
            raise ValueError(f"Snapshot for {snapshot_date.isoformat()} missing required 'price' key")

        price_data = dict(snapshot["price"] or {})
        if "close" not in price_data:
            raise ValueError(
                f"Snapshot for {snapshot_date.isoformat()} missing required 'price.close' value"
            )

        try:
            price_data["close"] = float(price_data["close"])
        except (TypeError, ValueError):
            raise ValueError(
                f"Snapshot for {snapshot_date.isoformat()} has non-numeric 'price.close' value"
            ) from None

        news_data = snapshot.get("news")
        if news_data is None:
            news_data = {"items": []}
            self._log_warning(
                f"Snapshot for {snapshot_date.isoformat()} missing 'news'; defaulting to empty items."
            )
        elif not isinstance(news_data, dict):
            if isinstance(news_data, Iterable) and not isinstance(news_data, (str, bytes)):
                coerced_items = list(news_data)
            else:
                coerced_items = []
            news_data = {"items": coerced_items}
            self._log_warning(
                f"Snapshot for {snapshot_date.isoformat()} had non-mapping 'news'; coerced to list of items."
            )
        else:
            news_items = news_data.get("items")
            if not isinstance(news_items, list):
                news_data = dict(news_data)
                news_data["items"] = [] if news_items is None else list(news_items)
                self._log_warning(
                    f"Snapshot for {snapshot_date.isoformat()} had non-list 'news.items'; coerced to list."
                )

        filing_q = snapshot.get("filing_q")
        if filing_q is None:
            filing_q = {}
            self._log_warning(
                f"Snapshot for {snapshot_date.isoformat()} missing 'filing_q'; defaulting to empty dict."
            )
        elif not isinstance(filing_q, dict):
            filing_q = {}
            self._log_warning(
                f"Snapshot for {snapshot_date.isoformat()} had non-mapping 'filing_q'; defaulting to empty dict."
            )

        filing_k = snapshot.get("filing_k")
        if filing_k is None:
            filing_k = {}
            self._log_warning(
                f"Snapshot for {snapshot_date.isoformat()} missing 'filing_k'; defaulting to empty dict."
            )
        elif not isinstance(filing_k, dict):
            filing_k = {}
            self._log_warning(
                f"Snapshot for {snapshot_date.isoformat()} had non-mapping 'filing_k'; defaulting to empty dict."
            )

        normalized_snapshot: Snapshot = {
            **{k: v for k, v in snapshot.items() if k not in {"price", "news", "filing_q", "filing_k"}},
            "price": price_data,
            "news": news_data,
            "filing_q": filing_q,
            "filing_k": filing_k,
        }
        return normalized_snapshot

    def _extract_close(self, snapshot: Snapshot) -> Optional[float]:
        price_data = snapshot.get("price")
        if not isinstance(price_data, dict):
            return None
        close_value = price_data.get("close")
        if close_value is None:
            return None
        try:
            return float(close_value)
        except (TypeError, ValueError):
            return None

    def _log_warning(self, message: str) -> None:
        if self.trade_logger is None:
            print(f"[MarketEnvironment] WARNING: {message}")
            return

        log_path = getattr(self.trade_logger, "text_log", None)
        if not isinstance(log_path, (str, Path)):
            print(f"[MarketEnvironment] WARNING: {message}")
            return

        Path(log_path).parent.mkdir(parents=True, exist_ok=True)
        with open(log_path, "a", encoding="utf-8") as handle:
            timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
            handle.write(f"{timestamp} | WARNING | {message}\n")
