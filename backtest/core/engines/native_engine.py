# core/engines/native_engine.py
import pandas as pd
import numpy as np
from typing import Dict, List, Optional
from dataclasses import dataclass

@dataclass
class NativeEngineConfig:
    symbol: str = "EURUSD"
    initial_balance: float = 10000
    strategy_name: str = "trend_following"
    strategy_params: Dict = None
    
    def __post_init__(self):
        if self.strategy_params is None:
            self.strategy_params = {}

class NativeEngine:
    """
    Your custom backtesting engine - lightweight and fast
    Replaces the original BacktestEngine with cleaner architecture
    """
    
    def __init__(self, config: NativeEngineConfig):
        self.config = config
        self.portfolio = None  # Will be set by portfolio manager
        self.execution = None  # Will be set by execution manager
        self.strategy = None   # Will be set by strategy manager
        
    def initialize(self, strategy_manager, portfolio_manager, execution_manager):
        """Inject dependencies"""
        self.strategy = strategy_manager
        self.portfolio = portfolio_manager
        self.execution = execution_manager
        
    def run(self, df: pd.DataFrame) -> Dict:
        """Main backtest loop using clean architecture"""
        results = {
            'equity_curve': [],
            'trades': [],
            'signals': []
        }
        
        print(f"🚀 Running native engine with {self.config.strategy_name}")
        
        for i in range(50, len(df)):
            window = df.iloc[i-50:i]
            current_bar = df.iloc[i]
            
            # 1. Get signal from strategy
            signal = self.strategy.get_signal(window)
            
            # 2. Portfolio manages position and risk
            position_action = self.portfolio.evaluate_position(
                signal, current_bar, self.strategy
            )
            
            # 3. Execution handles order placement
            if position_action['should_trade']:
                trade_result = self.execution.execute_trade(
                    position_action, current_bar
                )
                if trade_result:
                    results['trades'].append(trade_result)
            
            # 4. Update equity curve
            results['equity_curve'].append(
                self.portfolio.get_current_equity()
            )
            results['signals'].append(signal)
        
        return results