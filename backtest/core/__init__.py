# core/__init__.py
from .engines.native_engine import NativeEngine, NativeEngineConfig
from .engines.backtrader_adapter import BacktraderAdapter
from .portfolio.position_tracker import PositionTracker
from .portfolio.risk_manager import RiskManager
from .execution.order_manager import OrderManager, TradeExecutor
from .execution.slippage_simulator import SlippageSimulator

__all__ = [
    'NativeEngine',
    'NativeEngineConfig', 
    'BacktraderAdapter',
    'PositionTracker',
    'RiskManager',
    'OrderManager',
    'TradeExecutor',
    'SlippageSimulator'
]