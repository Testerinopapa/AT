"""
MACD (Moving Average Convergence Divergence) Strategy

Generates signals based on MACD line and signal line crossovers.
"""

import MetaTrader5 as mt5
import numpy as np
from .base_strategy import BaseStrategy


class MACDStrategy(BaseStrategy):
    """
    MACD Strategy based on MACD and signal line crossovers.
    
    BUY: When MACD line crosses above signal line (bullish crossover)
    SELL: When MACD line crosses below signal line (bearish crossover)
    NONE: No crossover detected
    """
    
    def __init__(self, params: dict = None):
        """
        Initialize MACD Strategy.
        
        Args:
            params: Strategy parameters
                - timeframe: MT5 timeframe (default: M15)
                - fast_period: Fast EMA period (default: 12)
                - slow_period: Slow EMA period (default: 26)
                - signal_period: Signal line period (default: 9)
        """
        default_params = {
            "timeframe": mt5.TIMEFRAME_M15,
            "fast_period": 12,
            "slow_period": 26,
            "signal_period": 9
        }
        
        if params:
            default_params.update(params)
        
        super().__init__("MACDStrategy", default_params)
    
    def calculate_ema(self, data: np.ndarray, period: int) -> np.ndarray:
        """
        Calculate Exponential Moving Average.
        
        Args:
            data: Price data array
            period: EMA period
            
        Returns:
            numpy array of EMA values
        """
        ema = np.zeros_like(data, dtype=float)
        multiplier = 2 / (period + 1)
        
        # First EMA is SMA
        ema[period - 1] = np.mean(data[:period])
        
        # Calculate EMA for remaining values
        for i in range(period, len(data)):
            ema[i] = (data[i] - ema[i-1]) * multiplier + ema[i-1]
        
        return ema
    
    def calculate_macd(self, prices: np.ndarray, fast_period: int, slow_period: int, signal_period: int):
        """
        Calculate MACD, Signal line, and Histogram.
        
        Args:
            prices: Price data array
            fast_period: Fast EMA period
            slow_period: Slow EMA period
            signal_period: Signal line period
            
        Returns:
            tuple: (macd_line, signal_line, histogram)
        """
        # Calculate fast and slow EMAs
        fast_ema = self.calculate_ema(prices, fast_period)
        slow_ema = self.calculate_ema(prices, slow_period)
        
        # MACD line = fast EMA - slow EMA
        macd_line = fast_ema - slow_ema
        
        # Signal line = EMA of MACD line
        # Start from slow_period since that's when MACD becomes valid
        valid_macd = macd_line[slow_period - 1:]
        signal_line_partial = self.calculate_ema(valid_macd, signal_period)
        
        # Pad signal line to match macd_line length
        signal_line = np.zeros_like(macd_line)
        signal_line[slow_period - 1:] = signal_line_partial
        
        # Histogram = MACD - Signal
        histogram = macd_line - signal_line
        
        return macd_line, signal_line, histogram
    
    def generate_signal(self, symbol: str) -> str:
        """
        Generate trading signal based on MACD crossover.
        
        Args:
            symbol: Trading symbol
            
        Returns:
            str: "BUY", "SELL", or "NONE"
        """
        timeframe = self.params.get("timeframe", mt5.TIMEFRAME_M15)
        fast_period = self.params.get("fast_period", 12)
        slow_period = self.params.get("slow_period", 26)
        signal_period = self.params.get("signal_period", 9)
        
        # Need enough data for MACD calculation
        lookback = slow_period + signal_period + 20
        
        # Get market data
        rates = self.get_market_data(symbol, timeframe, lookback)
        
        if rates is None:
            return "NONE"
        
        # Extract close prices
        closes = rates['close']
        
        # Calculate MACD
        macd_line, signal_line, histogram = self.calculate_macd(
            closes, fast_period, slow_period, signal_period
        )
        
        # Get valid indices (where signal line is calculated)
        valid_start = slow_period + signal_period - 2
        
        if len(macd_line) < valid_start + 2:
            print(f"[{self.name}] Insufficient MACD data")
            return "NONE"
        
        # Get current and previous values
        current_macd = macd_line[-1]
        current_signal = signal_line[-1]
        prev_macd = macd_line[-2]
        prev_signal = signal_line[-2]
        
        current_hist = histogram[-1]
        prev_hist = histogram[-2]
        
        # Check for bullish crossover (MACD crosses above signal)
        if prev_macd <= prev_signal and current_macd > current_signal:
            print(f"[{self.name}] Bullish crossover detected (MACD: {current_macd:.5f}, Signal: {current_signal:.5f}) → BUY signal")
            return "BUY"
        
        # Check for bearish crossover (MACD crosses below signal)
        elif prev_macd >= prev_signal and current_macd < current_signal:
            print(f"[{self.name}] Bearish crossover detected (MACD: {current_macd:.5f}, Signal: {current_signal:.5f}) → SELL signal")
            return "SELL"
        
        # Additional signal: histogram changing direction
        elif prev_hist < 0 and current_hist > 0:
            print(f"[{self.name}] Histogram turned positive (momentum shift) → BUY signal")
            return "BUY"
        
        elif prev_hist > 0 and current_hist < 0:
            print(f"[{self.name}] Histogram turned negative (momentum shift) → SELL signal")
            return "SELL"
        
        else:
            # No crossover
            position = "above" if current_macd > current_signal else "below"
            print(f"[{self.name}] No crossover (MACD {position} signal, hist: {current_hist:.5f}) → NONE")
            return "NONE"

