"""
Base Strategy Class

Abstract base class for all trading strategies.
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, Optional
import MetaTrader5 as mt5


class BaseStrategy(ABC):
    """
    Abstract base class for trading strategies.
    
    All strategies must implement the generate_signal method.
    """
    
    def __init__(self, name: str, params: Optional[Dict[str, Any]] = None):
        """
        Initialize the strategy.
        
        Args:
            name: Strategy name
            params: Strategy parameters (optional)
        """
        self.name = name
        self.params = params or {}
        self.enabled = True
        self.weight = 1.0  # For weighted strategy combinations
    
    @abstractmethod
    def generate_signal(self, symbol: str) -> str:
        """
        Generate trading signal for the given symbol.
        
        Args:
            symbol: Trading symbol (e.g., "EURUSD")
            
        Returns:
            str: One of "BUY", "SELL", or "NONE"
        """
        pass
    
    def get_market_data(self, symbol: str, timeframe: int, count: int) -> Optional[Any]:
        """
        Fetch market data from MT5.
        
        Args:
            symbol: Trading symbol
            timeframe: MT5 timeframe constant
            count: Number of candles to fetch
            
        Returns:
            numpy array of OHLC data or None if failed
        """
        rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, count)
        
        if rates is None or len(rates) < count:
            print(f"[{self.name}] Insufficient data: got {len(rates) if rates is not None else 0}, needed {count}")
            return None
        
        return rates
    
    def enable(self):
        """Enable this strategy."""
        self.enabled = True
        print(f"[{self.name}] Strategy enabled")
    
    def disable(self):
        """Disable this strategy."""
        self.enabled = False
        print(f"[{self.name}] Strategy disabled")
    
    def set_weight(self, weight: float):
        """
        Set the weight for this strategy in combined signals.
        
        Args:
            weight: Weight value (typically 0.0 to 1.0)
        """
        self.weight = weight
        print(f"[{self.name}] Weight set to {weight}")
    
    def get_info(self) -> Dict[str, Any]:
        """
        Get strategy information.
        
        Returns:
            dict: Strategy information
        """
        return {
            "name": self.name,
            "enabled": self.enabled,
            "weight": self.weight,
            "params": self.params
        }
    
    def __str__(self) -> str:
        """String representation of the strategy."""
        status = "enabled" if self.enabled else "disabled"
        return f"{self.name} (weight: {self.weight}, {status})"
    
    def __repr__(self) -> str:
        """Detailed representation of the strategy."""
        return f"<{self.__class__.__name__}: {self.name}, enabled={self.enabled}, weight={self.weight}>"

