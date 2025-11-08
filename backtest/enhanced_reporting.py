# backtest/enhanced_reporting.py
"""
Professional backtesting reports using QuantStats
Provides comprehensive performance metrics and visualizations
"""

import quantstats as qs
import pandas as pd
import numpy as np
from typing import List, Dict, Optional
import warnings

# Suppress QuantStats warnings for cleaner output
warnings.filterwarnings('ignore')


class QuantStatsReporter:
    """
    Drop-in replacement for basic backtest reporting
    Generates comprehensive performance analysis using QuantStats
    """
    
    @staticmethod
    def generate_report(equity_curve: List[float], 
                       trades: List[Dict],
                       timestamps: pd.Series,
                       initial_balance: float = 10000,
                       strategy_name: str = "Strategy",
                       output_file: Optional[str] = None,
                       benchmark: Optional[pd.Series] = None) -> Dict:
        """
        Generate comprehensive QuantStats performance report
        
        Args:
            equity_curve: List of equity values over time
            trades: List of trade dictionaries with 'profit' key
            timestamps: Pandas Series of timestamps matching equity curve
            initial_balance: Starting capital
            strategy_name: Name for the report
            output_file: Path to save HTML report (optional)
            benchmark: Benchmark returns for comparison (optional)
            
        Returns:
            Dictionary with key performance metrics
        """
        
        try:
            # Convert equity curve to pandas Series with timestamps
            if len(equity_curve) > len(timestamps):
                equity_curve = equity_curve[:len(timestamps)]
            elif len(equity_curve) < len(timestamps):
                timestamps = timestamps[:len(equity_curve)]
            
            equity_series = pd.Series(equity_curve, index=timestamps)
            
            # Calculate returns
            returns = equity_series.pct_change().dropna()
            
            # Handle empty returns
            if len(returns) == 0 or returns.isna().all():
                print("⚠️  Warning: No valid returns calculated")
                return QuantStatsReporter._generate_basic_metrics(
                    equity_curve, trades, initial_balance
                )
            
            # Ensure timezone-naive (QuantStats requirement)
            if hasattr(returns.index, 'tz') and returns.index.tz is not None:
                returns.index = returns.index.tz_localize(None)
            
            # Clean infinite/NaN values
            returns = returns.replace([np.inf, -np.inf], np.nan)
            returns = returns.dropna()
            
            if len(returns) == 0:
                print("⚠️  Warning: No valid returns after cleaning")
                return QuantStatsReporter._generate_basic_metrics(
                    equity_curve, trades, initial_balance
                )
            
            # Console output
            print("\n" + "="*70)
            print(f"📊 QUANTSTATS PERFORMANCE REPORT - {strategy_name}")
            print("="*70)
            
            # Display comprehensive metrics
            print("\n📈 PERFORMANCE METRICS:")
            print("-" * 70)
            
            try:
                qs.reports.metrics(returns, mode='full', display=True)
            except Exception as e:
                print(f"⚠️  Could not display full metrics: {e}")
                print("\nDisplaying basic metrics instead:")
                QuantStatsReporter._print_basic_metrics(returns, equity_curve, 
                                                        initial_balance, trades)
            
            # Generate HTML report if requested
            if output_file:
                try:
                    qs.reports.html(
                        returns,
                        output=output_file,
                        title=f"{strategy_name} Backtest Report",
                        download_filename=output_file,
                        benchmark=benchmark
                    )
                    print(f"\n✅ HTML report saved to: {output_file}")
                except Exception as e:
                    print(f"⚠️  Could not generate HTML report: {e}")
            
            # Extract key metrics programmatically
            metrics = QuantStatsReporter._extract_metrics(returns, equity_curve, 
                                                          initial_balance, trades)
            
            # Print summary
            QuantStatsReporter._print_summary(metrics, trades)
            
            return metrics
            
        except Exception as e:
            print(f"❌ Error in QuantStats reporting: {e}")
            print("Falling back to basic metrics...")
            return QuantStatsReporter._generate_basic_metrics(
                equity_curve, trades, initial_balance
            )
    
    @staticmethod
    def _extract_metrics(returns: pd.Series, equity_curve: List[float],
                        initial_balance: float, trades: List[Dict]) -> Dict:
        """Extract key performance metrics"""
        
        try:
            metrics = {}
            
            # Return metrics
            metrics['total_return'] = qs.stats.comp(returns) * 100 if len(returns) > 0 else 0
            metrics['cagr'] = qs.stats.cagr(returns) * 100 if len(returns) > 0 else 0
            
            # Risk metrics
            metrics['sharpe'] = qs.stats.sharpe(returns) if len(returns) > 0 else 0
            metrics['sortino'] = qs.stats.sortino(returns) if len(returns) > 0 else 0
            metrics['calmar'] = qs.stats.calmar(returns) if len(returns) > 0 else 0
            metrics['max_drawdown'] = qs.stats.max_drawdown(returns) if len(returns) > 0 else 0
            
            # Win/Loss metrics
            metrics['win_rate'] = qs.stats.win_rate(returns) * 100 if len(returns) > 0 else 0
            
            winning_returns = returns[returns > 0]
            losing_returns = returns[returns < 0]
            
            metrics['avg_win'] = winning_returns.mean() * 100 if len(winning_returns) > 0 else 0
            metrics['avg_loss'] = losing_returns.mean() * 100 if len(losing_returns) > 0 else 0
            
            # Profit factor
            total_wins = winning_returns.sum()
            total_losses = abs(losing_returns.sum())
            metrics['profit_factor'] = total_wins / total_losses if total_losses > 0 else float('inf')
            
            # Volatility
            metrics['volatility'] = qs.stats.volatility(returns) * 100 if len(returns) > 0 else 0
            
            # Trade statistics
            closed_trades = [t for t in trades if t.get('profit') is not None 
                           and t.get('type') in ['SL', 'TP', 'TRAIL_SL', 'REVERSE']]
            
            metrics['total_trades'] = len(closed_trades)
            metrics['winning_trades'] = len([t for t in closed_trades if t['profit'] > 0])
            metrics['losing_trades'] = len([t for t in closed_trades if t['profit'] < 0])
            
            if len(closed_trades) > 0:
                metrics['trade_win_rate'] = metrics['winning_trades'] / len(closed_trades) * 100
                
                trade_profits = [t['profit'] for t in closed_trades]
                metrics['avg_trade'] = np.mean(trade_profits)
                metrics['best_trade'] = max(trade_profits)
                metrics['worst_trade'] = min(trade_profits)
            else:
                metrics['trade_win_rate'] = 0
                metrics['avg_trade'] = 0
                metrics['best_trade'] = 0
                metrics['worst_trade'] = 0
            
            # Clean any NaN/inf values
            for key, value in metrics.items():
                if isinstance(value, (float, np.floating)):
                    if np.isnan(value) or np.isinf(value):
                        metrics[key] = 0
            
            return metrics
            
        except Exception as e:
            print(f"⚠️  Error extracting metrics: {e}")
            return QuantStatsReporter._generate_basic_metrics(
                equity_curve, trades, initial_balance
            )
    
    @staticmethod
    def _generate_basic_metrics(equity_curve: List[float], 
                                trades: List[Dict],
                                initial_balance: float) -> Dict:
        """Fallback basic metrics if QuantStats fails"""
        
        final_balance = equity_curve[-1] if equity_curve else initial_balance
        total_return = (final_balance - initial_balance) / initial_balance * 100
        
        closed_trades = [t for t in trades if t.get('profit') is not None 
                        and t.get('type') in ['SL', 'TP', 'TRAIL_SL', 'REVERSE']]
        
        winning_trades = [t for t in closed_trades if t['profit'] > 0]
        losing_trades = [t for t in closed_trades if t['profit'] < 0]
        
        win_rate = len(winning_trades) / max(len(closed_trades), 1) * 100
        
        # Calculate max drawdown
        equity_array = np.array(equity_curve)
        peak = np.maximum.accumulate(equity_array)
        drawdown = (peak - equity_array) / peak
        max_dd = drawdown.max() * 100 if len(drawdown) > 0 else 0
        
        return {
            'total_return': total_return,
            'final_balance': final_balance,
            'max_drawdown': max_dd,
            'win_rate': win_rate,
            'total_trades': len(closed_trades),
            'winning_trades': len(winning_trades),
            'losing_trades': len(losing_trades),
            'sharpe': 0,
            'sortino': 0,
            'calmar': 0,
            'profit_factor': 0
        }
    
    @staticmethod
    def _print_basic_metrics(returns: pd.Series, equity_curve: List[float],
                            initial_balance: float, trades: List[Dict]):
        """Print basic metrics if full QuantStats fails"""
        
        final_balance = equity_curve[-1] if equity_curve else initial_balance
        total_return = (final_balance - initial_balance) / initial_balance * 100
        
        # Calculate basic stats
        if len(returns) > 0:
            avg_return = returns.mean() * 100
            vol = returns.std() * 100
            sharpe = (avg_return / vol * np.sqrt(252)) if vol > 0 else 0
        else:
            avg_return = vol = sharpe = 0
        
        print(f"Total Return: {total_return:+.2f}%")
        print(f"Average Return: {avg_return:.4f}%")
        print(f"Volatility: {vol:.2f}%")
        print(f"Sharpe Ratio: {sharpe:.2f}")
    
    @staticmethod
    def _print_summary(metrics: Dict, trades: List[Dict]):
        """Print formatted summary of key metrics"""
        
        print("\n" + "="*70)
        print("📊 KEY METRICS SUMMARY")
        print("="*70)
        
        print(f"\n💰 RETURNS:")
        print(f"   Total Return:        {metrics.get('total_return', 0):+.2f}%")
        print(f"   CAGR:                {metrics.get('cagr', 0):+.2f}%")
        
        print(f"\n📉 RISK METRICS:")
        print(f"   Sharpe Ratio:        {metrics.get('sharpe', 0):.2f}")
        print(f"   Sortino Ratio:       {metrics.get('sortino', 0):.2f}")
        print(f"   Calmar Ratio:        {metrics.get('calmar', 0):.2f}")
        print(f"   Max Drawdown:        {metrics.get('max_drawdown', 0):.2f}%")
        print(f"   Volatility:          {metrics.get('volatility', 0):.2f}%")
        
        print(f"\n🎯 TRADING STATISTICS:")
        print(f"   Total Trades:        {metrics.get('total_trades', 0)}")
        print(f"   Winning Trades:      {metrics.get('winning_trades', 0)}")
        print(f"   Losing Trades:       {metrics.get('losing_trades', 0)}")
        print(f"   Win Rate:            {metrics.get('trade_win_rate', 0):.1f}%")
        print(f"   Profit Factor:       {metrics.get('profit_factor', 0):.2f}")
        
        print(f"\n💵 TRADE PERFORMANCE:")
        print(f"   Average Trade:       ${metrics.get('avg_trade', 0):+,.2f}")
        print(f"   Best Trade:          ${metrics.get('best_trade', 0):+,.2f}")
        print(f"   Worst Trade:         ${metrics.get('worst_trade', 0):+,.2f}")
        
        # Verdict
        print(f"\n{'='*70}")
        print("🎯 STRATEGY VERDICT:")
        
        sharpe = metrics.get('sharpe', 0)
        total_return = metrics.get('total_return', 0)
        win_rate = metrics.get('trade_win_rate', 0)
        
        if sharpe > 2 and total_return > 20:
            print("   ✅ EXCELLENT - Strong risk-adjusted returns!")
        elif sharpe > 1 and total_return > 10:
            print("   👍 GOOD - Solid performance, worth considering")
        elif sharpe > 0.5 and total_return > 0:
            print("   ⚠️  AVERAGE - Mediocre performance, needs improvement")
        elif total_return > 0:
            print("   😐 WEAK - Profitable but poor risk-adjusted returns")
        else:
            print("   ❌ POOR - Strategy is losing money")
        
        # Additional warnings
        if win_rate < 40:
            print("   ⚠️  Low win rate - consider adjusting entry/exit rules")
        if metrics.get('max_drawdown', 0) > 20:
            print("   ⚠️  High drawdown - risk management needs improvement")
        if metrics.get('total_trades', 0) < 20:
            print("   ⚠️  Too few trades - results may not be statistically significant")
        
        print("="*70 + "\n")


