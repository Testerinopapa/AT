# backtest/run_modern.py
"""
Modern backtest runner using the new core architecture
"""
import pandas as pd
import MetaTrader5 as mt5
from datetime import datetime
import matplotlib.pyplot as plt
import sys
import os

# Add the parent directory to Python path so we can import from backtest
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Import the new core architecture - FIXED IMPORTS
try:
    from backtest.core import (
        NativeEngine, NativeEngineConfig,
        PositionTracker, RiskManager,
        OrderManager, TradeExecutor, SlippageSimulator
    )
except ImportError:
    # Fallback: try relative imports
    from core import (
        NativeEngine, NativeEngineConfig,
        PositionTracker, RiskManager,
        OrderManager, TradeExecutor, SlippageSimulator
    )

# Import your existing strategy manager
try:
    from backtest.strategies.strategy_manager import StrategyManager
    from backtest.enhanced_reporting import QuantStatsReporter
except ImportError:
    # Fallback for direct execution
    from strategies.strategy_manager import StrategyManager
    from enhanced_reporting import QuantStatsReporter


def fetch_data(symbol: str, days: int, timeframe: int = 1):
    """Your existing data fetcher"""
    if not mt5.initialize():
        raise RuntimeError("MT5 init failed")
    if not mt5.symbol_select(symbol, True):
        mt5.shutdown()
        raise ValueError(f"Symbol {symbol} not available")

    from_ts = int((pd.Timestamp.now() - pd.Timedelta(days=days)).timestamp())
    to_ts = int(datetime.now().timestamp())
    rates = mt5.copy_rates_range(symbol, timeframe, from_ts, to_ts)
    mt5.shutdown()

    if rates is None or len(rates) < 100:
        raise ValueError("Not enough data")

    df = pd.DataFrame(rates)
    df['time'] = pd.to_datetime(df['time'], unit='s')
    return df


