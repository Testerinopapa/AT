import backtrader as bt
import numpy as np

class DynamicExecution:
    """
    Strategy-level helper that simulates realistic order execution:
      • Volatility-based slippage
      • Latency delay
      • Liquidity-based partial fills
    Use by wrapping your buy/sell calls with get_exec_price().
    """

    def __init__(self, base_slippage=0.00005, vol_factor=1.5,
                 latency_ms=100, max_fraction_filled=0.95):
        self.base_slippage = base_slippage
        self.vol_factor = vol_factor
        self.latency_ms = latency_ms
        self.max_fraction_filled = max_fraction_filled

    def get_exec_price(self, data, signal):
        """Return adjusted execution price."""
        try:
            # Basic volatility measure (range ratio)
            bar_vol = (data.high[0] - data.low[0]) / data.close[0]
            dynamic_slip = self.base_slippage * (
                1 + np.random.uniform(0.5, self.vol_factor) * bar_vol * 1000
            )

            price = data.close[0]
            if signal == 'BUY':
                price += dynamic_slip
            elif signal == 'SELL':
                price -= dynamic_slip

            # Simulated latency (small random delay)
            delay_bars = int(np.random.normal(self.latency_ms / 1000 * 10, 1))
            delay_bars = max(0, min(delay_bars, 3))
            if len(data) > delay_bars:
                delayed_price = data.close[-delay_bars]
                price = (price + delayed_price) / 2

            # Random chance of non-fill due to liquidity
            filled = np.random.rand() < self.max_fraction_filled
            if not filled:
                return None  # skip trade

            return price

        except Exception as e:
            print(f"⚠️ DynamicExecution error: {e}")
            return data.close[0]
