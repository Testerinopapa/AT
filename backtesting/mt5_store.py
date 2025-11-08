"""Backtrader store integration for MetaTrader 5.

This module wires the MetaTrader5 Python API into Backtrader's store/broker
abstractions.  MetaQuotes impose a few practical limits that callers should keep
in mind:

* ``mt5.copy_rates_range``/``copy_rates_from`` return at most 100 000 bars per
  request.  Larger history windows must be paged manually.
* Tick retrieval helpers (``copy_ticks_from``/``copy_ticks_range``) are capped at
  2 000 ticks per call and always require a logged-in terminal session.
* All data calls and trading operations depend on a running terminal that is
  already authenticated with the target broker account via ``mt5.initialize``.
  ``MT5Store`` only wraps those lifecycle steps – it cannot perform unattended
  logins if platform security dialogs are pending.
"""
from __future__ import annotations

from collections import deque
from datetime import datetime, timedelta, timezone
from typing import Any, Deque, Iterable, Optional

import MetaTrader5 as mt5
import backtrader as bt

from mt5_helpers import OrderRequest, cancel_order, close_position_by_ticket, send_market_order


def _as_naive(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt
    return dt.astimezone(timezone.utc).replace(tzinfo=None)


def _localize(timestamp: float, tzinfo: Optional[timezone]) -> datetime:
    base = datetime.fromtimestamp(timestamp, tz=timezone.utc)
    if tzinfo is None:
        return base.replace(tzinfo=None)
    return base.astimezone(tzinfo).replace(tzinfo=None)


def _get_field(record: Any, name: str, default: Any = None) -> Any:
    if isinstance(record, dict):
        return record.get(name, default)
    if hasattr(record, name):
        return getattr(record, name)
    try:
        return record[name]
    except (KeyError, IndexError, TypeError, ValueError):
        return default


class MT5Store(bt.stores.Store):
    """Store providing data and broker instances backed by MetaTrader 5."""

    params = (
        ("path", None),
        ("login", None),
        ("password", None),
        ("server", None),
        ("timeout", 60),
        ("reconnect", True),
        ("reconnect_delay", 5.0),
        ("max_bars_per_request", 100_000),
        ("max_ticks_per_request", 2_000),
    )

    BrokerCls = None  # Assigned after class definitions
    DataCls = None

    def __init__(self, **kwargs):
        super().__init__()
        for key, value in kwargs.items():
            if hasattr(self.p, key):
                setattr(self.p, key, value)

        self._broker = None
        self._connected = False

    # Connection management -------------------------------------------------
    def start(self):
        super().start()
        self.connect()

    def stop(self):
        self.disconnect()
        super().stop()

    def connect(self):
        if self._connected:
            return True

        initialize_kwargs = {}
        if self.p.path:
            initialize_kwargs["path"] = self.p.path
        if self.p.timeout:
            initialize_kwargs["timeout"] = int(self.p.timeout)

        if not mt5.initialize(**initialize_kwargs):
            code, message = mt5.last_error()
            raise RuntimeError(f"MetaTrader5 initialize failed: {code} {message}")

        if self.p.login is not None:
            authorized = mt5.login(self.p.login, password=self.p.password, server=self.p.server)
            if not authorized:
                code, message = mt5.last_error()
                mt5.shutdown()
                raise RuntimeError(f"MetaTrader5 login failed: {code} {message}")

        self._connected = True
        return True

    def disconnect(self):
        if not self._connected:
            return
        mt5.shutdown()
        self._connected = False

    def isconnected(self):
        return self._connected

    # Factory helpers ------------------------------------------------------
    def getdata(self, dataname, **kwargs):
        params = dict(kwargs)
        params.setdefault("dataname", dataname)
        params.setdefault("max_bars_per_request", self.p.max_bars_per_request)
        params.setdefault("max_ticks_per_request", self.p.max_ticks_per_request)
        return self.DataCls(store=self, **params)

    def getbroker(self, **kwargs):
        if self._broker is None:
            broker_kwargs = dict(kwargs)
            self._broker = self.BrokerCls(store=self, **broker_kwargs)
        return self._broker


class MT5Data(bt.feeds.DataBase):
    """Backtrader data feed driven by MetaTrader5 copy functions."""

    params = (
        ("dataname", None),
        ("mt5_timeframe", mt5.TIMEFRAME_M1),
        ("compression", 1),
        ("fromdate", None),
        ("todate", None),
        ("timezone", None),
        ("max_bars_per_request", 100_000),
        ("max_ticks_per_request", 2_000),
        ("refresh_bars", 500),
        ("refresh_ticks", 500),
        ("backfill", True),
        ("backfill_start", True),
    )

    datafields = bt.feeds.PandasData.datafields

    def __init__(self, store: MT5Store, **kwargs):
        super().__init__(**kwargs)
        self.store = store
        self._buffer: Deque[tuple] = deque()
        self._last_bar_time: Optional[float] = None
        self._last_tick_time: Optional[float] = None
        self._timeframe_is_tick = self.p.timeframe == bt.TimeFrame.Ticks or getattr(mt5, "TIMEFRAME_TICK", None) == self.p.mt5_timeframe
        self._tz = self.p.timezone

    def start(self):
        super().start()
        self.store.start()
        self._load_initial_history()

    def stop(self):
        self._buffer.clear()
        super().stop()

    def _load_initial_history(self):
        now = datetime.utcnow()
        span = timedelta(days=1 if self._timeframe_is_tick else 30)
        start = _as_naive(self.p.fromdate) or (now - span)
        end = _as_naive(self.p.todate) or now

        if self._timeframe_is_tick:
            ticks = mt5.copy_ticks_range(
                self.p.dataname,
                start,
                end,
                mt5.COPY_TICKS_ALL,
            )
            if ticks is not None:
                self._push_ticks(ticks)
        else:
            rates = mt5.copy_rates_range(
                self.p.dataname,
                self.p.mt5_timeframe,
                start,
                end,
            )
            if rates is not None:
                self._push_rates(rates)

    def _push_rates(self, rates: Iterable):
        for rate in rates:
            timestamp = float(_get_field(rate, "time", 0.0))
            if self._last_bar_time is not None and timestamp <= self._last_bar_time:
                continue

            dt = _localize(timestamp, self._tz)
            volume = float(
                _get_field(
                    rate,
                    "tick_volume",
                    _get_field(rate, "real_volume", _get_field(rate, "volume", 0.0)),
                )
            )
            bar = (
                dt,
                float(_get_field(rate, "open", 0.0)),
                float(_get_field(rate, "high", 0.0)),
                float(_get_field(rate, "low", 0.0)),
                float(_get_field(rate, "close", 0.0)),
                volume,
            )
            self._buffer.append(bar)
            self._last_bar_time = timestamp

    def _push_ticks(self, ticks: Iterable):
        for tick in ticks:
            timestamp = float(
                _get_field(tick, "time_msc", _get_field(tick, "time", 0.0))
            )
            if timestamp > 1e12:  # milliseconds
                timestamp /= 1000.0

            if self._last_tick_time is not None and timestamp <= self._last_tick_time:
                continue

            dt = _localize(timestamp, self._tz)
            bid = float(_get_field(tick, "bid", 0.0))
            ask = float(_get_field(tick, "ask", 0.0))
            last = float(_get_field(tick, "last", 0.0))
            price_candidates = [p for p in (last, bid, ask) if p]
            price = price_candidates[0] if price_candidates else 0.0
            volume = float(
                _get_field(tick, "volume_real", _get_field(tick, "volume", 0.0))
            )

            bar = (dt, price, price, price, price, volume)
            self._buffer.append(bar)
            self._last_tick_time = timestamp

    def _fetch_updates(self):
        if self._timeframe_is_tick:
            self._fetch_tick_updates()
        else:
            self._fetch_bar_updates()

    def _fetch_bar_updates(self):
        if self._last_bar_time is None:
            since = datetime.utcnow() - timedelta(days=1 if self._timeframe_is_tick else 30)
        else:
            since = datetime.fromtimestamp(self._last_bar_time, tz=timezone.utc)

        since = _as_naive(since)

        count = max(1, min(int(self.p.refresh_bars), int(self.p.max_bars_per_request)))
        rates = mt5.copy_rates_from(
            self.p.dataname,
            self.p.mt5_timeframe,
            since,
            count,
        )
        if rates is not None:
            self._push_rates(rates)

    def _fetch_tick_updates(self):
        if self._last_tick_time is None:
            since = datetime.utcnow() - timedelta(minutes=5)
        else:
            since = datetime.fromtimestamp(self._last_tick_time, tz=timezone.utc)
        since = _as_naive(since)
        now = _as_naive(datetime.utcnow())
        ticks = mt5.copy_ticks_range(
            self.p.dataname,
            since,
            now,
            mt5.COPY_TICKS_ALL,
        )
        if ticks is not None:
            self._push_ticks(ticks)

    def _load(self):
        if not self._buffer:
            self._fetch_updates()
            if not self._buffer:
                return False

        dt, o, h, l, c, v = self._buffer.popleft()
        self.lines.datetime[0] = bt.date2num(dt)
        self.lines.open[0] = o
        self.lines.high[0] = h
        self.lines.low[0] = l
        self.lines.close[0] = c
        self.lines.volume[0] = v
        self.lines.openinterest[0] = 0.0
        return True


class MT5Broker(bt.brokers.BrokerBase):
    """Thin Backtrader broker adapter that proxies orders to MetaTrader 5."""

    params = (
        ("deviation", 20),
        ("magic", 0),
        ("comment_prefix", "Backtrader"),
    )

    def __init__(self, store: MT5Store, **kwargs):
        super().__init__()
        self.store = store
        for key, value in kwargs.items():
            if hasattr(self.p, key):
                setattr(self.p, key, value)
        self._orders = {}

    def start(self):
        super().start()
        self.store.start()

    def stop(self):
        super().stop()

    def is_live(self):
        return True

    def getcash(self):
        info = mt5.account_info()
        return float(info.balance) if info is not None else 0.0

    def getvalue(self, datas=None):
        info = mt5.account_info()
        if info is None:
            return self.getcash()
        return float(info.equity)

    def submit(self, order):
        if not self.store.isconnected():
            self.store.start()

        order.submit(self)
        self.notify(order)

        size = order.created.size
        if not size:
            order.reject(self)
            self.notify(order)
            return order

        dataname = getattr(order.data.p, "dataname", None)
        if dataname is None:
            order.reject(self)
            self.notify(order)
            return order

        action = "BUY" if size > 0 else "SELL"
        volume = abs(size)

        try:
            tick = mt5.symbol_info_tick(dataname)
            price = None
            if tick is not None:
                price = tick.ask if action == "BUY" else tick.bid

            request = OrderRequest(
                symbol=dataname,
                action=action,
                volume=volume,
                price=price,
                deviation=self.p.deviation,
                magic=self.p.magic,
                comment=f"{self.p.comment_prefix} #{order.ref}",
            )
            result = send_market_order(request)
        except Exception:
            order.reject(self)
            self.notify(order)
            return order

        if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
            order.reject(self)
            self.notify(order)
            return order

        order.accept(self)
        self.notify(order)

        order.executed.price = result.price
        order.executed.size = size
        order.executed.value = result.price * volume
        order.executed.comm = getattr(result, "commission", 0.0)
        order.executed.pnl = getattr(result, "profit", 0.0)
        order.executed.remsize = 0
        order.completed()
        self.notify(order)

        if result.order:
            self._orders[order.ref] = result.order

        return order

    def cancel(self, order):
        ticket = self._orders.pop(order.ref, None)
        dataname = getattr(order.data.p, "dataname", None)
        if ticket is not None and dataname is not None:
            cancel_order(ticket=ticket, symbol=dataname, comment=f"Cancel #{order.ref}")

        order.cancel()
        self.notify(order)
        return order

    def close(self, position):
        if position is None:
            return
        try:
            dataname = getattr(getattr(position.data, "p", None), "dataname", None)
            if dataname is None:
                return
            close_position_by_ticket(
                ticket=position.ticket,
                symbol=dataname,
                volume=abs(position.size),
                side="BUY" if position.size > 0 else "SELL",
                deviation=self.p.deviation,
                magic=self.p.magic,
                comment="Backtrader close",
            )
        except Exception:
            return


MT5Store.BrokerCls = MT5Broker
MT5Store.DataCls = MT5Data

__all__ = ["MT5Store", "MT5Data", "MT5Broker"]
