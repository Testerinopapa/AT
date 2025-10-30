"""
Tests for trade logging and analytics modules.
"""

import pytest
import sqlite3
import json
from pathlib import Path
from datetime import datetime, timedelta
from unittest.mock import Mock, patch, MagicMock
import tempfile
import shutil

from trade_logger import TradeLogger
from analytics import PerformanceAnalytics


@pytest.fixture
def temp_log_dir():
    """Create a temporary directory for test logs."""
    temp_dir = tempfile.mkdtemp()
    yield temp_dir
    shutil.rmtree(temp_dir)


@pytest.fixture
def logger(temp_log_dir):
    """Create a TradeLogger instance with temporary directory."""
    return TradeLogger(log_dir=temp_log_dir)


@pytest.fixture
def analytics(temp_log_dir):
    """Create a PerformanceAnalytics instance with temporary database."""
    db_path = Path(temp_log_dir) / "trades.db"
    return PerformanceAnalytics(db_path=str(db_path))


class TestTradeLogger:
    """Test TradeLogger functionality."""
    
    def test_logger_initialization(self, logger, temp_log_dir):
        """Test logger initializes correctly."""
        assert logger.log_dir.exists()
        # CSV and DB are created on init, text log is created on first write
        assert logger.csv_log.exists()
        assert logger.db_path.exists()
    
    def test_database_schema(self, logger):
        """Test database schema is created correctly."""
        conn = sqlite3.connect(logger.db_path)
        cursor = conn.cursor()
        
        # Check table exists
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='trades'")
        assert cursor.fetchone() is not None
        
        # Check columns
        cursor.execute("PRAGMA table_info(trades)")
        columns = [row[1] for row in cursor.fetchall()]
        
        expected_columns = [
            'id', 'timestamp', 'symbol', 'action', 'order_id', 'ticket',
            'volume', 'entry_price', 'sl', 'tp', 'exit_price', 'profit',
            'commission', 'swap', 'duration_seconds', 'status', 'retcode',
            'comment', 'strategy', 'risk_reward_ratio', 'created_at'
        ]
        
        for col in expected_columns:
            assert col in columns
        
        conn.close()
    
    def test_log_trade_open(self, logger):
        """Test logging a trade opening."""
        # Mock MT5 result
        result = Mock()
        result.order = 12345
        result.retcode = 10009
        result.comment = "Request executed"
        
        logger.log_trade_open(
            symbol="EURUSD",
            action="BUY",
            result=result,
            volume=1.0,
            entry_price=1.16000,
            sl=1.15500,
            tp=1.17000,
            strategy="TestStrategy"
        )
        
        # Check database
        conn = sqlite3.connect(logger.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM trades WHERE order_id = ?", (12345,))
        row = cursor.fetchone()
        
        assert row is not None
        assert row[2] == "EURUSD"  # symbol
        assert row[3] == "BUY"  # action
        assert row[6] == 1.0  # volume
        assert row[7] == 1.16000  # entry_price
        assert row[15] == "OPEN"  # status
        assert row[18] == "TestStrategy"  # strategy
        
        conn.close()
    
    def test_log_trade_close(self, logger):
        """Test logging a trade closing."""
        # First open a trade
        result = Mock()
        result.order = 12345
        result.retcode = 10009
        result.comment = "Request executed"
        
        logger.log_trade_open(
            symbol="EURUSD",
            action="BUY",
            result=result,
            volume=1.0,
            entry_price=1.16000,
            sl=1.15500,
            tp=1.17000,
            strategy="TestStrategy"
        )
        
        # Now close it
        logger.log_trade_close(
            ticket=12345,
            exit_price=1.16500,
            profit=50.0,
            commission=-2.0,
            swap=-1.0
        )
        
        # Check database
        conn = sqlite3.connect(logger.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM trades WHERE order_id = ?", (12345,))
        row = cursor.fetchone()
        
        assert row is not None
        assert row[10] == 1.16500  # exit_price
        assert row[11] == 50.0  # profit
        assert row[12] == -2.0  # commission
        assert row[13] == -1.0  # swap
        assert row[15] == "CLOSED"  # status
        assert row[14] is not None  # duration_seconds
        
        conn.close()
    
    def test_risk_reward_ratio_calculation(self, logger):
        """Test risk/reward ratio is calculated correctly."""
        result = Mock()
        result.order = 12345
        result.retcode = 10009
        result.comment = "Request executed"
        
        # BUY trade: SL below, TP above
        logger.log_trade_open(
            symbol="EURUSD",
            action="BUY",
            result=result,
            volume=1.0,
            entry_price=1.16000,
            sl=1.15500,  # 500 pips risk
            tp=1.17000,  # 1000 pips reward
            strategy="TestStrategy"
        )
        
        conn = sqlite3.connect(logger.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT risk_reward_ratio FROM trades WHERE order_id = ?", (12345,))
        rr_ratio = cursor.fetchone()[0]
        
        # R/R should be 1000/500 = 2.0
        assert abs(rr_ratio - 2.0) < 0.01
        
        conn.close()
    
    def test_csv_export(self, logger):
        """Test trades are exported to CSV."""
        result = Mock()
        result.order = 12345
        result.retcode = 10009
        result.comment = "Request executed"
        
        logger.log_trade_open(
            symbol="EURUSD",
            action="BUY",
            result=result,
            volume=1.0,
            entry_price=1.16000,
            sl=1.15500,
            tp=1.17000,
            strategy="TestStrategy"
        )
        
        # Check CSV file exists and has content
        assert logger.csv_log.exists()
        
        with open(logger.csv_log, 'r') as f:
            lines = f.readlines()
            assert len(lines) >= 2  # Header + 1 trade
            assert "EURUSD" in lines[1]
            assert "BUY" in lines[1]


class TestPerformanceAnalytics:
    """Test PerformanceAnalytics functionality."""
    
    def setup_test_data(self, analytics):
        """Setup test data in database."""
        conn = sqlite3.connect(analytics.db_path)
        cursor = conn.cursor()
        
        # Create table if not exists
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
        
        # Insert test trades
        now = datetime.now()
        trades = [
            (now.strftime('%Y-%m-%d %H:%M:%S'), 'EURUSD', 'BUY', 1, 1, 1.0, 1.16, 1.155, 1.17, 1.165, 50.0, -2.0, -1.0, 300, 'CLOSED', 10009, 'Test', 'Strategy1', 2.0),
            (now.strftime('%Y-%m-%d %H:%M:%S'), 'EURUSD', 'SELL', 2, 2, 1.0, 1.16, 1.165, 1.155, 1.155, 50.0, -2.0, -1.0, 400, 'CLOSED', 10009, 'Test', 'Strategy1', 2.0),
            (now.strftime('%Y-%m-%d %H:%M:%S'), 'EURUSD', 'BUY', 3, 3, 1.0, 1.16, 1.155, 1.17, 1.158, -20.0, -2.0, -1.0, 200, 'CLOSED', 10009, 'Test', 'Strategy2', 2.0),
        ]
        
        for trade in trades:
            cursor.execute("""
                INSERT INTO trades (timestamp, symbol, action, order_id, ticket, volume, 
                                  entry_price, sl, tp, exit_price, profit, commission, swap,
                                  duration_seconds, status, retcode, comment, strategy, risk_reward_ratio)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, trade)
        
        conn.commit()
        conn.close()
    
    def test_analytics_initialization(self, analytics):
        """Test analytics initializes correctly."""
        # Reports dir is created on init
        assert analytics.reports_dir.exists()
        # DB path is set but may not exist until first use
        assert analytics.db_path is not None
    
    def test_basic_statistics(self, analytics):
        """Test basic statistics calculation."""
        self.setup_test_data(analytics)
        
        report = analytics.generate_performance_report(days=7)
        stats = report['basic_statistics']
        
        assert stats['total_trades'] == 3
        assert stats['winning_trades'] == 2
        assert stats['losing_trades'] == 1
        assert abs(stats['win_rate_percent'] - 66.67) < 0.1
        assert stats['total_pnl'] == 80.0
        assert stats['average_pnl'] == pytest.approx(26.67, rel=0.1)
    
    def test_strategy_performance(self, analytics):
        """Test strategy performance analysis."""
        self.setup_test_data(analytics)
        
        report = analytics.generate_performance_report(days=7)
        strategy_stats = report['strategy_performance']
        
        assert 'Strategy1' in strategy_stats
        assert 'Strategy2' in strategy_stats
        
        strategy1 = strategy_stats['Strategy1']
        assert strategy1['total_trades'] == 2
        assert strategy1['winning_trades'] == 2
        assert strategy1['total_pnl'] == 100.0
    
    def test_risk_metrics(self, analytics):
        """Test risk metrics calculation."""
        self.setup_test_data(analytics)
        
        report = analytics.generate_performance_report(days=7)
        risk = report['risk_metrics']
        
        assert 'max_drawdown' in risk
        assert 'sharpe_ratio' in risk
        assert 'consecutive_wins' in risk
        assert 'consecutive_losses' in risk
        
        assert risk['consecutive_wins'] == 2
        assert risk['consecutive_losses'] == 1
    
    def test_report_generation(self, analytics):
        """Test report is generated and saved."""
        self.setup_test_data(analytics)
        
        report = analytics.generate_performance_report(days=7)
        
        # Check report structure
        assert 'report_date' in report
        assert 'period_days' in report
        assert 'basic_statistics' in report
        assert 'strategy_performance' in report
        assert 'risk_metrics' in report
        
        # Check report file was created
        report_files = list(analytics.reports_dir.glob("performance_report_*.json"))
        assert len(report_files) > 0
    
    def test_empty_database(self, analytics):
        """Test analytics handles empty database gracefully."""
        # Setup empty database with table structure
        self.setup_test_data(analytics)

        # Delete all trades to make it empty
        conn = sqlite3.connect(analytics.db_path)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM trades")
        conn.commit()
        conn.close()

        report = analytics.generate_performance_report(days=7)
        stats = report['basic_statistics']

        assert stats['total_trades'] == 0
        assert stats['win_rate_percent'] == 0
        assert stats['total_pnl'] == 0

