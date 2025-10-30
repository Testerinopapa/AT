"""
Trading Strategies Package

This package contains various trading strategies for the TraderBot.
"""

from .base_strategy import BaseStrategy
from .simple_strategy import SimpleStrategy
from .ma_strategy import MAStrategy
from .rsi_strategy import RSIStrategy
from .macd_strategy import MACDStrategy
from .strategy_manager import StrategyManager

__all__ = [
    'BaseStrategy',
    'SimpleStrategy',
    'MAStrategy',
    'RSIStrategy',
    'MACDStrategy',
    'StrategyManager'
]

