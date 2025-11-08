"""Backtesting entry point that wires MetaTrader 5 data to Backtrader."""
from __future__ import annotations

from typing import Any, Dict, Optional

import backtrader as bt

from . import MT5Data, MT5Store
from .config import parse_backtest_config
from .strategy_adapter import StrategyBridge


def _extract_market_data_config(config: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(config, dict):
        return {}
    market_cfg = config.get("market_data", {})
    return market_cfg if isinstance(market_cfg, dict) else {}


def _configure_commission(broker: bt.brokers.BackBroker, commission_cfg: Dict[str, Any]) -> None:
    model = str(commission_cfg.get("model", "percentage")).strip().lower()
    rate = float(commission_cfg.get("rate", 0.0))
    per_trade = float(commission_cfg.get("per_trade", 0.0))

    if model == "percentage":
        broker.setcommission(commission=rate)
    elif model in {"fixed", "per_trade"}:
        broker.setcommission(commission=0.0, fixed=per_trade)
    else:
        print(
            "⚠️  Unsupported commission model '%s'. Falling back to percentage." % model
        )
        broker.setcommission(commission=rate)


def run_backtest(
    config: Dict[str, Any],
    strategy_manager: Any,
    risk_manager: Any,
    trade_logger: Any,
    analytics: Any,
) -> Optional[Any]:
    """Execute a Backtrader run using the MetaTrader5 bridge strategy."""

    if not isinstance(config, dict):
        raise TypeError("config must be a dictionary containing backtest settings")

    market_cfg = _extract_market_data_config(config)
    backtest_cfg = parse_backtest_config(market_cfg.get("backtest"))
    history_cfg = backtest_cfg.get("history", {})

    symbol = str(config.get("symbol", "EURUSD"))
    default_volume = float(config.get("volume", 0.1))

    cerebro = bt.Cerebro()
    cerebro.broker.setcash(float(backtest_cfg.get("initial_cash", 100000.0)))
    _configure_commission(cerebro.broker, backtest_cfg.get("commission", {}))

    store = MT5Store()
    data_feed = MT5Data(
        store=store,
        dataname=symbol,
        mt5_timeframe=backtest_cfg.get("timeframe"),
        fromdate=history_cfg.get("start"),
        todate=history_cfg.get("end"),
        timezone=history_cfg.get("timezone"),
    )
    cerebro.adddata(data_feed)

    agent_kwargs = {
        "llm_executor": market_cfg.get("llm_executor"),
        "llm_config": market_cfg.get("llm_config"),
    }

    cerebro.addstrategy(
        StrategyBridge,
        strategy_manager=strategy_manager,
        symbol=symbol,
        trade_logger=trade_logger,
        risk_manager=risk_manager,
        analytics=analytics,
        agent_kwargs=agent_kwargs,
        default_volume=default_volume,
    )

    try:
        results = cerebro.run()
    finally:
        store.stop()

    final_value = cerebro.broker.getvalue()
    print(f"🏁 Backtest complete. Final portfolio value: {final_value:.2f}")

    if analytics and hasattr(analytics, "print_summary_report"):
        try:
            analytics.print_summary_report()
        except Exception as exc:  # pragma: no cover - defensive logging
            print(f"⚠️  Failed to render analytics summary: {exc}")

    return results


__all__ = ["run_backtest"]
