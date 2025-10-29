"""
Simple Momentum Strategy

Generates signals based on comparing the last two candle closes.
"""

import MetaTrader5 as mt5
from .base_strategy import BaseStrategy


class SimpleStrategy(BaseStrategy):
    """
    Simple momentum strategy based on last two candle closes.
    
    BUY: When last close > previous close (upward momentum)
    SELL: When last close < previous close (downward momentum)
    NONE: When last close == previous close (no momentum)
    """
    
    def __init__(self, params: dict = None):
        """
        Initialize Simple Strategy.
        
        Args:
            params: Strategy parameters
                - timeframe: MT5 timeframe (default: M1)
                - lookback: Number of candles to fetch (default: 20)
        """
        default_params = {
            "timeframe": mt5.TIMEFRAME_M1,
            "lookback": 20
        }
        
        if params:
            default_params.update(params)
        
        super().__init__("SimpleStrategy", default_params)
    
    def generate_signal(self, symbol: str) -> str:
        """
        Generate trading signal based on momentum.
        
        Args:
            symbol: Trading symbol
            
        Returns:
            str: "BUY", "SELL", or "NONE"
        """
        timeframe = self.params.get("timeframe", mt5.TIMEFRAME_M1)
        lookback = self.params.get("lookback", 20)
        
        # Get market data
        rates = self.get_market_data(symbol, timeframe, lookback)
        
        if rates is None or len(rates) < 2:
            return "NONE"
        
        # Compare last two closes
        last_close = rates[-1]['close']
        prev_close = rates[-2]['close']
        
        if last_close > prev_close:
            print(f"[{self.name}] Upward momentum detected → BUY signal")
            return "BUY"
        elif last_close < prev_close:
            print(f"[{self.name}] Downward momentum detected → SELL signal")
            return "SELL"
        else:
            print(f"[{self.name}] No clear momentum → NONE")
            return "NONE"

