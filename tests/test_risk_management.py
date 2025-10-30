"""
Tests for Risk Management Module

Tests cover:
- Dynamic lot sizing
- SL/TP calculation (fixed pips, ATR, percentage)
- Daily loss/profit limits
- P/L tracking
- Trade validation
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
import numpy as np
from datetime import date
import json
import os
import tempfile

# Import the module to test
from risk_manager import RiskManager


@pytest.fixture
def mock_mt5():
    """Mock MT5 module."""
    with patch('risk_manager.mt5') as mock:
        # Mock account info
        mock_account = Mock()
        mock_account.balance = 10000.0
        mock.account_info.return_value = mock_account
        
        # Mock symbol info
        mock_symbol = Mock()
        mock_symbol.point = 0.00001
        mock_symbol.digits = 5
        mock_symbol.trade_contract_size = 100000
        mock_symbol.volume_min = 0.01
        mock_symbol.volume_max = 100.0
        mock_symbol.volume_step = 0.01
        mock.symbol_info.return_value = mock_symbol
        
        # Mock tick info
        mock_tick = Mock()
        mock_tick.ask = 1.16000
        mock_tick.bid = 1.15990
        mock.symbol_info_tick.return_value = mock_tick
        
        # Mock timeframe constants
        mock.TIMEFRAME_H1 = 16385
        
        yield mock


@pytest.fixture
def temp_pnl_file():
    """Create temporary P/L file."""
    fd, path = tempfile.mkstemp(suffix='.json')
    os.close(fd)
    with open(path, 'w') as f:
        json.dump({}, f)
    yield path
    os.unlink(path)


@pytest.fixture
def risk_config():
    """Standard risk management configuration."""
    return {
        "risk_management": {
            "risk_percentage": 1.0,
            "max_risk_percentage": 5.0,
            "min_lot_size": 0.01,
            "max_lot_size": 1.0,
            "sl_method": "fixed_pips",
            "tp_method": "fixed_pips",
            "fixed_sl_pips": 100,
            "fixed_tp_pips": 200,
            "atr_period": 14,
            "atr_sl_multiplier": 2.0,
            "atr_tp_multiplier": 3.0,
            "sl_percentage": 0.5,
            "tp_percentage": 1.0,
            "daily_loss_limit": 500.0,
            "daily_profit_target": 1000.0,
            "enable_daily_limits": True,
            "enable_dynamic_lot_sizing": True
        }
    }


@pytest.fixture
def risk_manager(risk_config, temp_pnl_file):
    """Create RiskManager instance with temp file."""
    manager = RiskManager(risk_config)
    manager.daily_pnl_file = temp_pnl_file
    return manager


# ============================================================
# Test: Initialization
# ============================================================

def test_risk_manager_initialization(risk_manager):
    """Test RiskManager initializes with correct parameters."""
    assert risk_manager.risk_percentage == 1.0
    assert risk_manager.max_risk_percentage == 5.0
    assert risk_manager.min_lot_size == 0.01
    assert risk_manager.max_lot_size == 1.0
    assert risk_manager.sl_method == "fixed_pips"
    assert risk_manager.tp_method == "fixed_pips"
    assert risk_manager.fixed_sl_pips == 100
    assert risk_manager.fixed_tp_pips == 200
    assert risk_manager.daily_loss_limit == 500.0
    assert risk_manager.daily_profit_target == 1000.0
    assert risk_manager.enable_daily_limits == True


# ============================================================
# Test: Dynamic Lot Sizing
# ============================================================

def test_calculate_lot_size_basic(risk_manager, mock_mt5):
    """Test basic lot size calculation."""
    # Account balance: 10000, Risk: 1% = 100
    # SL: 100 pips, Pip value: 1 (for 1 lot)
    # Expected: 100 / (100 * 1) = 1.0 lot (capped at max_lot_size)
    lot_size = risk_manager.calculate_lot_size("EURUSD", 100, 10000.0)
    
    assert lot_size >= risk_manager.min_lot_size
    assert lot_size <= risk_manager.max_lot_size


def test_calculate_lot_size_respects_min_max(risk_manager, mock_mt5):
    """Test lot size respects min/max constraints."""
    # Very small SL should give large lot size (capped at max)
    lot_size_small_sl = risk_manager.calculate_lot_size("EURUSD", 10, 10000.0)
    assert lot_size_small_sl <= risk_manager.max_lot_size
    
    # Very large SL should give small lot size (capped at min)
    lot_size_large_sl = risk_manager.calculate_lot_size("EURUSD", 1000, 10000.0)
    assert lot_size_large_sl >= risk_manager.min_lot_size


def test_calculate_lot_size_invalid_sl(risk_manager, mock_mt5):
    """Test lot size calculation with invalid SL returns min lot."""
    lot_size = risk_manager.calculate_lot_size("EURUSD", 0, 10000.0)
    assert lot_size == risk_manager.min_lot_size
    
    lot_size = risk_manager.calculate_lot_size("EURUSD", -50, 10000.0)
    assert lot_size == risk_manager.min_lot_size


def test_calculate_lot_size_no_account_info(risk_manager, mock_mt5):
    """Test lot size calculation when account info unavailable."""
    mock_mt5.account_info.return_value = None
    lot_size = risk_manager.calculate_lot_size("EURUSD", 100)
    assert lot_size == risk_manager.min_lot_size


# ============================================================
# Test: ATR Calculation
# ============================================================

def test_calculate_atr_basic(risk_manager, mock_mt5):
    """Test ATR calculation with mock data."""
    # Create mock rates data
    mock_rates = np.array([
        (1.16000, 1.16100, 1.15900, 1.16050),
        (1.16050, 1.16150, 1.15950, 1.16100),
        (1.16100, 1.16200, 1.16000, 1.16150),
        (1.16150, 1.16250, 1.16050, 1.16200),
        (1.16200, 1.16300, 1.16100, 1.16250),
        (1.16250, 1.16350, 1.16150, 1.16300),
        (1.16300, 1.16400, 1.16200, 1.16350),
        (1.16350, 1.16450, 1.16250, 1.16400),
        (1.16400, 1.16500, 1.16300, 1.16450),
        (1.16450, 1.16550, 1.16350, 1.16500),
        (1.16500, 1.16600, 1.16400, 1.16550),
        (1.16550, 1.16650, 1.16450, 1.16600),
        (1.16600, 1.16700, 1.16500, 1.16650),
        (1.16650, 1.16750, 1.16550, 1.16700),
        (1.16700, 1.16800, 1.16600, 1.16750),
    ], dtype=[('open', 'f8'), ('high', 'f8'), ('low', 'f8'), ('close', 'f8')])
    
    mock_mt5.copy_rates_from_pos.return_value = mock_rates
    
    atr = risk_manager.calculate_atr("EURUSD", period=14)
    
    assert atr is not None
    assert atr > 0
    assert isinstance(atr, float)


def test_calculate_atr_insufficient_data(risk_manager, mock_mt5):
    """Test ATR calculation with insufficient data."""
    mock_mt5.copy_rates_from_pos.return_value = None
    atr = risk_manager.calculate_atr("EURUSD")
    assert atr is None


def test_calculate_atr_caching(risk_manager, mock_mt5):
    """Test ATR caching mechanism."""
    mock_rates = np.array([
        (1.16000, 1.16100, 1.15900, 1.16050),
        (1.16050, 1.16150, 1.15950, 1.16100),
        (1.16100, 1.16200, 1.16000, 1.16150),
        (1.16150, 1.16250, 1.16050, 1.16200),
        (1.16200, 1.16300, 1.16100, 1.16250),
        (1.16250, 1.16350, 1.16150, 1.16300),
        (1.16300, 1.16400, 1.16200, 1.16350),
        (1.16350, 1.16450, 1.16250, 1.16400),
        (1.16400, 1.16500, 1.16300, 1.16450),
        (1.16450, 1.16550, 1.16350, 1.16500),
        (1.16500, 1.16600, 1.16400, 1.16550),
        (1.16550, 1.16650, 1.16450, 1.16600),
        (1.16600, 1.16700, 1.16500, 1.16650),
        (1.16650, 1.16750, 1.16550, 1.16700),
        (1.16700, 1.16800, 1.16600, 1.16750),
    ], dtype=[('open', 'f8'), ('high', 'f8'), ('low', 'f8'), ('close', 'f8')])
    
    mock_mt5.copy_rates_from_pos.return_value = mock_rates
    
    # First call
    atr1 = risk_manager.calculate_atr("EURUSD")
    
    # Second call (should use cache)
    atr2 = risk_manager.calculate_atr("EURUSD")
    
    assert atr1 == atr2
    # Should only call copy_rates_from_pos once
    assert mock_mt5.copy_rates_from_pos.call_count == 1


# ============================================================
# Test: SL/TP Calculation
# ============================================================

def test_calculate_sl_tp_fixed_pips_buy(risk_manager, mock_mt5):
    """Test SL/TP calculation with fixed pips for BUY."""
    sl, tp = risk_manager.calculate_sl_tp("EURUSD", "BUY", 1.16000)
    
    # SL should be below entry, TP should be above
    assert sl < 1.16000
    assert tp > 1.16000
    # TP should be further than SL (2:1 ratio)
    assert (tp - 1.16000) > (1.16000 - sl)


def test_calculate_sl_tp_fixed_pips_sell(risk_manager, mock_mt5):
    """Test SL/TP calculation with fixed pips for SELL."""
    sl, tp = risk_manager.calculate_sl_tp("EURUSD", "SELL", 1.16000)
    
    # SL should be above entry, TP should be below
    assert sl > 1.16000
    assert tp < 1.16000
    # TP should be further than SL (2:1 ratio)
    assert (1.16000 - tp) > (sl - 1.16000)


def test_calculate_sl_tp_percentage_method(risk_manager, mock_mt5):
    """Test SL/TP calculation with percentage method."""
    risk_manager.sl_method = "percentage"
    risk_manager.tp_method = "percentage"
    risk_manager.sl_percentage = 0.5  # 0.5%
    risk_manager.tp_percentage = 1.0  # 1.0%
    
    entry_price = 1.16000
    sl, tp = risk_manager.calculate_sl_tp("EURUSD", "BUY", entry_price)
    
    # Check SL is approximately 0.5% below entry
    expected_sl = entry_price * (1 - 0.005)
    assert abs(sl - expected_sl) < 0.0001
    
    # Check TP is approximately 1.0% above entry
    expected_tp = entry_price * (1 + 0.01)
    assert abs(tp - expected_tp) < 0.0001


# ============================================================
# Test: Daily P/L Tracking
# ============================================================

def test_get_daily_pnl_empty(risk_manager):
    """Test getting daily P/L when no data exists."""
    pnl = risk_manager.get_daily_pnl()
    assert pnl == 0.0


def test_update_daily_pnl(risk_manager):
    """Test updating daily P/L."""
    risk_manager.update_daily_pnl(50.0)
    pnl = risk_manager.get_daily_pnl()
    assert pnl == 50.0
    
    risk_manager.update_daily_pnl(-20.0)
    pnl = risk_manager.get_daily_pnl()
    assert pnl == 30.0


def test_daily_pnl_persistence(risk_manager, temp_pnl_file):
    """Test daily P/L persists across instances."""
    risk_manager.update_daily_pnl(100.0)
    
    # Create new instance with same file
    new_manager = RiskManager(risk_manager.config)
    new_manager.daily_pnl_file = temp_pnl_file
    
    pnl = new_manager.get_daily_pnl()
    assert pnl == 100.0


# ============================================================
# Test: Daily Limits
# ============================================================

def test_can_trade_within_limits(risk_manager):
    """Test trading allowed when within limits."""
    risk_manager.update_daily_pnl(100.0)  # Profit but below target
    can_trade, reason = risk_manager.can_trade()
    assert can_trade == True


def test_can_trade_loss_limit_reached(risk_manager):
    """Test trading disabled when loss limit reached."""
    risk_manager.update_daily_pnl(-500.0)  # Hit loss limit
    can_trade, reason = risk_manager.can_trade()
    assert can_trade == False
    assert "loss limit" in reason.lower()


def test_can_trade_profit_target_reached(risk_manager):
    """Test trading disabled when profit target reached."""
    risk_manager.update_daily_pnl(1000.0)  # Hit profit target
    can_trade, reason = risk_manager.can_trade()
    assert can_trade == False
    assert "profit target" in reason.lower()


def test_can_trade_limits_disabled(risk_manager):
    """Test trading always allowed when limits disabled."""
    risk_manager.enable_daily_limits = False
    risk_manager.update_daily_pnl(-1000.0)  # Way over loss limit
    can_trade, reason = risk_manager.can_trade()
    assert can_trade == True


# ============================================================
# Test: Trade Validation
# ============================================================

def test_validate_trade_success(risk_manager, mock_mt5):
    """Test trade validation passes with valid parameters."""
    is_valid, reason = risk_manager.validate_trade("EURUSD", "BUY", 0.1)
    assert is_valid == True


def test_validate_trade_lot_too_small(risk_manager, mock_mt5):
    """Test trade validation fails with lot size too small."""
    is_valid, reason = risk_manager.validate_trade("EURUSD", "BUY", 0.001)
    assert is_valid == False
    assert "minimum" in reason.lower()


def test_validate_trade_lot_too_large(risk_manager, mock_mt5):
    """Test trade validation fails with lot size too large."""
    is_valid, reason = risk_manager.validate_trade("EURUSD", "BUY", 10.0)
    assert is_valid == False
    assert "maximum" in reason.lower()


def test_validate_trade_daily_limit_reached(risk_manager, mock_mt5):
    """Test trade validation fails when daily limit reached."""
    risk_manager.update_daily_pnl(-500.0)  # Hit loss limit
    is_valid, reason = risk_manager.validate_trade("EURUSD", "BUY", 0.1)
    assert is_valid == False
    assert "loss limit" in reason.lower()

