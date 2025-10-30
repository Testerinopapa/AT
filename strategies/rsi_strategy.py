"""
RSI (Relative Strength Index) Strategy

Generates signals based on RSI overbought/oversold conditions.
"""

import MetaTrader5 as mt5
import numpy as np
from .base_strategy import BaseStrategy


class RSIStrategy(BaseStrategy):
    """
    RSI Strategy based on overbought/oversold levels.
    
    BUY: When RSI crosses above oversold level (default: 30)
    SELL: When RSI crosses below overbought level (default: 70)
    NONE: RSI in neutral zone
    """
    
    def __init__(self, params: dict = None):
        """
        Initialize RSI Strategy.
        
        Args:
            params: Strategy parameters
                - timeframe: MT5 timeframe (default: M5)
                - period: RSI period (default: 14)
                - oversold: Oversold threshold (default: 30)
                - overbought: Overbought threshold (default: 70)
        """
        default_params = {
            "timeframe": mt5.TIMEFRAME_M5,
            "period": 14,
            "oversold": 30,
            "overbought": 70
        }
        
        if params:
            default_params.update(params)
        
        super().__init__("RSIStrategy", default_params)
    
    def calculate_rsi(self, prices: np.ndarray, period: int) -> np.ndarray:
        """
        Calculate RSI (Relative Strength Index).
        
        Args:
            prices: Price data array
            period: RSI period
            
        Returns:
            numpy array of RSI values
        """
        # Calculate price changes
        deltas = np.diff(prices)
        
        # Separate gains and losses
        gains = np.where(deltas > 0, deltas, 0)
        losses = np.where(deltas < 0, -deltas, 0)
        
        # Calculate average gains and losses
        avg_gains = np.zeros(len(gains))
        avg_losses = np.zeros(len(losses))
        
        # First average is simple mean
        avg_gains[period - 1] = np.mean(gains[:period])
        avg_losses[period - 1] = np.mean(losses[:period])
        
        # Subsequent values use smoothed average
        for i in range(period, len(gains)):
            avg_gains[i] = (avg_gains[i - 1] * (period - 1) + gains[i]) / period
            avg_losses[i] = (avg_losses[i - 1] * (period - 1) + losses[i]) / period
        
        # Calculate RS and RSI
        rs = np.zeros(len(avg_gains))
        rsi = np.zeros(len(avg_gains))
        
        for i in range(period - 1, len(avg_gains)):
            if avg_losses[i] == 0:
                rsi[i] = 100
            else:
                rs[i] = avg_gains[i] / avg_losses[i]
                rsi[i] = 100 - (100 / (1 + rs[i]))
        
        return rsi
    
    def generate_signal(self, symbol: str) -> str:
        """
        Generate trading signal based on RSI levels.
        
        Args:
            symbol: Trading symbol
            
        Returns:
            str: "BUY", "SELL", or "NONE"
        """
        timeframe = self.params.get("timeframe", mt5.TIMEFRAME_M5)
        period = self.params.get("period", 14)
        oversold = self.params.get("oversold", 30)
        overbought = self.params.get("overbought", 70)
        
        # Need period + extra for RSI calculation
        lookback = period + 20
        
        # Get market data
        rates = self.get_market_data(symbol, timeframe, lookback)
        
        if rates is None:
            return "NONE"
        
        # Extract close prices
        closes = rates['close']
        
        # Calculate RSI
        rsi_values = self.calculate_rsi(closes, period)
        
        if len(rsi_values) < 2:
            print(f"[{self.name}] Insufficient RSI data")
            return "NONE"
        
        # Get current and previous RSI
        current_rsi = rsi_values[-1]
        prev_rsi = rsi_values[-2]
        
        # Check for oversold bounce (BUY signal)
        if prev_rsi <= oversold and current_rsi > oversold:
            print(f"[{self.name}] RSI bounced from oversold ({current_rsi:.2f}) → BUY signal")
            return "BUY"
        
        # Check for overbought reversal (SELL signal)
        elif prev_rsi >= overbought and current_rsi < overbought:
            print(f"[{self.name}] RSI dropped from overbought ({current_rsi:.2f}) → SELL signal")
            return "SELL"
        
        # Additional signals: entering zones
        elif current_rsi <= oversold and prev_rsi > oversold:
            print(f"[{self.name}] RSI entering oversold zone ({current_rsi:.2f}) → BUY signal")
            return "BUY"
        
        elif current_rsi >= overbought and prev_rsi < overbought:
            print(f"[{self.name}] RSI entering overbought zone ({current_rsi:.2f}) → SELL signal")
            return "SELL"
        
        else:
            # Neutral zone
            zone = "oversold" if current_rsi < oversold else "overbought" if current_rsi > overbought else "neutral"
            print(f"[{self.name}] RSI in {zone} zone ({current_rsi:.2f}) → NONE")
            return "NONE"

