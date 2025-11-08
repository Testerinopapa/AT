# backtest/sizers.py
import backtrader as bt
import pandas_ta as ta
import numpy as np


class PercentSizer(bt.Sizer):
    """Backtrader built-in – just a thin wrapper for clarity."""
    params = (('percents', 10),)          # 10 % of cash per trade

    def _getsizing(self, comminfo, cash, data, isbuy):
        return int((cash * self.p.percents / 100) / data.close[0])


class RiskPercentSizer(bt.Sizer):
    """
    Size = (risk_% of portfolio) / (stop-loss distance in price units)
    Stop distance is taken from the strategy (self.strategy.sl_price).
    """
    params = (
        ('risk_percent', 2.0),   # 2 % of equity per trade
        ('default_stop_pips', 0.001),
    )

    def _getsizing(self, comminfo, cash, data, isbuy):
        strat = self.strategy
        portfolio = strat.broker.getvalue()
        risk_cash = portfolio * (self.p.risk_percent / 100)

        # Prefer stop that the strategy already calculated
        stop_price = getattr(strat, 'sl_price', None)
        if stop_price is None:
            price = data.close[0]
            stop_price = price - self.p.default_stop_pips if isbuy else price + self.p.default_stop_pips

        risk_per_unit = abs(data.close[0] - stop_price)
        if risk_per_unit == 0:
            return 0
        size = int(risk_cash / risk_per_unit)
        return max(size, 1)          # at least 1 unit


class ATRVolatilitySizer(bt.Sizer):
    """
    Size inversely to ATR → constant risk in volatility units.
    risk_percent = % of equity you are willing to lose on a 1-ATR move.
    """
    params = (
        ('risk_percent', 2.0),
        ('atr_period', 14),
        ('atr_multiplier', 1.0),   # 1 × ATR stop distance
    )

    def __init__(self):
        self.atr = bt.indicators.ATR(self.datas[0], period=self.p.atr_period)

    def _getsizing(self, comminfo, cash, data, isbuy):
        portfolio = self.strategy.broker.getvalue()
        risk_cash = portfolio * (self.p.risk_percent / 100)

        atr = self.atr[0]
        if np.isnan(atr) or atr == 0:
            return 0

        stop_distance = atr * self.p.atr_multiplier
        size = int(risk_cash / stop_distance)
        return max(size, 1)


class KellySizer(bt.Sizer):
    """
    Very light Kelly – you feed win-rate & avg win/loss from a previous run.
    Conservative: use only `kelly_fraction` of the full Kelly.
    """
    params = (
        ('win_rate', 0.55),
        ('avg_win', 1.5),          # avg win / avg loss
        ('kelly_fraction', 0.25),  # 25 % of full Kelly
    )

    def _getsizing(self, comminfo, cash, data, isbuy):
        p, q = self.p.win_rate, 1 - self.p.win_rate
        r = self.p.avg_win
        full_kelly = (p * r - q) / r
        kelly = full_kelly * self.p.kelly_fraction
        kelly = max(kelly, 0)      # never negative
        size = int((cash * kelly) / data.close[0])
        return max(size, 1)