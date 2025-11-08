# backtest.py (updated)
from core import (
    NativeEngine, NativeEngineConfig, 
    PositionTracker, RiskManager,
    OrderManager, TradeExecutor, SlippageSimulator
)
from backtest.strategies.strategy_manager import StrategyManager
import pandas as pd

def run_modern_backtest():
    """Example using the new modular architecture"""
    
    # 1. Setup core components
    portfolio = PositionTracker(initial_balance=10000)
    risk_manager = RiskManager(
        max_position_size=0.1,    # 10% per trade
        risk_per_trade=0.01,      # 1% risk per trade
        max_daily_loss=0.02       # 2% max daily loss
    )
    
    slippage_sim = SlippageSimulator()
    order_manager = OrderManager(slippage_simulator=slippage_sim)
    trade_executor = TradeExecutor(order_manager, risk_manager)
    
    # 2. Setup engine
    engine_config = NativeEngineConfig(
        symbol="EURUSD",
        initial_balance=10000,
        strategy_name="trend_following",
        strategy_params={'lookback_fast': 8, 'lookback_slow': 21}
    )
    
    engine = NativeEngine(engine_config)
    
    # 3. Inject dependencies
    strategy_manager = StrategyManager(
        engine_config.strategy_name,
        **engine_config.strategy_params
    )
    
    engine.initialize(strategy_manager, portfolio, trade_executor)
    
    # 4. Run backtest
    df = fetch_data("EURUSD", days=30)  # Your existing data fetcher
    results = engine.run(df)
    
    # 5. Generate reports (using your existing reporting)
    from backtest.enhanced_reporting import QuantStatsReporter
    
    metrics = QuantStatsReporter.generate_report(
        equity_curve=results['equity_curve'],
        trades=portfolio.trade_history,
        timestamps=df['time'],
        strategy_name="Modern_Architecture_Test"
    )
    
    return metrics

if __name__ == "__main__":
    run_modern_backtest()