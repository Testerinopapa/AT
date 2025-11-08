# core/engines/backtrader_adapter.py
import pandas as pd
from typing import Dict, Any, Optional
import backtrader as bt

class BacktraderAdapter:
    """
    Thin adapter that bridges your system to Backtrader
    Replaces the complex backtrader_engine.py with clean interface
    """
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.cerebro = bt.Cerebro()
        
    def setup_backtrader(self, df: pd.DataFrame):
        """Prepare Backtrader with your data and strategy"""
        # Convert your DataFrame to Backtrader format
        df_bt = df.rename(columns={'time': 'datetime'})
        df_bt.set_index('datetime', inplace=True)
        
        data = bt.feeds.PandasData(dataname=df_bt)
        self.cerebro.adddata(data)
        
        # Add your strategy via adapter
        self.cerebro.addstrategy(
            BacktraderStrategyAdapter,
            strategy_name=self.config.get('strategy_name', 'trend_following'),
            strategy_params=self.config.get('strategy_params', {})
        )
        
        # Basic setup
        self.cerebro.broker.setcash(self.config.get('cash', 10000))
        self.cerebro.broker.setcommission(commission=0.001)  # 0.1%
    
    def run(self) -> Dict[str, Any]:
        """Run Backtrader and extract results"""
        print("🔄 Running via Backtrader adapter...")
        results = self.cerebro.run()
        strat = results[0]
        
        # Extract and standardize results
        return {
            'final_value': self.cerebro.broker.getvalue(),
            'analyzers': self._extract_analyzers(strat),
            'trades': self._extract_trades(strat)
        }
    
    def _extract_analyzers(self, strategy):
        """Standardize analyzer output"""
        return {
            'sharpe': getattr(strategy.analyzers.sharpe.get_analysis(), 'sharperatio', 0),
            'drawdown': strategy.analyzers.drawdown.get_analysis(),
            'trade_stats': strategy.analyzers.trades.get_analysis()
        }
    
    def _extract_trades(self, strategy):
        """Extract and standardize trade history"""
        # Implementation depends on your trade recording
        return []

class BacktraderStrategyAdapter(bt.Strategy):
    """
    Adapter that makes Backtrader use your strategy signals
    """
    params = (
        ('strategy_name', 'trend_following'),
        ('strategy_params', {}),
    )
    
    def __init__(self):
        # Import your strategy manager
        from backtest.strategies.strategy_manager import StrategyManager
        
        self.manager = StrategyManager(
            strategy_name=self.p.strategy_name,
            **self.p.strategy_params
        )
        self.data_close = self.datas[0].close
        
    def next(self):
        # Build window from Backtrader data
        lookback = 20
        if len(self.data_close) < lookback:
            return
            
        # Convert to DataFrame for your strategy manager
        window_data = []
        for i in range(-lookback, 0):
            window_data.append({
                'close': self.data_close[i],
                'open': self.datas[0].open[i],
                'high': self.datas[0].high[i],
                'low': self.datas[0].low[i],
                'volume': self.datas[0].volume[i]
            })
        
        df_window = pd.DataFrame(window_data)
        signal = self.manager.get_signal(df_window)
        
        # Execute in Backtrader
        if signal == 'BUY' and not self.position:
            self.buy()
        elif signal == 'SELL' and not self.position:
            self.sell()