"""
Pytest configuration and shared fixtures for TraderBot tests.
"""
import pytest
import sys
import os
from unittest.mock import Mock, MagicMock
import numpy as np

# Add parent directory to path for imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))


@pytest.fixture
def mock_mt5():
    """Mock MetaTrader5 module for testing without actual MT5 connection."""
    mt5_mock = MagicMock()
    
    # Mock initialization
    mt5_mock.initialize.return_value = True
    mt5_mock.shutdown.return_value = None
    mt5_mock.last_error.return_value = (0, "Success")
    
    # Mock account info
    account_info = Mock()
    account_info.login = 12345678
    account_info.balance = 10000.0
    account_info.equity = 10000.0
    account_info.margin = 0.0
    account_info.margin_free = 10000.0
    mt5_mock.account_info.return_value = account_info
    
    # Mock symbol selection
    mt5_mock.symbol_select.return_value = True
    
    # Mock symbol info
    symbol_info = Mock()
    symbol_info.name = "EURUSD"
    symbol_info.digits = 5
    symbol_info.point = 0.00001
    symbol_info.volume_min = 0.01
    symbol_info.volume_max = 100.0
    symbol_info.volume_step = 0.01
    mt5_mock.symbol_info.return_value = symbol_info
    
    # Mock tick info
    tick = Mock()
    tick.ask = 1.16045
    tick.bid = 1.16025
    tick.time = 1234567890
    mt5_mock.symbol_info_tick.return_value = tick
    
    # Mock order send
    order_result = Mock()
    order_result.retcode = 10009  # TRADE_RETCODE_DONE
    order_result.order = 123456789
    order_result.price = 1.16045
    order_result.volume = 0.1
    order_result.comment = "Success"
    mt5_mock.order_send.return_value = order_result
    
    # Mock positions
    mt5_mock.positions_get.return_value = []
    
    # Mock constants
    mt5_mock.TIMEFRAME_M1 = 1
    mt5_mock.TIMEFRAME_M5 = 5
    mt5_mock.TIMEFRAME_M15 = 15
    mt5_mock.TIMEFRAME_H1 = 60
    mt5_mock.ORDER_TYPE_BUY = 0
    mt5_mock.ORDER_TYPE_SELL = 1
    mt5_mock.TRADE_ACTION_DEAL = 1
    mt5_mock.ORDER_TIME_GTC = 0
    mt5_mock.ORDER_FILLING_FOK = 1
    mt5_mock.ORDER_FILLING_IOC = 2
    mt5_mock.TRADE_RETCODE_DONE = 10009
    
    return mt5_mock


@pytest.fixture
def mock_rates_data():
    """Generate mock price data for testing strategies."""
    def _generate_rates(pattern="uptrend", num_candles=20):
        """
        Generate mock OHLC data.
        
        Args:
            pattern: 'uptrend', 'downtrend', 'sideways', 'volatile'
            num_candles: Number of candles to generate
        """
        base_price = 1.16000
        rates = []
        
        for i in range(num_candles):
            if pattern == "uptrend":
                close = base_price + (i * 0.00010)
                open_price = close - 0.00005
            elif pattern == "downtrend":
                close = base_price - (i * 0.00010)
                open_price = close + 0.00005
            elif pattern == "sideways":
                close = base_price + (0.00005 if i % 2 == 0 else -0.00005)
                open_price = base_price
            else:  # volatile
                close = base_price + (np.random.randn() * 0.00020)
                open_price = close + (np.random.randn() * 0.00010)
            
            high = max(open_price, close) + 0.00003
            low = min(open_price, close) - 0.00003
            
            rates.append((
                1234567890 + (i * 60),  # time
                open_price,              # open
                high,                    # high
                low,                     # low
                close,                   # close
                100,                     # tick_volume
                2,                       # spread
                0                        # real_volume
            ))

        return np.array(rates, dtype=[
            ('time', 'i8'), ('open', 'f8'), ('high', 'f8'),
            ('low', 'f8'), ('close', 'f8'), ('tick_volume', 'i8'),
            ('spread', 'i4'), ('real_volume', 'i8')
        ])
    
    return _generate_rates


@pytest.fixture
def sample_config():
    """Sample configuration for testing."""
    return {
        "symbol": "EURUSD",
        "volume": 0.1,
        "deviation": 50,
        "trade_interval_seconds": 60,
        "max_concurrent_trades": 3,
        "risk_percentage": 1.0,
        "daily_loss_limit": 100.0,
        "daily_profit_target": 200.0
    }


@pytest.fixture
def temp_log_file(tmp_path):
    """Create a temporary log file for testing."""
    log_file = tmp_path / "test_trades.log"
    return str(log_file)


@pytest.fixture
def temp_config_file(tmp_path, sample_config):
    """Create a temporary config file for testing."""
    import json
    config_file = tmp_path / "settings.json"
    with open(config_file, 'w') as f:
        json.dump(sample_config, f)
    return str(config_file)

