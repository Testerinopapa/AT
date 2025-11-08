"""Backtrader adapter that mirrors the live-trading execution pipeline.

The :class:`StrategyBridge` strategy wires the in-memory ``EnvironmentAgent``
to Backtrader so historical candles can be replayed while still exercising the
same signal aggregation, risk management and logging hooks used in production.

The bridge intentionally mirrors the live workflow:

* Each bar's close, news headlines and optional metadata are forwarded to the
  :meth:`EnvironmentAgent.step` method to maintain memory buffers.
* The resulting strategy signals are combined using the configured
  :class:`~strategies.strategy_manager.StrategyManager` method so enable flags
  and weights are honoured exactly as they are in live trading.
* Position sizing, stop-loss and take-profit levels are produced by the shared
  :class:`~risk_manager.RiskManager` helpers to keep sizing logic identical to
  production execution.
* Order events are forwarded to :class:`~trade_logger.TradeLogger` and closing
  trades notify :class:`~analytics.PerformanceAnalytics` so downstream
  analytics continue to receive consistent data.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional

import backtrader as bt

from agents import EnvironmentAgent
from analytics import PerformanceAnalytics
from risk_manager import RiskManager
from trade_logger import TradeLogger


def _ensure_iterable(value: Optional[Any]) -> List[str]:
    """Coerce Backtrader line values into a list of strings."""

    return EnvironmentAgent._ensure_iterable(value)


@dataclass
class _BacktestOrderResult:
    """Light-weight stand-in for MetaTrader5's order result objects."""

    order: int
    price: float
    volume: float
    retcode: int = 10009  # Matches ``mt5.TRADE_RETCODE_DONE``
    comment: str = "Backtrader order"