class ModernBacktestRunner:
    """
    Modern replacement for BacktestRunner using core architecture
    """
    
    def __init__(self, symbol="EURUSD", initial_balance=10000, 
                 strategy_name="trend_following", **strategy_params):
        self.symbol = symbol
        self.initial_balance = initial_balance
        self.strategy_name = strategy_name
        self.strategy_params = strategy_params
        
        # Initialize core components
        self.setup_core_components()
        
    def setup_core_components(self):
        """Initialize and wire up all core components"""
        
        # 1. Portfolio Management
        self.portfolio = PositionTracker(initial_balance=self.initial_balance)
        
        # 2. Risk Management 
        self.risk_manager = RiskManager(
            max_position_size=0.1,      # 10% per trade
            risk_per_trade=0.02,        # 2% risk per trade  
            max_daily_loss=0.05,        # 5% max daily loss
            volatility_lookback=20
        )
        
        # 3. Execution System
        self.slippage_simulator = SlippageSimulator(
            base_slippage=0.00005,      # 0.5 pips
            volatility_factor=2.0,
            latency_ms=150
        )
        
        self.order_manager = OrderManager(
            slippage_simulator=self.slippage_simulator
        )
        
        self.trade_executor = TradeExecutor(
            order_manager=self.order_manager,
            risk_manager=self.risk_manager
        )
        
        # 4. Strategy
        self.strategy_manager = StrategyManager(
            strategy_name=self.strategy_name,
            **self.strategy_params
        )
        
        # 5. Engine
        engine_config = NativeEngineConfig(
            symbol=self.symbol,
            initial_balance=self.initial_balance,
            strategy_name=self.strategy_name,
            strategy_params=self.strategy_params
        )
        
        self.engine = NativeEngine(engine_config)
        
        # Wire everything together
        self.engine.initialize(
            strategy_manager=self.strategy_manager,
            portfolio_manager=self.portfolio,
            execution_manager=self.trade_executor
        )
    
    def run_backtest(self, days=30, plot_results=True):
        """Run complete backtest with modern architecture"""
        print(f"🚀 Starting modern backtest for {self.symbol}")
        print(f"   Strategy: {self.strategy_name}")
        print(f"   Balance: ${self.initial_balance:,.2f}")
        print(f"   Days: {days}")
        
        # Fetch data
        df = fetch_data(self.symbol, days)
        if df is None:
            print("❌ Failed to fetch data")
            return None
        
        print(f"📊 Loaded {len(df)} bars of data")
        
        # Run backtest
        results = self.engine.run(df)
        
        # Generate comprehensive report
        self._generate_report(results, df)
        
        # Plot results if requested
        if plot_results:
            self._plot_results(results, df)
        
        return results
    
    def _generate_report(self, results, df):
        """Generate professional reports"""
        print("\n" + "="*70)
        print("📊 GENERATING COMPREHENSIVE REPORT")
        print("="*70)
        
        # Use your existing QuantStats reporter
        metrics = QuantStatsReporter.generate_report(
            equity_curve=results['equity_curve'],
            trades=self.portfolio.trade_history,
            timestamps=df['time'],
            initial_balance=self.initial_balance,
            strategy_name=f"{self.symbol}_{self.strategy_name}",
            output_file=f"backtests/{self.symbol}_{self.strategy_name}_modern.html"
        )
        
        # Print trade summary
        self._print_trade_summary()
        
        return metrics
    
    def _print_trade_summary(self):
        """Print detailed trade analysis"""
        trades = self.portfolio.trade_history
        closed_trades = [t for t in trades if t.get('action') == 'CLOSE']
        
        if not closed_trades:
            print("🤷 No closed trades to analyze")
            return
        
        winning_trades = [t for t in closed_trades if t.get('pnl', 0) > 0]
        losing_trades = [t for t in closed_trades if t.get('pnl', 0) < 0]
        
        total_pnl = sum(t.get('pnl', 0) for t in closed_trades)
        win_rate = len(winning_trades) / len(closed_trades) * 100
        
        print(f"\n🎯 TRADE PERFORMANCE SUMMARY:")
        print(f"   Total Trades: {len(closed_trades)}")
        print(f"   Winning Trades: {len(winning_trades)}")
        print(f"   Losing Trades: {len(losing_trades)}")
        print(f"   Win Rate: {win_rate:.1f}%")
        print(f"   Total P&L: ${total_pnl:+,.2f}")
        print(f"   Average P&L: ${total_pnl/len(closed_trades):+,.2f}")
        
        if winning_trades:
            avg_win = sum(t['pnl'] for t in winning_trades) / len(winning_trades)
            print(f"   Average Win: ${avg_win:+,.2f}")
        
        if losing_trades:
            avg_loss = sum(t['pnl'] for t in losing_trades) / len(losing_trades)
            print(f"   Average Loss: ${avg_loss:+,.2f}")
    
    def _plot_results(self, results, df):
        """Plot equity curve and trades"""
        plt.figure(figsize=(12, 8))
        
        # Plot equity curve
        plt.subplot(2, 1, 1)
        plt.plot(df['time'][:len(results['equity_curve'])], 
                results['equity_curve'], 
                label='Equity Curve', 
                color='blue', 
                linewidth=2)
        plt.title(f'Modern Backtest: {self.symbol} - {self.strategy_name}')
        plt.ylabel('Equity ($)')
        plt.legend()
        plt.grid(True, alpha=0.3)
        
        # Plot drawdown
        plt.subplot(2, 1, 2)
        equity = pd.Series(results['equity_curve'])
        rolling_max = equity.expanding().max()
        drawdown = (equity - rolling_max) / rolling_max * 100
        plt.fill_between(df['time'][:len(drawdown)], drawdown, 0, 
                        color='red', alpha=0.3, label='Drawdown')
        plt.ylabel('Drawdown (%)')
        plt.xlabel('Time')
        plt.legend()
        plt.grid(True, alpha=0.3)
        
        plt.tight_layout()
        plt.savefig(f'backtests/{self.symbol}_modern_equity.png', dpi=150, bbox_inches='tight')
        plt.show()
    
    def run_multiple_strategies(self, strategies, days=30):
        """Run and compare multiple strategies"""
        results = {}
        
        for strategy_name, params in strategies:
            print(f"\n{'='*60}")
            print(f"Testing {strategy_name}...")
            print(f"{'='*60}")
            
            # Create new runner for each strategy
            runner = ModernBacktestRunner(
                symbol=self.symbol,
                initial_balance=self.initial_balance,
                strategy_name=strategy_name,
                **params
            )
            
            strategy_results = runner.run_backtest(days=days, plot_results=False)
            results[strategy_name] = strategy_results
        
        # Compare results
        self._compare_strategies(results)
        return results
    
    def _compare_strategies(self, results):
        """Compare performance across strategies"""
        print("\n" + "="*70)
        print("🏆 STRATEGY COMPARISON")
        print("="*70)
        
        comparison_data = []
        
        for strategy_name, result in results.items():
            if result and 'equity_curve' in result:
                final_equity = result['equity_curve'][-1] if result['equity_curve'] else self.initial_balance
                total_return = (final_equity - self.initial_balance) / self.initial_balance * 100
                
                comparison_data.append({
                    'strategy': strategy_name,
                    'final_equity': final_equity,
                    'return_pct': total_return
                })
        
        # Sort by performance
        comparison_data.sort(key=lambda x: x['return_pct'], reverse=True)
        
        for i, data in enumerate(comparison_data, 1):
            emoji = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else "  "
            print(f"{emoji} {i:2d}. {data['strategy']:20} | "
                  f"Return: {data['return_pct']:+.2f}% | "
                  f"Equity: ${data['final_equity']:,.2f}")


def main():
    """Main function to demonstrate the modern backtest"""
    
    # Example 1: Single strategy backtest
    print("🎯 MODERN BACKTEST RUNNER")
    print("="*50)
    
    runner = ModernBacktestRunner(
        symbol="EURUSD",
        initial_balance=10000,
        strategy_name="trend_following",
        lookback_fast=8,
        lookback_slow=21
    )
    
    # Run single backtest
    results = runner.run_backtest(days=7, plot_results=True)
    
    # Example 2: Multiple strategy comparison (uncomment to run)
    """
    strategies = [
        ("trend_following", {"lookback_fast": 8, "lookback_slow": 21}),
        ("rsi", {"rsi_period": 14, "oversold": 30, "overbought": 70}),
        ("breakout", {"lookback_period": 20, "volatility_multiplier": 1.5}),
    ]
    
    runner.run_multiple_strategies(strategies, days=7)
    """


if __name__ == "__main__":
    main()