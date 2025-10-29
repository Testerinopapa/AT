"""
Integration tests for Milestone 2: Continuous Trading Loop
"""
import pytest
from unittest.mock import patch, Mock, MagicMock, call
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))


class TestPositionTracking:
    """Tests for position tracking functionality."""
    
    @patch('main.mt5')
    def test_get_open_positions_no_filter(self, mock_mt5):
        """Test getting all open positions without filter."""
        from main import get_open_positions
        
        # Mock positions
        pos1 = Mock(symbol="EURUSD", ticket=123)
        pos2 = Mock(symbol="GBPUSD", ticket=456)
        mock_mt5.positions_get.return_value = [pos1, pos2]
        
        positions = get_open_positions()
        
        assert len(positions) == 2
        mock_mt5.positions_get.assert_called_once_with()
    
    @patch('main.mt5')
    def test_get_open_positions_with_symbol_filter(self, mock_mt5):
        """Test getting positions filtered by symbol."""
        from main import get_open_positions
        
        pos1 = Mock(symbol="EURUSD", ticket=123)
        mock_mt5.positions_get.return_value = [pos1]
        
        positions = get_open_positions("EURUSD")
        
        assert len(positions) == 1
        assert positions[0].symbol == "EURUSD"
        mock_mt5.positions_get.assert_called_once_with(symbol="EURUSD")
    
    @patch('main.mt5')
    def test_get_open_positions_empty(self, mock_mt5):
        """Test getting positions when none exist."""
        from main import get_open_positions
        
        mock_mt5.positions_get.return_value = None
        
        positions = get_open_positions()
        
        assert positions == []
    
    @patch('main.mt5')
    def test_has_open_position_true(self, mock_mt5):
        """Test checking for open position when one exists."""
        from main import has_open_position
        
        pos1 = Mock(symbol="EURUSD", ticket=123)
        mock_mt5.positions_get.return_value = [pos1]
        
        result = has_open_position("EURUSD")
        
        assert result is True
    
    @patch('main.mt5')
    def test_has_open_position_false(self, mock_mt5):
        """Test checking for open position when none exists."""
        from main import has_open_position
        
        mock_mt5.positions_get.return_value = []
        
        result = has_open_position("EURUSD")
        
        assert result is False
    
    @patch('main.mt5')
    def test_can_open_new_trade_under_limit(self, mock_mt5):
        """Test can open trade when under limit."""
        from main import can_open_new_trade
        
        # Mock 2 open positions (limit is 3)
        pos1 = Mock(symbol="EURUSD", ticket=123)
        pos2 = Mock(symbol="GBPUSD", ticket=456)
        mock_mt5.positions_get.return_value = [pos1, pos2]
        
        result = can_open_new_trade()
        
        assert result is True
    
    @patch('main.mt5')
    def test_can_open_new_trade_at_limit(self, mock_mt5):
        """Test cannot open trade when at limit."""
        from main import can_open_new_trade
        
        # Mock 3 open positions (limit is 3)
        pos1 = Mock(symbol="EURUSD", ticket=123)
        pos2 = Mock(symbol="GBPUSD", ticket=456)
        pos3 = Mock(symbol="USDJPY", ticket=789)
        mock_mt5.positions_get.return_value = [pos1, pos2, pos3]
        
        result = can_open_new_trade()
        
        assert result is False


class TestTradeExecution:
    """Tests for trade execution with new structure."""
    
    @patch('main.mt5')
    @patch('main.log_trade')
    def test_execute_trade_buy_success(self, mock_log, mock_mt5):
        """Test successful BUY trade execution."""
        from main import execute_trade
        
        # Mock tick data
        tick = Mock()
        tick.ask = 1.16045
        tick.bid = 1.16025
        mock_mt5.symbol_info_tick.return_value = tick
        
        # Mock successful order
        result = Mock()
        result.retcode = 10009  # TRADE_RETCODE_DONE
        result.order = 123456789
        result.price = 1.16045
        mock_mt5.order_send.return_value = result
        mock_mt5.TRADE_RETCODE_DONE = 10009
        mock_mt5.ORDER_TYPE_BUY = 0
        mock_mt5.TRADE_ACTION_DEAL = 1
        mock_mt5.ORDER_TIME_GTC = 0
        mock_mt5.ORDER_FILLING_FOK = 1
        
        success = execute_trade("EURUSD", "BUY")
        
        assert success is True
        mock_log.assert_called_once()
    
    @patch('main.mt5')
    @patch('main.log_trade')
    def test_execute_trade_sell_success(self, mock_log, mock_mt5):
        """Test successful SELL trade execution."""
        from main import execute_trade
        
        # Mock tick data
        tick = Mock()
        tick.ask = 1.16045
        tick.bid = 1.16025
        mock_mt5.symbol_info_tick.return_value = tick
        
        # Mock successful order
        result = Mock()
        result.retcode = 10009
        result.order = 123456789
        result.price = 1.16025
        mock_mt5.order_send.return_value = result
        mock_mt5.TRADE_RETCODE_DONE = 10009
        mock_mt5.ORDER_TYPE_SELL = 1
        mock_mt5.TRADE_ACTION_DEAL = 1
        mock_mt5.ORDER_TIME_GTC = 0
        mock_mt5.ORDER_FILLING_FOK = 1
        
        success = execute_trade("EURUSD", "SELL")
        
        assert success is True
        mock_log.assert_called_once()
    
    @patch('main.mt5')
    def test_execute_trade_no_tick_data(self, mock_mt5):
        """Test trade execution fails when tick data unavailable."""
        from main import execute_trade
        
        mock_mt5.symbol_info_tick.return_value = None
        
        success = execute_trade("EURUSD", "BUY")
        
        assert success is False
    
    @patch('main.mt5')
    @patch('main.log_trade')
    def test_execute_trade_order_failed(self, mock_log, mock_mt5):
        """Test trade execution when order fails."""
        from main import execute_trade
        
        # Mock tick data
        tick = Mock()
        tick.ask = 1.16045
        tick.bid = 1.16025
        mock_mt5.symbol_info_tick.return_value = tick
        
        # Mock failed order
        result = Mock()
        result.retcode = 10013  # Invalid request
        result.order = 0
        result.comment = "Invalid volume"
        mock_mt5.order_send.return_value = result
        mock_mt5.TRADE_RETCODE_DONE = 10009
        mock_mt5.ORDER_TYPE_BUY = 0
        mock_mt5.TRADE_ACTION_DEAL = 1
        mock_mt5.ORDER_TIME_GTC = 0
        mock_mt5.ORDER_FILLING_FOK = 1
        
        success = execute_trade("EURUSD", "BUY")
        
        assert success is False
        mock_log.assert_called_once()