class StrategyBridge(bt.Strategy):
    """Backtrader strategy that proxies signals from ``EnvironmentAgent``."""

    params = dict(
        strategy_manager=None,
        symbol="EURUSD",
        trade_logger=None,
        risk_manager=None,
        analytics=None,
        agent_kwargs=None,
        default_volume=0.1,
    )

    def __init__(self) -> None:
        manager = self.p.strategy_manager
        if manager is None:
            raise ValueError("StrategyBridge requires a StrategyManager instance")

        agent_kwargs = dict(self.p.agent_kwargs or {})
        agent_kwargs.setdefault("strategy_manager", manager)
        agent_kwargs.setdefault("symbol", self.p.symbol)
        agent_kwargs.setdefault("trade_logger", self.p.trade_logger)

        self.agent = EnvironmentAgent(**agent_kwargs)
        self.strategy_manager = manager
        self.trade_logger: Optional[TradeLogger] = self.p.trade_logger
        self.analytics: Optional[PerformanceAnalytics] = self.p.analytics
        self.risk_manager: Optional[RiskManager] = self.p.risk_manager
        self.symbol: str = self.p.symbol
        self.default_volume: float = float(self.p.default_volume)

        self._pending_order = None
        self._pending_orders: Dict[int, Dict[str, Any]] = {}
        self._ticket_counter = 0
        self._last_action: Optional[str] = None

    # ------------------------------------------------------------------
    # Backtrader life-cycle hooks
    # ------------------------------------------------------------------
    def next(self) -> None:  # pragma: no cover - Backtrader runtime hook
        if self._pending_order:
            return

        date = self.data.datetime.datetime(0)
        date_label = date.isoformat() if isinstance(date, datetime) else str(date)
        close_price = float(self.data.close[0]) if len(self.data.close) else None

        news_items = _ensure_iterable(self._extract_line(self.data, "news"))
        meta_items = _ensure_iterable(self._extract_line(self.data, "meta"))
        filings_q = _ensure_iterable(self._extract_line(self.data, "filing_q"))
        filings_k = _ensure_iterable(self._extract_line(self.data, "filing_k"))
        future_return = self._extract_line(self.data, "future_return")

        combined_news: List[str] = []
        if news_items:
            combined_news.extend(news_items)
        if meta_items:
            combined_news.extend(meta_items)

        step_result = self.agent.step(
            date_label,
            close_price,
            filings_k,
            filings_q,
            combined_news,
            future_return=future_return,
        )

        decision = self._resolve_decision(step_result)

        if decision == "BUY":
            self._handle_entry("BUY", close_price)
        elif decision == "SELL":
            self._handle_entry("SELL", close_price)
        else:
            self._flatten_if_needed()

        self._last_action = decision

    def notify_order(self, order):  # pragma: no cover - Backtrader runtime hook
        if order.status in [order.Submitted, order.Accepted]:
            return

        if order.status == order.Completed:
            meta = self._pending_orders.pop(order.ref, {})
            action = meta.get("action", "BUY" if order.isbuy() else "SELL")
            ticket = meta.get("ticket", self._ticket_counter)
            sl = meta.get("sl")
            tp = meta.get("tp")
            volume = abs(order.executed.size)
            entry_price = order.executed.price

            if self.trade_logger:
                result = _BacktestOrderResult(
                    order=ticket,
                    price=entry_price,
                    volume=volume,
                )
                strategy_label = getattr(self.strategy_manager, "method", "UNKNOWN").upper()
                self.trade_logger.log_trade_open(
                    symbol=self.symbol,
                    action=action,
                    result=result,
                    volume=volume,
                    entry_price=entry_price,
                    sl=sl if sl is not None else 0.0,
                    tp=tp if tp is not None else 0.0,
                    strategy=strategy_label,
                )

        if order.status in [order.Completed, order.Canceled, order.Margin, order.Rejected]:
            self._pending_order = None

    def notify_trade(self, trade):  # pragma: no cover - Backtrader runtime hook
        if not trade.isclosed:
            return

        ticket = getattr(trade, "ref", None)
        exit_price = trade.price
        profit = trade.pnl

        if self.trade_logger:
            self.trade_logger.log_trade_close(
                ticket=ticket if ticket is not None else self._ticket_counter,
                exit_price=exit_price,
                profit=profit,
                commission=getattr(trade, "commission", 0.0),
                swap=getattr(trade, "pnlcomm", 0.0),
            )

        if self.risk_manager and hasattr(self.risk_manager, "update_daily_pnl"):
            self.risk_manager.update_daily_pnl(profit)

        self._notify_analytics_on_close()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _extract_line(self, data, name: str) -> Optional[Any]:
        line = getattr(data, name, None)
        if line is None:
            return None
        try:
            return line[0]
        except TypeError:
            return line

    def _resolve_decision(self, step_result: Dict[str, Any]) -> str:
        raw_decision = (step_result or {}).get("decision", "NONE")
        signals = (step_result or {}).get("signals", {})

        manager = self.strategy_manager
        if not manager or not signals:
            return self._normalise_decision(raw_decision)

        method = getattr(manager, "method", "majority")
        method = (method or "majority").lower()

        if method == "unanimous":
            combined = manager.combine_signals_unanimous(signals)
        elif method == "weighted":
            combined = manager.combine_signals_weighted(signals)
        elif method == "any":
            combined = manager.combine_signals_any(signals)
        else:
            combined = manager.combine_signals_majority(signals)

        return self._normalise_decision(combined or raw_decision)

    @staticmethod
    def _normalise_decision(decision: Optional[str]) -> str:
        if not decision:
            return "FLAT"
        upper = decision.upper()
        if upper in {"BUY", "SELL"}:
            return upper
        if upper in {"NONE", "FLAT", "HOLD"}:
            return "FLAT"
        return upper

    def _handle_entry(self, action: str, price: Optional[float]) -> None:
        if price is None:
            return

        if self.position:
            if (action == "BUY" and self.position.size > 0) or (
                action == "SELL" and self.position.size < 0
            ):
                return

            if (action == "BUY" and self.position.size < 0) or (
                action == "SELL" and self.position.size > 0
            ):
                self._pending_order = self.close()
                return

        lot_size, sl, tp = self._calculate_risk_params(action, price)
        size = lot_size if lot_size is not None else self.default_volume

        if action == "BUY":
            order = self.buy(size=size)
        else:
            order = self.sell(size=size)

        self._ticket_counter += 1
        self._pending_order = order
        self._pending_orders[order.ref] = {
            "action": action,
            "sl": sl,
            "tp": tp,
            "ticket": self._ticket_counter,
        }

    def _flatten_if_needed(self) -> None:
        if not self.position:
            return

        if self._last_action == "FLAT":
            return

        self._pending_order = self.close()

    def _calculate_risk_params(self, action: str, price: float):
        lot_size = None
        sl = None
        tp = None

        if not self.risk_manager:
            return lot_size, sl, tp

        try:
            sl, tp = self.risk_manager.calculate_sl_tp(self.symbol, action, price)
        except Exception:
            sl, tp = None, None

        sl_distance_pips = None
        if sl is not None:
            point = self._infer_point()
            if point:
                sl_distance_pips = abs(price - sl) / (point * 10)

        enable_dynamic = bool(
            getattr(self.risk_manager, "risk_config", {}).get(
                "enable_dynamic_lot_sizing", False
            )
        )

        if enable_dynamic and sl_distance_pips and sl_distance_pips > 0:
            try:
                lot_size = self.risk_manager.calculate_lot_size(
                    self.symbol, sl_distance_pips
                )
            except Exception:
                lot_size = None

        return lot_size, sl, tp

    def _infer_point(self) -> Optional[float]:
        if not self.risk_manager:
            return None

        try:
            import MetaTrader5 as mt5  # type: ignore
        except Exception:
            return None

        symbol_info = mt5.symbol_info(self.symbol)
        if symbol_info is None:
            return None

        return getattr(symbol_info, "point", None)

    def _notify_analytics_on_close(self) -> None:
        if not self.analytics:
            return

        for attr in ("on_trade_closed", "register_trade_close", "record_trade"):
            hook = getattr(self.analytics, attr, None)
            if callable(hook):
                try:
                    hook()
                except TypeError:
                    hook({})
                return

        generate = getattr(self.analytics, "generate_performance_report", None)
        if callable(generate):
            try:
                generate()
            except TypeError:
                generate(30)

