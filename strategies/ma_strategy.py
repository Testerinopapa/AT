"""
Moving Average Crossover Strategy

Generates signals based on moving average crossovers.
"""

import MetaTrader5 as mt5
import numpy as np
from .base_strategy import BaseStrategy


class MAStrategy(BaseStrategy):
    """
    Moving Average Crossover Strategy.
    
    BUY: When fast MA crosses above slow MA (golden cross)
    SELL: When fast MA crosses below slow MA (death cross)
    NONE: No crossover detected
    """
    
    def __init__(self, params: dict = None):
        """
        Initialize MA Strategy.
        
        Args:
            params: Strategy parameters
                - timeframe: MT5 timeframe (default: M5)
                - fast_period: Fast MA period (default: 10)
                - slow_period: Slow MA period (default: 20)
                - ma_type: MA type - 'SMA' or 'EMA' (default: 'SMA')
        """
        default_params = {
            "timeframe": mt5.TIMEFRAME_M5,
            "fast_period": 10,
            "slow_period": 20,
            "ma_type": "SMA"
        }
        
        if params:
            default_params.update(params)
        
        super().__init__("MAStrategy", default_params)
    
    def calculate_sma(self, data: np.ndarray, period: int) -> np.ndarray:
        """
        Calculate Simple Moving Average.
        
        Args:
            data: Price data array
            period: MA period
            
        Returns:
            numpy array of SMA values
        """
        return np.convolve(data, np.ones(period)/period, mode='valid')
    
    def calculate_ema(self, data: np.ndarray, period: int) -> np.ndarray:
        """
        Calculate Exponential Moving Average.
        
        Args:
            data: Price data array
            period: MA period
            
        Returns:
            numpy array of EMA values
        """
        ema = np.zeros_like(data)
        multiplier = 2 / (period + 1)
        
        # First EMA is SMA
        ema[period - 1] = np.mean(data[:period])
        
        # Calculate EMA for remaining values
        for i in range(period, len(data)):
            ema[i] = (data[i] - ema[i-1]) * multiplier + ema[i-1]
        
        return ema[period-1:]
    
    def generate_signal(self, symbol: str) -> str:
        """
        Generate trading signal based on MA crossover.
        
        Args:
            symbol: Trading symbol
            
        Returns:
            str: "BUY", "SELL", or "NONE"
        """
        timeframe = self.params.get("timeframe", mt5.TIMEFRAME_M5)
        fast_period = self.params.get("fast_period", 10)
        slow_period = self.params.get("slow_period", 20)
        ma_type = self.params.get("ma_type", "SMA")
        
        # Need enough data for slow MA + 1 for crossover detection
        lookback = slow_period + 10
        
        # Get market data
        rates = self.get_market_data(symbol, timeframe, lookback)
        
        if rates is None:
            return "NONE"
        
        # Extract close prices
        closes = rates['close']
        
        # Calculate MAs
        if ma_type == "EMA":
            fast_ma = self.calculate_ema(closes, fast_period)
            slow_ma = self.calculate_ema(closes, slow_period)
        else:  # SMA
            fast_ma = self.calculate_sma(closes, fast_period)
            slow_ma = self.calculate_sma(closes, slow_period)
        
        # Align arrays (both should have same length after calculation)
        min_len = min(len(fast_ma), len(slow_ma))
        fast_ma = fast_ma[-min_len:]
        slow_ma = slow_ma[-min_len:]
        
        if len(fast_ma) < 2 or len(slow_ma) < 2:
            print(f"[{self.name}] Insufficient MA data")
            return "NONE"
        
        # Check for crossover
        # Current: fast_ma[-1] vs slow_ma[-1]
        # Previous: fast_ma[-2] vs slow_ma[-2]
        
        current_fast = fast_ma[-1]
        current_slow = slow_ma[-1]
        prev_fast = fast_ma[-2]
        prev_slow = slow_ma[-2]
        
        # Golden cross: fast crosses above slow
        if prev_fast <= prev_slow and current_fast > current_slow:
            print(f"[{self.name}] Golden cross detected (fast: {current_fast:.5f}, slow: {current_slow:.5f}) → BUY signal")
            return "BUY"
        
        # Death cross: fast crosses below slow
        elif prev_fast >= prev_slow and current_fast < current_slow:
            print(f"[{self.name}] Death cross detected (fast: {current_fast:.5f}, slow: {current_slow:.5f}) → SELL signal")
            return "SELL"
        
        else:
            # No crossover
            position = "above" if current_fast > current_slow else "below"
            print(f"[{self.name}] No crossover (fast {position} slow) → NONE")
            return "NONE"

