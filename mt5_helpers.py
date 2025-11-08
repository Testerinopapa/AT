"""Utility functions for working with the MetaTrader5 API.

The helpers centralise order submission logic so it can be reused by both the
interactive trading loop and any integration layers (for example Backtrader
stores/brokers).  They offer small, composable wrappers around
``mt5.order_send`` for the most common market and cancel actions.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import MetaTrader5 as mt5


@dataclass
class OrderRequest:
    """Structured representation of a market order request."""

    symbol: str
    action: str
    volume: float
    price: Optional[float] = None
    deviation: int = 20
    sl: Optional[float] = None
    tp: Optional[float] = None
    magic: int = 0
    comment: Optional[str] = None
    type_time: int = mt5.ORDER_TIME_GTC
    type_filling: int = mt5.ORDER_FILLING_FOK
    position: Optional[int] = None

    def to_request(self) -> dict:
        """Convert the dataclass into the MetaTrader5 request payload."""

        action = self.action.upper()
        if action not in {"BUY", "SELL"}:
            raise ValueError(f"Unsupported order action '{self.action}'.")

        order_type = mt5.ORDER_TYPE_BUY if action == "BUY" else mt5.ORDER_TYPE_SELL

        price = self.price
        if price is None:
            tick = mt5.symbol_info_tick(self.symbol)
            if tick is None:
                raise RuntimeError(f"Unable to resolve latest tick for {self.symbol}.")
            price = tick.ask if order_type == mt5.ORDER_TYPE_BUY else tick.bid

        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": self.symbol,
            "volume": float(self.volume),
            "type": order_type,
            "price": float(price),
            "deviation": int(self.deviation),
            "type_time": self.type_time,
            "type_filling": self.type_filling,
        }

        if self.sl is not None:
            request["sl"] = float(self.sl)
        if self.tp is not None:
            request["tp"] = float(self.tp)
        if self.magic is not None:
            request["magic"] = int(self.magic)
        if self.comment:
            request["comment"] = str(self.comment)
        if self.position is not None:
            request["position"] = int(self.position)

        return request


def send_market_order(request: OrderRequest) -> mt5.TradeResult:
    """Submit a market order using the provided ``OrderRequest``."""

    payload = request.to_request()
    return mt5.order_send(payload)


def close_position_by_ticket(
    ticket: int,
    symbol: str,
    volume: float,
    side: str,
    deviation: int = 20,
    magic: int = 0,
    comment: Optional[str] = None,
) -> mt5.TradeResult:
    """Close an existing position identified by its ticket."""

    side = side.upper()
    if side not in {"BUY", "SELL"}:
        raise ValueError("side must be either 'BUY' or 'SELL'")

    order_type = mt5.ORDER_TYPE_SELL if side == "BUY" else mt5.ORDER_TYPE_BUY
    tick = mt5.symbol_info_tick(symbol)
    if tick is None:
        raise RuntimeError(f"Unable to resolve latest tick for {symbol}.")

    price = tick.bid if side == "BUY" else tick.ask

    payload = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": symbol,
        "volume": float(volume),
        "type": order_type,
        "position": int(ticket),
        "price": float(price),
        "deviation": int(deviation),
        "magic": int(magic),
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_FOK,
    }

    if comment:
        payload["comment"] = str(comment)

    return mt5.order_send(payload)


def cancel_order(
    ticket: int, symbol: str, comment: Optional[str] = None
) -> mt5.TradeResult:
    """Cancel a pending order via ``TRADE_ACTION_REMOVE``."""

    payload = {
        "action": mt5.TRADE_ACTION_REMOVE,
        "order": int(ticket),
        "symbol": symbol,
    }

    if comment:
        payload["comment"] = str(comment)

    return mt5.order_send(payload)
