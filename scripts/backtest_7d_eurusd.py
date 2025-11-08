"""
Backtest EURUSD over the last 7 days using Backtrader + StrategyBridge.

Data: downloaded from Yahoo Finance (EURUSD=X) with 1h candles.
Strategy: EnvironmentAgent bridge with a simple stub StrategyManager that
          goes BUY for the first 5 bars then FLAT to realize PnL.

Run:
  python scripts/backtest_7d_eurusd.py
"""
from __future__ import annotations

import sys
import subprocess
from pathlib import Path


def ensure_repo_on_path():
    root = Path(__file__).resolve().parent.parent
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))


def ensure_deps():
    try:
        import pandas  # noqa: F401
        import yfinance  # noqa: F401
    except Exception:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "pandas", "yfinance", "--quiet"])  # noqa: S603,S607


class StubStrategyManager:
    """Deterministic signal source for backtest repeatability."""

    def __init__(self):
        self.method = "majority"
        self._count = 0

    def get_individual_signals(self, symbol: str):
        # BUY for first 5 bars, then FLAT to trigger a close and realize PnL
        self._count += 1
        if self._count <= 5:
            return {"stub": "BUY"}
        return {"stub": "FLAT"}

    # Minimal combine_* methods expected by StrategyBridge
    def combine_signals_unanimous(self, signals):
        vals = [v for v in signals.values() if v and v != "NONE"]
        return vals[0] if vals and all(v == vals[0] for v in vals) else "NONE"

    def combine_signals_weighted(self, signals):
        if any(v == "BUY" for v in signals.values()):
            return "BUY"
        if any(v == "SELL" for v in signals.values()):
            return "SELL"
        return "NONE"

    def combine_signals_any(self, signals):
        return self.combine_signals_weighted(signals)

    def combine_signals_majority(self, signals):
        buy = sum(1 for v in signals.values() if v == "BUY")
        sell = sum(1 for v in signals.values() if v == "SELL")
        if buy > sell:
            return "BUY"
        if sell > buy:
            return "SELL"
        return "NONE"


def download_eurusd_7d_1h():
    import yfinance as yf
    import pandas as pd

    df = yf.download(
        "EURUSD=X",
        period="7d",
        interval="1h",
        auto_adjust=False,
        prepost=False,
        progress=False,
        threads=True,
    )
    if df is None or df.empty:
        raise RuntimeError("Failed to download EURUSD=X data from Yahoo Finance")
    # Flatten potential MultiIndex columns and standardize names
    df = df.dropna()
    cols = []
    for c in df.columns:
        if isinstance(c, tuple):
            # yfinance can return MultiIndex like (field, ticker) or (ticker, field)
            # pick the element that looks like a field name
            name = None
            for part in c:
                if str(part).lower() in {"open","high","low","close","adj close","volume"}:
                    name = str(part)
                    break
            cols.append(name or str(c[0]))
        else:
            cols.append(str(c))
    df.columns = cols
    rename = {"Adj Close": "Close", "adj close": "Close"}
    df = df.rename(columns=rename)
    # Keep Backtrader-required columns
    df = df[["Open","High","Low","Close","Volume"]]
    # Ensure numeric
    df = df.astype({"Open":"float64","High":"float64","Low":"float64","Close":"float64","Volume":"float64"})
    return df


def run_backtest():
    ensure_repo_on_path()
    ensure_deps()

    import backtrader as bt
    # Import-time compatibility shims for base classes
    if not hasattr(bt.stores, "Store") and hasattr(bt.stores, "VCStore"):
        setattr(bt.stores, "Store", bt.stores.VCStore)
    if not hasattr(bt.brokers, "BrokerBase") and hasattr(bt.brokers, "BrokerBack"):
        setattr(bt.brokers, "BrokerBase", bt.brokers.BrokerBack)

    from backtesting.strategy_adapter import StrategyBridge
    from trade_logger import TradeLogger
    from analytics import PerformanceAnalytics

    df = download_eurusd_7d_1h()

    data = bt.feeds.PandasData(dataname=df)

    manager = StubStrategyManager()
    trade_logger = TradeLogger()
    analytics = PerformanceAnalytics()

    cerebro = bt.Cerebro()
    cerebro.broker.set_cash(100000.0)
    cerebro.broker.setcommission(commission=0.0002)  # 2 bps
    cerebro.adddata(data, name="EURUSD-1H")
    cerebro.addstrategy(
        StrategyBridge,
        strategy_manager=manager,
        symbol="EURUSD",
        trade_logger=trade_logger,
        risk_manager=None,
        analytics=analytics,
        agent_kwargs=dict(memory_limits={"short": 64, "mid": 48, "long": 32}),
        default_volume=0.1,
    )

    print("[Backtest] Running 7-day EURUSD backtest (1H bars)...")
    cerebro.run(stdstats=False)
    print("[Backtest] Done. Portfolio value:", cerebro.broker.getvalue())


if __name__ == "__main__":
    run_backtest()
