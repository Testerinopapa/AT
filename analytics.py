"""
Performance Analytics Module

Provides comprehensive analytics and reporting:
- Performance metrics calculation
- Strategy comparison
- Report generation
- Data visualization preparation
"""

import sqlite3
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from collections import defaultdict


class PerformanceAnalytics:
    """Performance analytics and reporting engine."""
    
    def __init__(self, db_path: str = "logs/trades.db"):
        """
        Initialize PerformanceAnalytics.
        
        Args:
            db_path: Path to SQLite database
        """
        self.db_path = Path(db_path)
        self.reports_dir = Path("logs/reports")
        self.reports_dir.mkdir(exist_ok=True)
        
        print(f"[Analytics] Initialized with database: {self.db_path}")
    
    def generate_performance_report(self, days: int = 30) -> Dict:
        """
        Generate comprehensive performance report.
        
        Args:
            days: Number of days to analyze
            
        Returns:
            Dictionary with performance metrics
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        date_threshold = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
        
        # Basic statistics
        basic_stats = self._get_basic_statistics(cursor, date_threshold)
        
        # Strategy performance
        strategy_stats = self._get_strategy_performance(cursor, date_threshold)
        
        # Time-based analysis
        time_stats = self._get_time_analysis(cursor, date_threshold)
        
        # Risk metrics
        risk_metrics = self._get_risk_metrics(cursor, date_threshold)
        
        # Best and worst trades
        best_worst = self._get_best_worst_trades(cursor, date_threshold)
        
        conn.close()
        
        report = {
            'report_date': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'period_days': days,
            'basic_statistics': basic_stats,
            'strategy_performance': strategy_stats,
            'time_analysis': time_stats,
            'risk_metrics': risk_metrics,
            'best_worst_trades': best_worst
        }
        
        # Save report to file
        report_file = self.reports_dir / f"performance_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(report_file, 'w') as f:
            json.dump(report, f, indent=2)
        
        print(f"[Analytics] Performance report saved: {report_file}")
        
        return report
    
    def _get_basic_statistics(self, cursor, date_threshold: str) -> Dict:
        """Calculate basic trading statistics."""
        # Total trades
        cursor.execute("""
            SELECT COUNT(*) FROM trades 
            WHERE timestamp >= ? AND status = 'CLOSED'
        """, (date_threshold,))
        total_trades = cursor.fetchone()[0]
        
        # Winning/losing trades
        cursor.execute("""
            SELECT 
                COUNT(CASE WHEN profit > 0 THEN 1 END) as wins,
                COUNT(CASE WHEN profit < 0 THEN 1 END) as losses,
                COUNT(CASE WHEN profit = 0 THEN 1 END) as breakeven
            FROM trades 
            WHERE timestamp >= ? AND status = 'CLOSED'
        """, (date_threshold,))
        wins, losses, breakeven = cursor.fetchone()
        
        # Win rate
        win_rate = (wins / total_trades * 100) if total_trades > 0 else 0
        
        # P/L statistics
        cursor.execute("""
            SELECT 
                COALESCE(SUM(profit), 0) as total_pnl,
                COALESCE(AVG(profit), 0) as avg_pnl,
                COALESCE(MAX(profit), 0) as max_profit,
                COALESCE(MIN(profit), 0) as max_loss
            FROM trades 
            WHERE timestamp >= ? AND status = 'CLOSED'
        """, (date_threshold,))
        total_pnl, avg_pnl, max_profit, max_loss = cursor.fetchone()
        
        # Average winning/losing trade
        cursor.execute("""
            SELECT COALESCE(AVG(profit), 0) FROM trades 
            WHERE timestamp >= ? AND status = 'CLOSED' AND profit > 0
        """, (date_threshold,))
        avg_win = cursor.fetchone()[0]
        
        cursor.execute("""
            SELECT COALESCE(AVG(profit), 0) FROM trades 
            WHERE timestamp >= ? AND status = 'CLOSED' AND profit < 0
        """, (date_threshold,))
        avg_loss = cursor.fetchone()[0]
        
        # Profit factor
        cursor.execute("""
            SELECT COALESCE(SUM(profit), 0) FROM trades 
            WHERE timestamp >= ? AND status = 'CLOSED' AND profit > 0
        """, (date_threshold,))
        gross_profit = cursor.fetchone()[0]
        
        cursor.execute("""
            SELECT COALESCE(SUM(ABS(profit)), 0) FROM trades 
            WHERE timestamp >= ? AND status = 'CLOSED' AND profit < 0
        """, (date_threshold,))
        gross_loss = cursor.fetchone()[0]
        
        profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else 0
        
        # Average trade duration
        cursor.execute("""
            SELECT COALESCE(AVG(duration_seconds), 0) FROM trades 
            WHERE timestamp >= ? AND status = 'CLOSED' AND duration_seconds IS NOT NULL
        """, (date_threshold,))
        avg_duration = cursor.fetchone()[0]
        
        return {
            'total_trades': total_trades,
            'winning_trades': wins,
            'losing_trades': losses,
            'breakeven_trades': breakeven,
            'win_rate_percent': round(win_rate, 2),
            'total_pnl': round(total_pnl, 2),
            'average_pnl': round(avg_pnl, 2),
            'max_profit': round(max_profit, 2),
            'max_loss': round(max_loss, 2),
            'average_win': round(avg_win, 2),
            'average_loss': round(avg_loss, 2),
            'gross_profit': round(gross_profit, 2),
            'gross_loss': round(gross_loss, 2),
            'profit_factor': round(profit_factor, 2),
            'average_duration_seconds': round(avg_duration, 0)
        }
    
    def _get_strategy_performance(self, cursor, date_threshold: str) -> Dict:
        """Analyze performance by strategy."""
        cursor.execute("""
            SELECT 
                strategy,
                COUNT(*) as total_trades,
                COUNT(CASE WHEN profit > 0 THEN 1 END) as wins,
                COALESCE(SUM(profit), 0) as total_pnl,
                COALESCE(AVG(profit), 0) as avg_pnl
            FROM trades 
            WHERE timestamp >= ? AND status = 'CLOSED'
            GROUP BY strategy
            ORDER BY total_pnl DESC
        """, (date_threshold,))
        
        strategies = {}
        for row in cursor.fetchall():
            strategy, total, wins, pnl, avg_pnl = row
            win_rate = (wins / total * 100) if total > 0 else 0
            strategies[strategy] = {
                'total_trades': total,
                'winning_trades': wins,
                'win_rate_percent': round(win_rate, 2),
                'total_pnl': round(pnl, 2),
                'average_pnl': round(avg_pnl, 2)
            }
        
        return strategies
    
    def _get_time_analysis(self, cursor, date_threshold: str) -> Dict:
        """Analyze performance by time periods."""
        # Daily performance
        cursor.execute("""
            SELECT 
                DATE(timestamp) as trade_date,
                COUNT(*) as trades,
                COALESCE(SUM(profit), 0) as daily_pnl
            FROM trades 
            WHERE timestamp >= ? AND status = 'CLOSED'
            GROUP BY DATE(timestamp)
            ORDER BY trade_date DESC
            LIMIT 30
        """, (date_threshold,))
        
        daily_performance = []
        for row in cursor.fetchall():
            date, trades, pnl = row
            daily_performance.append({
                'date': date,
                'trades': trades,
                'pnl': round(pnl, 2)
            })
        
        # Hour of day analysis
        cursor.execute("""
            SELECT 
                CAST(strftime('%H', timestamp) AS INTEGER) as hour,
                COUNT(*) as trades,
                COALESCE(SUM(profit), 0) as pnl
            FROM trades 
            WHERE timestamp >= ? AND status = 'CLOSED'
            GROUP BY hour
            ORDER BY hour
        """, (date_threshold,))
        
        hourly_performance = {}
        for row in cursor.fetchall():
            hour, trades, pnl = row
            hourly_performance[f"{hour:02d}:00"] = {
                'trades': trades,
                'pnl': round(pnl, 2)
            }
        
        return {
            'daily_performance': daily_performance,
            'hourly_performance': hourly_performance
        }
    
    def _get_risk_metrics(self, cursor, date_threshold: str) -> Dict:
        """Calculate risk-related metrics."""
        # Get all closed trades
        cursor.execute("""
            SELECT profit FROM trades 
            WHERE timestamp >= ? AND status = 'CLOSED'
            ORDER BY timestamp
        """, (date_threshold,))
        
        profits = [row[0] for row in cursor.fetchall()]
        
        if not profits:
            return {
                'max_drawdown': 0,
                'max_drawdown_percent': 0,
                'sharpe_ratio': 0,
                'consecutive_wins': 0,
                'consecutive_losses': 0
            }
        
        # Calculate drawdown
        cumulative = []
        running_sum = 0
        for profit in profits:
            running_sum += profit
            cumulative.append(running_sum)
        
        max_drawdown = 0
        peak = cumulative[0]
        for value in cumulative:
            if value > peak:
                peak = value
            drawdown = peak - value
            if drawdown > max_drawdown:
                max_drawdown = drawdown
        
        # Max drawdown percentage
        max_drawdown_pct = (max_drawdown / peak * 100) if peak > 0 else 0
        
        # Consecutive wins/losses
        max_consecutive_wins = 0
        max_consecutive_losses = 0
        current_wins = 0
        current_losses = 0
        
        for profit in profits:
            if profit > 0:
                current_wins += 1
                current_losses = 0
                max_consecutive_wins = max(max_consecutive_wins, current_wins)
            elif profit < 0:
                current_losses += 1
                current_wins = 0
                max_consecutive_losses = max(max_consecutive_losses, current_losses)
        
        # Simple Sharpe ratio (assuming risk-free rate = 0)
        if len(profits) > 1:
            avg_return = sum(profits) / len(profits)
            std_dev = (sum((p - avg_return) ** 2 for p in profits) / len(profits)) ** 0.5
            sharpe_ratio = (avg_return / std_dev) if std_dev > 0 else 0
        else:
            sharpe_ratio = 0
        
        return {
            'max_drawdown': round(max_drawdown, 2),
            'max_drawdown_percent': round(max_drawdown_pct, 2),
            'sharpe_ratio': round(sharpe_ratio, 2),
            'consecutive_wins': max_consecutive_wins,
            'consecutive_losses': max_consecutive_losses
        }
    
    def _get_best_worst_trades(self, cursor, date_threshold: str) -> Dict:
        """Get best and worst performing trades."""
        # Best trades
        cursor.execute("""
            SELECT timestamp, symbol, action, entry_price, exit_price, profit, strategy
            FROM trades 
            WHERE timestamp >= ? AND status = 'CLOSED'
            ORDER BY profit DESC
            LIMIT 5
        """, (date_threshold,))
        
        best_trades = []
        for row in cursor.fetchall():
            best_trades.append({
                'timestamp': row[0],
                'symbol': row[1],
                'action': row[2],
                'entry_price': row[3],
                'exit_price': row[4],
                'profit': round(row[5], 2),
                'strategy': row[6]
            })
        
        # Worst trades
        cursor.execute("""
            SELECT timestamp, symbol, action, entry_price, exit_price, profit, strategy
            FROM trades 
            WHERE timestamp >= ? AND status = 'CLOSED'
            ORDER BY profit ASC
            LIMIT 5
        """, (date_threshold,))
        
        worst_trades = []
        for row in cursor.fetchall():
            worst_trades.append({
                'timestamp': row[0],
                'symbol': row[1],
                'action': row[2],
                'entry_price': row[3],
                'exit_price': row[4],
                'profit': round(row[5], 2),
                'strategy': row[6]
            })
        
        return {
            'best_trades': best_trades,
            'worst_trades': worst_trades
        }
    
    def print_summary_report(self, days: int = 30):
        """Print a formatted summary report to console."""
        report = self.generate_performance_report(days)
        
        print("\n" + "="*80)
        print(f"📊 PERFORMANCE REPORT - Last {days} Days")
        print("="*80)
        
        stats = report['basic_statistics']
        print(f"\n📈 BASIC STATISTICS")
        print(f"   Total Trades: {stats['total_trades']}")
        print(f"   Winning Trades: {stats['winning_trades']} ({stats['win_rate_percent']}%)")
        print(f"   Losing Trades: {stats['losing_trades']}")
        print(f"   Total P/L: ${stats['total_pnl']:.2f}")
        print(f"   Average P/L: ${stats['average_pnl']:.2f}")
        print(f"   Profit Factor: {stats['profit_factor']:.2f}")
        
        risk = report['risk_metrics']
        print(f"\n⚠️  RISK METRICS")
        print(f"   Max Drawdown: ${risk['max_drawdown']:.2f} ({risk['max_drawdown_percent']:.2f}%)")
        print(f"   Sharpe Ratio: {risk['sharpe_ratio']:.2f}")
        print(f"   Max Consecutive Wins: {risk['consecutive_wins']}")
        print(f"   Max Consecutive Losses: {risk['consecutive_losses']}")
        
        if report['strategy_performance']:
            print(f"\n🎯 STRATEGY PERFORMANCE")
            for strategy, perf in report['strategy_performance'].items():
                print(f"   {strategy}:")
                print(f"      Trades: {perf['total_trades']} | Win Rate: {perf['win_rate_percent']}% | P/L: ${perf['total_pnl']:.2f}")
        
        print("\n" + "="*80)

