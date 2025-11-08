"""
Standalone integration test for PR #7: MT5 Backtrader store, data feed, broker.

This script injects a minimal fake MetaTrader5 module so the Backtrader store,
data feed, and broker can be exercised without a live MT5 terminal.

How to run:
  python scripts/pr7_backtrader_integration_test.py

Expected output:
  - Verifies store connect/disconnect
  - Loads a few bars/ticks and prints first datapoint
  - Reads broker cash/value and sends a market order via helper
"""
from __future__ import annotations

import sys
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path


def make_fake_mt5():
    mt5 = types.SimpleNamespace()

    # Constants
    mt5.TIMEFRAME_M1 = 1
    mt5.TIMEFRAME_TICK = -1
    mt5.COPY_TICKS_ALL = 0
    mt5.ORDER_TYPE_BUY = 0
    mt5.ORDER_TYPE_SELL = 1
    mt5.TRADE_ACTION_DEAL = 1
    mt5.TRADE_ACTION_REMOVE = 2
    mt5.ORDER_TIME_GTC = 0
    mt5.ORDER_FILLING_FOK = 0
    mt5.TRADE_RETCODE_DONE = 10009

    state = {"initialized": False}

    def initialize(**kwargs):
        state["initialized"] = True
        return True

    def shutdown():
        state["initialized"] = False
        return True

    def login(*_, **__):
        return True

    def last_error():
        return (0, "OK")

    def account_info():
        return types.SimpleNamespace(balance=100000.0, equity=100000.0)

    def symbol_info_tick(symbol):
        return types.SimpleNamespace(bid=1.2345, ask=1.2347)

    def order_send(payload):
        return types.SimpleNamespace(
            retcode=mt5.TRADE_RETCODE_DONE,
            price=float(payload.get("price", 1.2346)),
            commission=0.0,
            profit=0.0,
            order=42,
        )

    def _rate_bar(ts, o, h, l, c, v):
        return {
            "time": float(ts),
            "open": float(o),
            "high": float(h),
            "low": float(l),
            "close": float(c),
            "tick_volume": float(v),
        }

    def copy_rates_range(symbol, timeframe, start, end):
        base = datetime.now(tz=timezone.utc).timestamp()
        return [
            _rate_bar(base - 180, 1.10, 1.20, 1.00, 1.15, 10),
            _rate_bar(base - 120, 1.15, 1.25, 1.05, 1.20, 11),
            _rate_bar(base - 60, 1.20, 1.30, 1.10, 1.25, 12),
        ]

    def copy_rates_from(symbol, timeframe, since, count):
        base = datetime.now(tz=timezone.utc).timestamp()
        return [
            _rate_bar(base, 1.25, 1.35, 1.15, 1.30, 13),
        ]

    def _tick(ts, bid, ask, last, vol):
        return {
            "time": float(ts),
            "time_msc": float(ts * 1000.0),
            "bid": float(bid),
            "ask": float(ask),
            "last": float(last),
            "volume": float(vol),
            "volume_real": float(vol),
        }

    def copy_ticks_range(symbol, start, end, flags):
        base = datetime.now(tz=timezone.utc).timestamp()
        return [
            _tick(base - 2, 1.2345, 1.2347, 1.2346, 1),
            _tick(base - 1, 1.2346, 1.2348, 1.2347, 2),
        ]

    # Bind
    mt5.initialize = initialize
    mt5.shutdown = shutdown
    mt5.login = login
    mt5.last_error = last_error
    mt5.account_info = account_info
    mt5.symbol_info_tick = symbol_info_tick
    mt5.order_send = order_send
    mt5.copy_rates_range = copy_rates_range
    mt5.copy_rates_from = copy_rates_from
    mt5.copy_ticks_range = copy_ticks_range

    return mt5


def main():
    # Ensure project root is importable regardless of invocation path
    root = Path(__file__).resolve().parent.parent
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    # Inject fake MetaTrader5 before importing the PR modules
    sys.modules["MetaTrader5"] = make_fake_mt5()

    import backtrader as bt
    # Backtrader compatibility shims for import-time bases only (no Cerebro run)
    if not hasattr(bt.stores, "Store") and hasattr(bt.stores, "VCStore"):
        setattr(bt.stores, "Store", bt.stores.VCStore)
    if not hasattr(bt.brokers, "BrokerBase") and hasattr(bt.brokers, "BrokerBack"):
        setattr(bt.brokers, "BrokerBase", bt.brokers.BrokerBack)

    from backtesting.mt5_store import MT5Store, MT5Data, MT5Broker
    from mt5_helpers import OrderRequest, send_market_order

    # 1) Store connectivity
    store = MT5Store()
    assert store.connect() is True
    print("[OK] Store connected")
    store.disconnect()
    print("[OK] Store disconnected")

    # 2) Data feed instances (direct buffer inspection)
    store = MT5Store()
    data_bars = MT5Data(
        store=store,
        dataname="EURUSD",
        mt5_timeframe=sys.modules["MetaTrader5"].TIMEFRAME_M1,
        timeframe=bt.TimeFrame.Minutes,
        timezone=None,
    )
    data_bars._load_initial_history()
    assert data_bars._buffer, "Bars buffer is empty"
    print("[OK] Bars loaded:", data_bars._buffer[0])

    data_ticks = MT5Data(
        store=store,
        dataname="EURUSD",
        mt5_timeframe=sys.modules["MetaTrader5"].TIMEFRAME_TICK,
        timeframe=bt.TimeFrame.Ticks,
        timezone=None,
    )
    data_ticks._load_initial_history()
    assert data_ticks._buffer, "Ticks buffer is empty"
    print("[OK] Ticks loaded:", data_ticks._buffer[0])

    # 3) Broker helpers (account/value) and market order helper
    broker = MT5Broker(store=store)
    print("[OK] Broker cash:", broker.getcash())
    print("[OK] Broker value:", broker.getvalue())

    req = OrderRequest(symbol="EURUSD", action="BUY", volume=0.1)
    result = send_market_order(req)
    assert result.retcode == sys.modules["MetaTrader5"].TRADE_RETCODE_DONE
    print("[OK] Market order helper returned DONE")


if __name__ == "__main__":
    main()