# Convenience function for quick reporting
def quick_report(equity: List[float], 
                trades: List[Dict], 
                timestamps: pd.Series,
                strategy_name: str = "Strategy",
                output_html: bool = True) -> Dict:
    """
    Quick one-liner to generate a report
    
    Usage:
        from backtest.enhanced_reporting import quick_report
        metrics = quick_report(equity, trades, df['time'], "MyStrategy")
    """
    
    output_file = f"backtests/{strategy_name}_report.html" if output_html else None
    
    return QuantStatsReporter.generate_report(
        equity_curve=equity,
        trades=trades,
        timestamps=timestamps,
        strategy_name=strategy_name,
        output_file=output_file
    )


# Example usage
if __name__ == "__main__":
    print("Enhanced Reporting Module")
    print("="*70)
    print("\nUsage in your backtest_runner.py:")
    print("\n1. Import:")
    print("   from backtest.enhanced_reporting import QuantStatsReporter")
    print("\n2. Replace _generate_results() with:")
    print("""
    def _generate_results(self, df, equity, trades, final_balance):
        output_file = f"backtests/{self.symbol}_{self.strategy_name}_report.html"
        metrics = QuantStatsReporter.generate_report(
            equity_curve=equity,
            trades=trades,
            timestamps=df['time'],
            initial_balance=self.initial_balance,
            strategy_name=f"{self.symbol}_{self.strategy_name}",
            output_file=output_file
        )
        return metrics
    """)
    print("\n3. Run your backtest and enjoy professional reports! 🎉")