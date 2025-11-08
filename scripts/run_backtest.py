"""
CLI: Run a Backtrader backtest using StrategyBridge (EnvironmentAgent bridge).

Examples
- Yahoo Finance, 7 days of 1h bars (default):
    python scripts/run_backtest.py --symbol EURUSD

- Yahoo Finance, 30 days of 15m bars:
    python scripts/run_backtest.py --symbol EURUSD --period 30 --interval 15m

- CSV file with OHLCV (datetime,open,high,low,close,volume):
    python scripts/run_backtest.py --source csv --csv data/eurusd_7d_1h.csv \
      --dtformat "%Y-%m-%d %H:%M:%S"

Notes
- Uses a stub StrategyManager by default to avoid MetaTrader dependencies.
- Writes logs and analytics to the existing logs/ paths.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path


def ensure_repo_on_path() -> None:
    root = Path(__file__).resolve().parent.parent
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))


class StubStrategyManager:
    """Deterministic signal source for offline testing.

    BUY for the first N bars (default 5) then FLAT to realize PnL.
    """

    def __init__(self, warmup_bars: int = 5):
        self.method = "majority"
        self._count = 0
        self._warmup = int(warmup_bars)

    def get_individual_signals(self, symbol: str):
        self._count += 1
        if self._count <= self._warmup:
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


def _load_yahoo(symbol: str, period: int, interval: str):
    import yfinance as yf
    df = yf.download(
        "EURUSD=X" if symbol.upper() == "EURUSD" else symbol,
        period=f"{int(period)}d",
        interval=interval,
        auto_adjust=False,
        progress=False,
    )
    if df is None or getattr(df, "empty", True):
        raise RuntimeError("No data returned by Yahoo Finance")
    # Normalize columns to OHLCV
    df = df.dropna()
    if hasattr(df, "columns") and any(isinstance(c, tuple) for c in df.columns):
        cols = []
        for c in df.columns:
            if isinstance(c, tuple):
                name = None
                for part in c:
                    if str(part).lower() in {"open", "high", "low", "close", "adj close", "volume"}:
                        name = str(part)
                        break
                cols.append(name or str(c[0]))
            else:
                cols.append(str(c))
        df.columns = cols
    df = df.rename(columns={"Adj Close": "Close", "adj close": "Close"})
    return df[["Open", "High", "Low", "Close", "Volume"]]


def _load_csv(path: Path, dtformat: str):
    import backtrader as bt  # only type reference, actual feed created later
    # Return parameters for GenericCSVData
    return dict(
        dataname=str(path),
        dtformat=dtformat,
        datetime=0,
        open=1,
        high=2,
        low=3,
        close=4,
        volume=5,
        openinterest=-1,
    )


def run(args: argparse.Namespace) -> None:
    ensure_repo_on_path()

    import backtrader as bt
    # Backtrader 1.9.78 compatibility for base classes
    if not hasattr(bt.stores, "Store") and hasattr(bt.stores, "VCStore"):
        setattr(bt.stores, "Store", bt.stores.VCStore)
    if not hasattr(bt.brokers, "BrokerBase") and hasattr(bt.brokers, "BrokerBack"):
        setattr(bt.brokers, "BrokerBase", bt.brokers.BrokerBack)

    from backtesting.strategy_adapter import StrategyBridge
    from trade_logger import TradeLogger
    from analytics import PerformanceAnalytics

    symbol = args.symbol.upper()
    interval = args.interval
    period = int(args.period)

    data_feed = None
    if args.source == "yahoo":
        try:
            df = _load_yahoo(symbol, period, interval)
        except Exception as exc:
            # Attempt a minimal fallback for intraday limits
            if interval != "1d":
                import yfinance as yf
                df = yf.download(
                    "EURUSD=X" if symbol == "EURUSD" else symbol,
                    period="7d",
                    interval=interval,
                    auto_adjust=False,
                    progress=False,
                )
                if df is None or getattr(df, "empty", True):
                    print(f"ERROR: Yahoo load failed: {exc}")
                    return
            else:
                print(f"ERROR: Yahoo load failed: {exc}")
                return
        data_feed = bt.feeds.PandasData(dataname=df)
    else:
        csv_params = _load_csv(Path(args.csv), args.dtformat)
        data_feed = bt.feeds.GenericCSVData(**csv_params)

    # Build components
    manager = StubStrategyManager(warmup_bars=args.warmup)
    trade_logger = TradeLogger()
    analytics = PerformanceAnalytics()

    cerebro = bt.Cerebro()
    cerebro.broker.set_cash(float(args.initial_cash))
    if args.commission:
        cerebro.broker.setcommission(commission=float(args.commission))
    cerebro.adddata(data_feed, name=f"{symbol}-{interval}")
    cerebro.addstrategy(
        StrategyBridge,
        strategy_manager=manager,
        symbol=symbol,
        trade_logger=trade_logger,
        risk_manager=None,
        analytics=analytics,
        agent_kwargs=_build_agent_kwargs(args),
        default_volume=float(args.volume),
        decision_log_path=(args.decisions_path if args.log_decisions else None),
        log_all_decisions=bool(args.log_decisions),
    )

    print("\n========================================")
    print("Running StrategyBridge backtest (offline)")
    print("========================================")
    print(f"Symbol: {symbol}")
    print(f"Interval: {interval} | Period: {period}d")
    print(f"Initial cash: {float(args.initial_cash):.2f} | Commission: {float(args.commission)}")
    cerebro.run(stdstats=False)
    print("Portfolio value:", cerebro.broker.getvalue())


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Backtrader backtest runner (StrategyBridge)")
    p.add_argument("--symbol", default="EURUSD", help="Symbol (use EURUSD for Yahoo EURUSD=X)")
    p.add_argument("--source", choices=["yahoo", "csv"], default="yahoo", help="Data source")
    p.add_argument("--period", type=int, default=7, help="Days to load (Yahoo only)")
    p.add_argument("--interval", default="1h", help="Bar interval: 1m/5m/15m/30m/1h/1d (Yahoo)")
    p.add_argument("--csv", help="CSV path when --source csv")
    p.add_argument("--dtformat", default="%Y-%m-%d %H:%M:%S", help="CSV datetime format")
    p.add_argument("--initial-cash", type=float, default=100000.0, help="Starting cash")
    p.add_argument("--commission", type=float, default=0.0002, help="Commission rate (e.g., 0.0002)")
    p.add_argument("--volume", type=float, default=0.1, help="Default order volume")
    p.add_argument("--warmup", type=int, default=5, help="Bars to BUY before FLAT (stub manager)")
    p.add_argument("--log-decisions", action="store_true", help="Log per-bar decisions to JSONL")
    p.add_argument("--decisions-path", default="logs/llm_decisions.jsonl", help="Path for decisions JSONL log")
    p.add_argument("--llm", choices=["none", "openrouter"], default="none", help="Enable LLM backend for decisions")
    p.add_argument("--llm-config", help="Optional JSON string with LLM config (backend specific)")
    return p


def _build_agent_kwargs(args: argparse.Namespace):
    kwargs = dict(memory_limits={"short": 64, "mid": 48, "long": 32})
    if args.llm and args.llm != "none":
        kwargs["llm_executor"] = args.llm
        if args.llm_config:
            try:
                import json as _json
                kwargs["llm_config"] = _json.loads(args.llm_config)
            except Exception:
                pass
    return kwargs


if __name__ == "__main__":
    parser = build_parser()
    args = parser.parse_args()
    run(args)
