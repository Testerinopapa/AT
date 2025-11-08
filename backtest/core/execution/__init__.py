# backtest/core/execution/__init__.py
from .order_manager import OrderManager, TradeExecutor
from .slippage_simulator import SlippageSimulator

__all__ = ['OrderManager', 'TradeExecutor', 'SlippageSimulator']