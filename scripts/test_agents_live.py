"""
Live integration test for PR #4 (agents + LLM) with MetaTrader5.

This script:
  - Initializes MetaTrader5 and selects the symbol
  - Builds daily snapshots via market_data.build_daily_snapshots
  - Constructs a real StrategyManager from the strategies package
  - Runs EnvironmentAgent with an OpenRouter LLM backend (optional)

Requirements:
  - MetaTrader 5 terminal installed and logged in on this machine
  - Python package MetaTrader5 installed
  - requests installed (for LLM backend)
  - OPENROUTER_API_KEY set (via environment or .env) if you want LLM calls

Usage (from repo root):
  python -m scripts.test_agents_live --symbol EURUSD \
      --start 2024-02-01 --end 2024-02-07 \
      --model minimax/minimax-m2:free --verbose
"""

from __future__ import annotations

import argparse
import os
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Live MT5 + LLM integration test for EnvironmentAgent")
    p.add_argument("--symbol", required=True, help="Trading symbol (e.g. EURUSD, GBPUSD)")
    p.add_argument("--start", required=True, help="Start date (YYYY-MM-DD)")
    p.add_argument("--end", required=True, help="End date (YYYY-MM-DD)")
    p.add_argument("--model", default="@preset/tradebot", help="OpenRouter model id (e.g. minimax/minimax-m2:free)")
    p.add_argument("--no-llm", action="store_true", help="Disable LLM and use majority voting only")
    p.add_argument("--verbose", action="store_true", help="Print per-day details")
    return p.parse_args()


def _ensure_dt_utc(d: date) -> datetime:
    return datetime(d.year, d.month, d.day, tzinfo=timezone.utc)


def _load_env_file() -> None:
    # Simple .env loader (OPENROUTER_API_KEY only) – ignore if missing
    env_path = Path(".env")
    if not env_path.exists():
        return
    try:
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                k, v = line.split("=", 1)
                k, v = k.strip(), v.strip()
                if k and (k not in os.environ):
                    os.environ[k] = v
    except Exception:
        pass


def _extract_titles(items: Optional[Dict[str, Any]]) -> List[str]:
    if not isinstance(items, dict):
        return []
    arr = items.get("items")
    if not isinstance(arr, list):
        return []
    titles: List[str] = []
    for row in arr:
        if isinstance(row, dict):
            t = row.get("title")
            if t:
                titles.append(str(t))
    return titles


def main() -> None:
    args = _parse_args()
    _load_env_file()

    # Live MT5
    import MetaTrader5 as mt5
    if not mt5.initialize():
        raise SystemExit(f"Failed to initialize MetaTrader5: {mt5.last_error()}")
    try:
        if not mt5.symbol_select(args.symbol, True):
            raise SystemExit(f"Failed to select symbol: {args.symbol}")

        # Build snapshots for the requested window
        from market_data import build_daily_snapshots
        start_d = date.fromisoformat(args.start)
        end_d = date.fromisoformat(args.end)
        snapshots = build_daily_snapshots(args.symbol, _ensure_dt_utc(start_d), _ensure_dt_utc(end_d))

        # Construct StrategyManager with real strategies
        from strategies import (
            StrategyManager,
            SimpleStrategy,
            MAStrategy,
            RSIStrategy,
            MACDStrategy,
        )

        manager = StrategyManager(method="majority")
        manager.add_strategy(SimpleStrategy())
        manager.add_strategy(MAStrategy({"timeframe": mt5.TIMEFRAME_M5, "fast_period": 10, "slow_period": 20, "ma_type": "EMA"}))
        manager.add_strategy(RSIStrategy({"timeframe": mt5.TIMEFRAME_M5, "period": 14, "oversold": 30, "overbought": 70}))
        manager.add_strategy(MACDStrategy({"timeframe": mt5.TIMEFRAME_M15, "fast_period": 12, "slow_period": 26, "signal_period": 9}))

        # EnvironmentAgent with optional LLM backend
        from agents.environment_agent import EnvironmentAgent

        llm_executor: Optional[Any]
        llm_cfg: Optional[Dict[str, Any]]
        if args.no_llm:
            llm_executor = None
            llm_cfg = None
        else:
            llm_executor = "openrouter"
            llm_cfg = {"model": args.model}
            if not os.environ.get("OPENROUTER_API_KEY"):
                print("[WARN] OPENROUTER_API_KEY not set; proceeding without LLM.")
                llm_executor = None
                llm_cfg = None

        agent = EnvironmentAgent(
            strategy_manager=manager,
            symbol=args.symbol,
            llm_executor=llm_executor,
            llm_config=llm_cfg,
        )

        # Iterate snapshots by date
        decisions: List[Tuple[str, str]] = []
        for d in sorted(snapshots.keys()):
            snap = snapshots[d]
            price_close = (snap.get("price") or {}).get("close")
            filing_k_titles = _extract_titles(snap.get("filing_k"))
            filing_q_titles = _extract_titles(snap.get("filing_q"))
            news_titles = []
            news = snap.get("news")
            if isinstance(news, dict):
                for item in news.get("items", []) if isinstance(news.get("items"), list) else []:
                    t = item.get("title") if isinstance(item, dict) else None
                    if t:
                        news_titles.append(str(t))

            res = agent.step(
                date=d.isoformat() if hasattr(d, "isoformat") else str(d),
                price=price_close,
                filing_k=filing_k_titles,
                filing_q=filing_q_titles,
                news=news_titles,
                future_return=None,
            )
            decisions.append((str(d), res.get("decision", "NONE")))
            if args.verbose:
                print(f"{d} | price={price_close} | decision={res.get('decision')} | rationale={res.get('rationale')}")

        # Summary
        totals: Dict[str, int] = {"BUY": 0, "SELL": 0, "NONE": 0}
        for _, dec in decisions:
            totals[dec] = totals.get(dec, 0) + 1

        print("Live agents integration test COMPLETE")
        print(f" Symbol: {args.symbol}")
        print(f" Range:  {start_d} .. {end_d}")
        print(f" Totals: BUY={totals['BUY']}, SELL={totals['SELL']}, NONE={totals['NONE']}")
        if not args.verbose:
            for d, dec in decisions[:3]:
                print(f"  {d} -> {dec}")

    finally:
        try:
            mt5.shutdown()
        except Exception:
            pass


if __name__ == "__main__":
    main()

