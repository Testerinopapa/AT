"""
Integration test for PR #8: EnvironmentAgent-backed Backtrader strategy bridge.

This script spins up a minimal Backtrader Cerebro run with the new
`StrategyBridge` strategy. It uses a stub StrategyManager to produce a BUY on
the first bar and FLAT thereafter, exercising order submit/close, trade logging,
and analytics hooks without requiring MetaTrader5 or a custom Store.

Run:
  python scripts/pr8_strategy_bridge_integration_test.py
"""
from __future__ import annotations

import csv
import sys
from datetime import datetime, timedelta
from pathlib import Path


def _ensure_repo_on_path():
    root = Path(__file__).resolve().parent.parent
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))


class StubStrategyManager:
    """Minimal StrategyManager stub for deterministic signals.

    - Emits BUY on the first bar, FLAT afterwards
    - Exposes combine_* methods expected by StrategyBridge
    """

    def __init__(self):
        self.method = "majority"
        self._fired = False

    def get_individual_signals(self, symbol: str):
        if not self._fired:
            self._fired = True
            return {"stub": "BUY"}
        return {"stub": "FLAT"}

    # Combine helpers mimic typical manager API
    def combine_signals_unanimous(self, signals):
        vals = [v for v in signals.values() if v and v != "NONE"]
        return vals[0] if vals and all(v == vals[0] for v in vals) else "NONE"

    def combine_signals_weighted(self, signals):
        # trivial: BUY wins if present
        if any(v == "BUY" for v in signals.values()):
            return "BUY"
        if any(v == "SELL" for v in signals.values()):
            return "SELL"
        return "NONE"

    def combine_signals_any(self, signals):
        return self.combine_signals_weighted(signals)

    def combine_signals_majority(self, signals):
        # trivial majority
        buy = sum(1 for v in signals.values() if v == "BUY")
        sell = sum(1 for v in signals.values() if v == "SELL")
        if buy > sell:
            return "BUY"
        if sell > buy:
            return "SELL"
        return "NONE"


def _write_csv_bars(path: Path, n: int = 10):
    """Write a simple OHLCV CSV with `n` consecutive minutes."""
    base = datetime.utcnow().replace(second=0, microsecond=0) - timedelta(minutes=n)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        w = csv.writer(f)
        # Backtrader GenericCSVData default headers not required; specify in feed params
        for i in range(n):
            dt = base + timedelta(minutes=i)
            o = 1.2000 + i * 0.0001
            h = o + 0.0005
            l = o - 0.0005
            c = o + 0.0002
            v = 100 + i
            w.writerow([dt.strftime("%Y-%m-%d %H:%M:%S"), o, h, l, c, v])


def main():
    _ensure_repo_on_path()

    import backtrader as bt
    # Compatibility shims for older backtrader exposing VCStore/BrokerBack only
    if not hasattr(bt.stores, "Store") and hasattr(bt.stores, "VCStore"):
        setattr(bt.stores, "Store", bt.stores.VCStore)
    if not hasattr(bt.brokers, "BrokerBase") and hasattr(bt.brokers, "BrokerBack"):
        setattr(bt.brokers, "BrokerBase", bt.brokers.BrokerBack)
    from backtesting.strategy_adapter import StrategyBridge
    from trade_logger import TradeLogger
    from analytics import PerformanceAnalytics

    # 1) Build a tiny CSV data feed
    data_path = Path("data/pr8_bt_bridge_bars.csv")
    _write_csv_bars(data_path, n=12)

    data = bt.feeds.GenericCSVData(
        dataname=str(data_path),
        dtformat="%Y-%m-%d %H:%M:%S",
        datetime=0,
        open=1,
        high=2,
        low=3,
        close=4,
        volume=5,
        openinterest=-1,
        timeframe=bt.TimeFrame.Minutes,
        compression=1,
        header=False,
    )

    # 2) Wire the bridge with stub manager and real logger/analytics
    manager = StubStrategyManager()
    trade_logger = TradeLogger()
    analytics = PerformanceAnalytics()

    cerebro = bt.Cerebro()
    cerebro.adddata(data, name="CSV-EURUSD")
    cerebro.addstrategy(
        StrategyBridge,
        strategy_manager=manager,
        symbol="EURUSD",
        trade_logger=trade_logger,
        risk_manager=None,  # keep MT5 fully out of the loop
        analytics=analytics,
        agent_kwargs=dict(memory_limits={"short": 8, "mid": 8, "long": 8}),
        default_volume=0.01,
    )

    print("[OK] Starting Cerebro run for StrategyBridge...")
    cerebro.run(stdstats=False)
    print("[OK] StrategyBridge run completed.")


if __name__ == "__main__":
    main()