class TestTradingIteration:
    """Tests for trading iteration logic."""
    
    @patch('main.execute_trade')
    @patch('main.trade_decision')
    @patch('main.has_open_position')
    @patch('main.can_open_new_trade')
    def test_trading_iteration_executes_buy(self, mock_can_trade, mock_has_pos, 
                                           mock_decision, mock_execute):
        """Test trading iteration executes BUY signal."""
        from main import trading_iteration
        
        mock_has_pos.return_value = False
        mock_can_trade.return_value = True
        mock_decision.return_value = "BUY"
        mock_execute.return_value = True
        
        trading_iteration("EURUSD")
        
        mock_execute.assert_called_once_with("EURUSD", "BUY")
    
    @patch('main.execute_trade')
    @patch('main.trade_decision')
    @patch('main.has_open_position')
    @patch('main.can_open_new_trade')
    def test_trading_iteration_skips_if_position_exists(self, mock_can_trade, mock_has_pos,
                                                        mock_decision, mock_execute):
        """Test trading iteration skips when position already exists."""
        from main import trading_iteration
        
        mock_has_pos.return_value = True
        
        trading_iteration("EURUSD")
        
        mock_execute.assert_not_called()
        mock_decision.assert_not_called()
    
    @patch('main.execute_trade')
    @patch('main.trade_decision')
    @patch('main.has_open_position')
    @patch('main.can_open_new_trade')
    def test_trading_iteration_skips_if_max_trades_reached(self, mock_can_trade, mock_has_pos,
                                                           mock_decision, mock_execute):
        """Test trading iteration skips when max trades reached."""
        from main import trading_iteration
        
        mock_has_pos.return_value = False
        mock_can_trade.return_value = False
        
        trading_iteration("EURUSD")
        
        mock_execute.assert_not_called()
        mock_decision.assert_not_called()
    
    @patch('main.execute_trade')
    @patch('main.trade_decision')
    @patch('main.has_open_position')
    @patch('main.can_open_new_trade')
    def test_trading_iteration_skips_on_no_signal(self, mock_can_trade, mock_has_pos,
                                                  mock_decision, mock_execute):
        """Test trading iteration skips when no signal."""
        from main import trading_iteration
        
        mock_has_pos.return_value = False
        mock_can_trade.return_value = True
        mock_decision.return_value = "NONE"
        
        trading_iteration("EURUSD")
        
        mock_execute.assert_not_called()


class TestInitialization:
    """Tests for initialization functions."""
    
    @patch('main.mt5')
    def test_initialize_mt5_success(self, mock_mt5):
        """Test successful MT5 initialization."""
        from main import initialize_mt5
        
        mock_mt5.initialize.return_value = True
        account_info = Mock()
        account_info.login = 12345678
        account_info.balance = 10000.0
        mock_mt5.account_info.return_value = account_info
        
        result = initialize_mt5()
        
        assert result is True
    
    @patch('main.mt5')
    def test_initialize_mt5_failed(self, mock_mt5):
        """Test failed MT5 initialization."""
        from main import initialize_mt5
        
        mock_mt5.initialize.return_value = False
        
        result = initialize_mt5()
        
        assert result is False
    
    @patch('main.mt5')
    def test_prepare_symbol_success(self, mock_mt5):
        """Test successful symbol preparation."""
        from main import prepare_symbol
        
        mock_mt5.symbol_select.return_value = True
        symbol_info = Mock()
        symbol_info.name = "EURUSD"
        mock_mt5.symbol_info.return_value = symbol_info
        
        result = prepare_symbol("EURUSD")
        
        assert result is True
    
    @patch('main.mt5')
    def test_prepare_symbol_failed(self, mock_mt5):
        """Test failed symbol preparation."""
        from main import prepare_symbol
        
        mock_mt5.symbol_select.return_value = False
        
        result = prepare_symbol("EURUSD")
        
        assert result is False

