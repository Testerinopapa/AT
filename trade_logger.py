"""
Enhanced Trade Logger Module

Provides comprehensive logging capabilities including:
- Structured trade logging (text, CSV, SQLite)
- Performance analytics
- Trade statistics
- Report generation
"""

import json
import csv
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import MetaTrader5 as mt5


class TradeLogger:
    """Enhanced trade logger with multiple output formats and analytics."""
    
    def __init__(self, log_dir: str = "logs"):
        """
        Initialize TradeLogger.
        
        Args:
            log_dir: Directory for log files
        """
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(exist_ok=True)
        
        # File paths
        self.text_log = self.log_dir / "trades.log"
        self.csv_log = self.log_dir / "trades.csv"
        self.db_path = self.log_dir / "trades.db"
        self.stats_file = self.log_dir / "statistics.json"
        
        # Initialize database
        self._init_database()
        
        # Initialize CSV if it doesn't exist
        self._init_csv()
        
        print(f"[TradeLogger] Initialized with log directory: {self.log_dir}")
    
    def _init_database(self):
        """Initialize SQLite database with trades table."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                symbol TEXT NOT NULL,
                action TEXT NOT NULL,
                order_id INTEGER,
                ticket INTEGER,
                volume REAL,
                entry_price REAL,
                sl REAL,
                tp REAL,
                exit_price REAL,
                profit REAL,
                commission REAL,
                swap REAL,
                duration_seconds INTEGER,
                status TEXT,
                retcode INTEGER,
                comment TEXT,
                strategy TEXT,
                risk_reward_ratio REAL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Create indexes for faster queries
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_timestamp ON trades(timestamp)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_symbol ON trades(symbol)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_action ON trades(action)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_status ON trades(status)")
        
        conn.commit()
        conn.close()
    
    def _init_csv(self):
        """Initialize CSV file with headers if it doesn't exist."""
        if not self.csv_log.exists():
            with open(self.csv_log, 'w', newline='') as f:
                writer = csv.writer(f)
                writer.writerow([
                    'Timestamp', 'Symbol', 'Action', 'Order_ID', 'Ticket',
                    'Volume', 'Entry_Price', 'SL', 'TP', 'Exit_Price',
                    'Profit', 'Commission', 'Swap', 'Duration_Seconds',
                    'Status', 'Retcode', 'Comment', 'Strategy', 'Risk_Reward_Ratio'
                ])
    
    def log_trade_open(self, symbol: str, action: str, result, volume: float,
                       entry_price: float, sl: float, tp: float, strategy: str = "Unknown"):
        """
        Log a trade opening.
        
        Args:
            symbol: Trading symbol
            action: Trade action (BUY/SELL)
            result: MT5 order result
            volume: Trade volume
            entry_price: Entry price
            sl: Stop loss
            tp: Take profit
            strategy: Strategy name
        """
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        # Calculate risk/reward ratio
        if action == "BUY":
            risk = entry_price - sl
            reward = tp - entry_price
        else:
            risk = sl - entry_price
            reward = entry_price - tp
        
        rr_ratio = reward / risk if risk > 0 else 0
        
        trade_data = {
            'timestamp': timestamp,
            'symbol': symbol,
            'action': action,
            'order_id': result.order,
            'ticket': result.order,
            'volume': volume,
            'entry_price': entry_price,
            'sl': sl,
            'tp': tp,
            'exit_price': None,
            'profit': None,
            'commission': None,
            'swap': None,
            'duration_seconds': None,
            'status': 'OPEN' if result.retcode == mt5.TRADE_RETCODE_DONE else 'FAILED',
            'retcode': result.retcode,
            'comment': result.comment if hasattr(result, 'comment') else '',
            'strategy': strategy,
            'risk_reward_ratio': round(rr_ratio, 2)
        }
        
        # Log to text file
        self._log_to_text(trade_data)
        
        # Log to CSV
        self._log_to_csv(trade_data)
        
        # Log to database
        self._log_to_database(trade_data)
        
        return trade_data
    
    def log_trade_close(self, ticket: int, exit_price: float, profit: float,
                        commission: float = 0, swap: float = 0):
        """
        Log a trade closing.
        
        Args:
            ticket: Trade ticket number
            exit_price: Exit price
            profit: Trade profit
            commission: Commission paid
            swap: Swap paid/received
        """
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        # Update database
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Get original trade data
        cursor.execute("SELECT timestamp FROM trades WHERE ticket = ? AND status = 'OPEN'", (ticket,))
        result = cursor.fetchone()
        
        if result:
            open_time = datetime.strptime(result[0], '%Y-%m-%d %H:%M:%S')
            close_time = datetime.strptime(timestamp, '%Y-%m-%d %H:%M:%S')
            duration = int((close_time - open_time).total_seconds())
            
            cursor.execute("""
                UPDATE trades 
                SET exit_price = ?, profit = ?, commission = ?, swap = ?,
                    duration_seconds = ?, status = 'CLOSED'
                WHERE ticket = ? AND status = 'OPEN'
            """, (exit_price, profit, commission, swap, duration, ticket))
            
            conn.commit()
            
            # Log to text file
            with open(self.text_log, 'a') as f:
                f.write(
                    f"{timestamp} | CLOSE | Ticket: {ticket} | "
                    f"Exit: {exit_price:.5f} | Profit: {profit:.2f} | "
                    f"Duration: {duration}s\n"
                )
        
        conn.close()
    
    def _log_to_text(self, trade_data: Dict):
        """Log trade to text file."""
        with open(self.text_log, 'a') as f:
            f.write(
                f"{trade_data['timestamp']} | "
                f"{trade_data['action']:<12} | "
                f"Order: {trade_data['order_id']:<12} | "
                f"Price: {trade_data['entry_price']:.5f} | "
                f"SL: {trade_data['sl']:.5f} | "
                f"TP: {trade_data['tp']:.5f} | "
                f"Vol: {trade_data['volume']:.2f} | "
                f"R/R: {trade_data['risk_reward_ratio']:.2f} | "
                f"Strategy: {trade_data['strategy']} | "
                f"Status: {trade_data['status']} | "
                f"Retcode: {trade_data['retcode']}\n"
            )
    
    def _log_to_csv(self, trade_data: Dict):
        """Log trade to CSV file."""
        with open(self.csv_log, 'a', newline='') as f:
            writer = csv.writer(f)
            writer.writerow([
                trade_data['timestamp'],
                trade_data['symbol'],
                trade_data['action'],
                trade_data['order_id'],
                trade_data['ticket'],
                trade_data['volume'],
                trade_data['entry_price'],
                trade_data['sl'],
                trade_data['tp'],
                trade_data['exit_price'],
                trade_data['profit'],
                trade_data['commission'],
                trade_data['swap'],
                trade_data['duration_seconds'],
                trade_data['status'],
                trade_data['retcode'],
                trade_data['comment'],
                trade_data['strategy'],
                trade_data['risk_reward_ratio']
            ])
    
    def _log_to_database(self, trade_data: Dict):
        """Log trade to SQLite database."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT INTO trades (
                timestamp, symbol, action, order_id, ticket, volume,
                entry_price, sl, tp, exit_price, profit, commission, swap,
                duration_seconds, status, retcode, comment, strategy, risk_reward_ratio
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            trade_data['timestamp'],
            trade_data['symbol'],
            trade_data['action'],
            trade_data['order_id'],
            trade_data['ticket'],
            trade_data['volume'],
            trade_data['entry_price'],
            trade_data['sl'],
            trade_data['tp'],
            trade_data['exit_price'],
            trade_data['profit'],
            trade_data['commission'],
            trade_data['swap'],
            trade_data['duration_seconds'],
            trade_data['status'],
            trade_data['retcode'],
            trade_data['comment'],
            trade_data['strategy'],
            trade_data['risk_reward_ratio']
        ))
        
        conn.commit()
        conn.close()
    
    def get_statistics(self, days: int = 30) -> Dict:
        """
        Get trading statistics for the last N days.
        
        Args:
            days: Number of days to analyze
            
        Returns:
            Dictionary with statistics
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Calculate date threshold
        date_threshold = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
        
        # Total trades
        cursor.execute("""
            SELECT COUNT(*) FROM trades 
            WHERE timestamp >= ? AND status = 'CLOSED'
        """, (date_threshold,))
        total_trades = cursor.fetchone()[0]
        
        # Winning trades
        cursor.execute("""
            SELECT COUNT(*) FROM trades 
            WHERE timestamp >= ? AND status = 'CLOSED' AND profit > 0
        """, (date_threshold,))
        winning_trades = cursor.fetchone()[0]
        
        # Losing trades
        losing_trades = total_trades - winning_trades
        
        # Win rate
        win_rate = (winning_trades / total_trades * 100) if total_trades > 0 else 0
        
        # Total profit/loss
        cursor.execute("""
            SELECT COALESCE(SUM(profit), 0) FROM trades 
            WHERE timestamp >= ? AND status = 'CLOSED'
        """, (date_threshold,))
        total_pnl = cursor.fetchone()[0]
        
        # Average profit
        cursor.execute("""
            SELECT COALESCE(AVG(profit), 0) FROM trades 
            WHERE timestamp >= ? AND status = 'CLOSED' AND profit > 0
        """, (date_threshold,))
        avg_profit = cursor.fetchone()[0]
        
        # Average loss
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
        
        conn.close()
        
        stats = {
            'period_days': days,
            'total_trades': total_trades,
            'winning_trades': winning_trades,
            'losing_trades': losing_trades,
            'win_rate': round(win_rate, 2),
            'total_pnl': round(total_pnl, 2),
            'avg_profit': round(avg_profit, 2),
            'avg_loss': round(avg_loss, 2),
            'gross_profit': round(gross_profit, 2),
            'gross_loss': round(gross_loss, 2),
            'profit_factor': round(profit_factor, 2),
            'generated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }
        
        # Save to file
        with open(self.stats_file, 'w') as f:
            json.dump(stats, f, indent=2)
        
        return stats

