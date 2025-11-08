"""Reusable order execution helpers for MetaTrader 5 workflows."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Callable, Optional, Sequence

import MetaTrader5 as mt5

from mt5_helpers import OrderRequest, close_position_by_ticket, send_market_order


def get_open_positions(
    symbol: Optional[str] = None, *, mt5_module=mt5
) -> Sequence[Any]:
    """Return currently open MetaTrader 5 positions."""

    positions = (
        mt5_module.positions_get(symbol=symbol)
        if symbol
        else mt5_module.positions_get()
    )
    return positions if positions is not None else []


def has_open_position(symbol: str, *, mt5_module=mt5) -> bool:
    """Determine whether at least one open position exists for ``symbol``."""

    return len(get_open_positions(symbol, mt5_module=mt5_module)) > 0


def can_open_new_trade(
    *,
    max_concurrent_trades: int,
    positions: Optional[Sequence[Any]] = None,
    get_positions: Optional[Callable[[], Sequence[Any]]] = None,
) -> bool:
    """Check if a new trade can be opened respecting concurrency limits."""

    if positions is None:
        if get_positions is None:
            positions = get_open_positions()
        else:
            positions = get_positions()

    return len(positions or []) < max_concurrent_trades


def log_trade(
    *,
    symbol: str,
    action: str,
    result: Any,
    volume: float,
    price: float,
    sl: float,
    tp: float,
    strategy: str,
    trade_logger: Optional[Any] = None,
    log_path: Optional[str] = None,
) -> None:
    """Persist trade execution details via the configured sinks."""

    if trade_logger is not None:
        trade_logger.log_trade_open(
            symbol=symbol,
            action=action,
            result=result,
            volume=volume,
            entry_price=price,
            sl=sl,
            tp=tp,
            strategy=strategy,
        )

    if log_path:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        try:
            with open(log_path, "a") as handle:
                handle.write(
                    f"{timestamp} | {action:<12} | {result.order:<12} | "
                    f"Price: {price:.5f} | SL: {sl:.5f} | TP: {tp:.5f} | "
                    f"Retcode: {result.retcode}\n"
                )
        except OSError:
            print(f"⚠️  Unable to append trade log entry to {log_path}.")


def execute_trade(
    symbol: str,
    action: str,
    *,
    risk_manager: Any,
    trade_logger: Optional[Any],
    strategy_manager: Optional[Any],
    deviation: int,
    log_path: Optional[str],
    default_volume: float,
    config: dict,
    magic: int = 0,
    comment_prefix: str = "",
    order_sender: Callable[[OrderRequest], Any] = send_market_order,
    order_request_factory: Callable[..., OrderRequest] = OrderRequest,
    mt5_module=mt5,
) -> bool:
    """Execute a market order using shared risk management helpers."""

    can_trade, reason = risk_manager.can_trade() if risk_manager else (True, "OK")
    if not can_trade:
        print(f"🚫 Trading disabled: {reason}")
        return False

    print(f"📤 Sending {action} trade request...")

    tick = mt5_module.symbol_info_tick(symbol)
    if tick is None:
        print(f"❌ Could not get tick data for {symbol}")
        return False

    price = tick.ask if action == "BUY" else tick.bid

    sl = tp = None
    if risk_manager:
        sl, tp = risk_manager.calculate_sl_tp(symbol, action, price)
    else:
        print("⚠️  Risk manager unavailable; SL/TP not configured.")
        sl = price
        tp = price

    symbol_info = mt5_module.symbol_info(symbol)
    if symbol_info is None:
        print(f"❌ Could not get symbol info for {symbol}")
        return False

    point = symbol_info.point
    sl_distance_pips = abs(price - sl) / (point * 10) if sl is not None else 0

    dynamic_cfg = (config or {}).get("risk_management", {}) if isinstance(config, dict) else {}
    if dynamic_cfg.get("enable_dynamic_lot_sizing", False) and risk_manager:
        volume = risk_manager.calculate_lot_size(symbol, sl_distance_pips)
        print(
            f"💰 Dynamic lot size: {volume} "
            f"(Risk: {risk_manager.risk_percentage}%, SL: {sl_distance_pips:.1f} pips)"
        )
    else:
        volume = default_volume
        print(f"💰 Fixed lot size: {volume}")

    if risk_manager:
        is_valid, validation_reason = risk_manager.validate_trade(symbol, action, volume)
        if not is_valid:
            print(f"🚫 Trade validation failed: {validation_reason}")
            return False

    order_request = order_request_factory(
        symbol=symbol,
        action=action,
        volume=volume,
        price=price,
        sl=sl,
        tp=tp,
        deviation=deviation,
        magic=magic,
        comment=f"{comment_prefix} {action}".strip(),
    )

    try:
        result = order_sender(order_request)
    except RuntimeError as exc:
        print(f"❌ Order send failed: {exc}")
        return False

    if result is None:
        print("❌ Order send failed - no result returned")
        return False

    print(f"\nTrade Result: {result}")

    if result.retcode == mt5_module.TRADE_RETCODE_DONE:
        print(f"\n✅ {action} executed successfully!")
        print(f"   Ticket: {result.order}")
        print(f"   Price:  {result.price}")
        print(f"   SL:     {sl}")
        print(f"   TP:     {tp}")

        strategy_label = "UNKNOWN"
        if strategy_manager and hasattr(strategy_manager, "method"):
            strategy_label = str(strategy_manager.method).upper()

        log_trade(
            symbol=symbol,
            action=action,
            result=result,
            volume=volume,
            price=price,
            sl=sl if sl is not None else 0.0,
            tp=tp if tp is not None else 0.0,
            strategy=strategy_label,
            trade_logger=trade_logger,
            log_path=log_path,
        )
        return True

    print(f"\n❌ {action} failed! Code {result.retcode}: {result.comment}")
    log_trade(
        symbol=symbol,
        action=f"{action}_FAILED",
        result=result,
        volume=volume,
        price=price,
        sl=sl if sl is not None else 0.0,
        tp=tp if tp is not None else 0.0,
        strategy="FAILED",
        trade_logger=trade_logger,
        log_path=log_path,
    )
    return False


def close_position(
    position: Any,
    *,
    trade_logger: Optional[Any],
    risk_manager: Optional[Any],
    deviation: int,
    magic: int = 234000,
    comment: str = "python script close",
    closer: Callable[..., Any] = close_position_by_ticket,
    mt5_module=mt5,
) -> bool:
    """Close an existing MetaTrader 5 position and propagate bookkeeping."""

    try:
        result = closer(
            ticket=position.ticket,
            symbol=position.symbol,
            volume=position.volume,
            side="BUY" if position.type == mt5_module.ORDER_TYPE_BUY else "SELL",
            deviation=deviation,
            magic=magic,
            comment=comment,
        )
    except RuntimeError as exc:
        print(f"❌ Failed to close position #{position.ticket}: {exc}")
        return False

    if result.retcode != mt5_module.TRADE_RETCODE_DONE:
        print(f"❌ Failed to close position #{position.ticket} | Code: {result.retcode}")
        return False

    profit = getattr(position, "profit", 0.0)
    commission = getattr(position, "commission", 0.0)
    swap = getattr(position, "swap", 0.0)
    close_price = getattr(result, "price", None)

    print(f"✅ Position #{position.ticket} closed | Profit: {profit:.2f}")

    if trade_logger is not None:
        trade_logger.log_trade_close(
            ticket=position.ticket,
            exit_price=close_price if close_price is not None else 0.0,
            profit=profit,
            commission=commission,
            swap=swap,
        )

    if risk_manager and hasattr(risk_manager, "update_daily_pnl"):
        risk_manager.update_daily_pnl(profit)

    return True


__all__ = [
    "can_open_new_trade",
    "close_position",
    "execute_trade",
    "get_open_positions",
    "has_open_position",
    "log_trade",
]
