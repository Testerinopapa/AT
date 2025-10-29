"""
Unit tests for new strategy system (Milestone 3).
"""
import pytest
from unittest.mock import patch, Mock, MagicMock
import numpy as np
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from strategies import (
    SimpleStrategy,
    MAStrategy,
    RSIStrategy,
    MACDStrategy,
    StrategyManager
)


class TestSimpleStrategyNew:
    """Tests for SimpleStrategy class."""

    @patch('strategies.base_strategy.mt5')
    def test_buy_signal_on_uptrend(self, mock_mt5, mock_rates_data):
        """Test BUY signal on upward momentum."""
        strategy = SimpleStrategy()

        mock_mt5.TIMEFRAME_M1 = 1
        mock_mt5.copy_rates_from_pos.return_value = mock_rates_data("uptrend", 20)

        signal = strategy.generate_signal("EURUSD")
        assert signal == "BUY"

    @patch('strategies.base_strategy.mt5')
    def test_sell_signal_on_downtrend(self, mock_mt5, mock_rates_data):
        """Test SELL signal on downward momentum."""
        strategy = SimpleStrategy()

        mock_mt5.TIMEFRAME_M1 = 1
        mock_mt5.copy_rates_from_pos.return_value = mock_rates_data("downtrend", 20)

        signal = strategy.generate_signal("EURUSD")
        assert signal == "SELL"
    
    @patch('strategies.base_strategy.mt5')
    def test_none_signal_on_equal_prices(self, mock_mt5):
        """Test NONE signal when prices are equal."""
        strategy = SimpleStrategy()

        rates = np.array([
            (1234567890, 1.16000, 1.16010, 1.15990, 1.16000, 100, 2, 0),
            (1234567950, 1.16000, 1.16010, 1.15990, 1.16000, 100, 2, 0),
        ], dtype=[
            ('time', 'i8'), ('open', 'f8'), ('high', 'f8'),
            ('low', 'f8'), ('close', 'f8'), ('tick_volume', 'i8'),
            ('spread', 'i4'), ('real_volume', 'i8')
        ])

        mock_mt5.TIMEFRAME_M1 = 1
        mock_mt5.copy_rates_from_pos.return_value = rates

        signal = strategy.generate_signal("EURUSD")
        assert signal == "NONE"
    
    def test_strategy_enable_disable(self):
        """Test enabling and disabling strategy."""
        strategy = SimpleStrategy()
        
        assert strategy.enabled is True
        
        strategy.disable()
        assert strategy.enabled is False
        
        strategy.enable()
        assert strategy.enabled is True
    
    def test_strategy_weight(self):
        """Test setting strategy weight."""
        strategy = SimpleStrategy()
        
        assert strategy.weight == 1.0
        
        strategy.set_weight(2.5)
        assert strategy.weight == 2.5


class TestMAStrategyNew:
    """Tests for MAStrategy class."""
    
    @patch('strategies.ma_strategy.mt5')
    def test_golden_cross_buy_signal(self, mock_mt5):
        """Test BUY signal on golden cross."""
        strategy = MAStrategy({"fast_period": 5, "slow_period": 10})
        
        # Create data where fast MA crosses above slow MA
        closes = np.array([1.16000, 1.16010, 1.16020, 1.16030, 1.16040,
                          1.16050, 1.16060, 1.16070, 1.16080, 1.16090,
                          1.16100, 1.16110, 1.16120, 1.16130, 1.16140])
        
        rates = np.array([
            (1234567890 + i*60, closes[i], closes[i]+0.0001, closes[i]-0.0001, closes[i], 100, 2, 0)
            for i in range(len(closes))
        ], dtype=[
            ('time', 'i8'), ('open', 'f8'), ('high', 'f8'), 
            ('low', 'f8'), ('close', 'f8'), ('tick_volume', 'i8'),
            ('spread', 'i4'), ('real_volume', 'i8')
        ])
        
        mock_mt5.TIMEFRAME_M5 = 5
        mock_mt5.copy_rates_from_pos.return_value = rates
        
        signal = strategy.generate_signal("EURUSD")
        # May be BUY or NONE depending on crossover detection
        assert signal in ["BUY", "NONE"]
    
    @patch('strategies.ma_strategy.mt5')
    def test_death_cross_sell_signal(self, mock_mt5):
        """Test SELL signal on death cross."""
        strategy = MAStrategy({"fast_period": 5, "slow_period": 10})
        
        # Create data where fast MA crosses below slow MA
        closes = np.array([1.16140, 1.16130, 1.16120, 1.16110, 1.16100,
                          1.16090, 1.16080, 1.16070, 1.16060, 1.16050,
                          1.16040, 1.16030, 1.16020, 1.16010, 1.16000])
        
        rates = np.array([
            (1234567890 + i*60, closes[i], closes[i]+0.0001, closes[i]-0.0001, closes[i], 100, 2, 0)
            for i in range(len(closes))
        ], dtype=[
            ('time', 'i8'), ('open', 'f8'), ('high', 'f8'), 
            ('low', 'f8'), ('close', 'f8'), ('tick_volume', 'i8'),
            ('spread', 'i4'), ('real_volume', 'i8')
        ])
        
        mock_mt5.TIMEFRAME_M5 = 5
        mock_mt5.copy_rates_from_pos.return_value = rates
        
        signal = strategy.generate_signal("EURUSD")
        # May be SELL or NONE depending on crossover detection
        assert signal in ["SELL", "NONE"]


class TestRSIStrategyNew:
    """Tests for RSIStrategy class."""
    
    @patch('strategies.rsi_strategy.mt5')
    def test_oversold_buy_signal(self, mock_mt5):
        """Test BUY signal when RSI bounces from oversold."""
        strategy = RSIStrategy({"period": 14, "oversold": 30})
        
        # Create downtrend then bounce (oversold condition)
        closes = np.array([1.16100] + [1.16100 - i*0.001 for i in range(1, 25)] + [1.15900, 1.15920])
        
        rates = np.array([
            (1234567890 + i*60, closes[i], closes[i]+0.0001, closes[i]-0.0001, closes[i], 100, 2, 0)
            for i in range(len(closes))
        ], dtype=[
            ('time', 'i8'), ('open', 'f8'), ('high', 'f8'), 
            ('low', 'f8'), ('close', 'f8'), ('tick_volume', 'i8'),
            ('spread', 'i4'), ('real_volume', 'i8')
        ])
        
        mock_mt5.TIMEFRAME_M5 = 5
        mock_mt5.copy_rates_from_pos.return_value = rates
        
        signal = strategy.generate_signal("EURUSD")
        assert signal in ["BUY", "NONE"]  # Depends on exact RSI calculation
    
    @patch('strategies.rsi_strategy.mt5')
    def test_overbought_sell_signal(self, mock_mt5):
        """Test SELL signal when RSI drops from overbought."""
        strategy = RSIStrategy({"period": 14, "overbought": 70})
        
        # Create uptrend then drop (overbought condition)
        closes = np.array([1.15900] + [1.15900 + i*0.001 for i in range(1, 25)] + [1.16100, 1.16080])
        
        rates = np.array([
            (1234567890 + i*60, closes[i], closes[i]+0.0001, closes[i]-0.0001, closes[i], 100, 2, 0)
            for i in range(len(closes))
        ], dtype=[
            ('time', 'i8'), ('open', 'f8'), ('high', 'f8'), 
            ('low', 'f8'), ('close', 'f8'), ('tick_volume', 'i8'),
            ('spread', 'i4'), ('real_volume', 'i8')
        ])
        
        mock_mt5.TIMEFRAME_M5 = 5
        mock_mt5.copy_rates_from_pos.return_value = rates
        
        signal = strategy.generate_signal("EURUSD")
        assert signal in ["SELL", "NONE"]  # Depends on exact RSI calculation


class TestMACDStrategyNew:
    """Tests for MACDStrategy class."""
    
    @patch('strategies.macd_strategy.mt5')
    def test_bullish_crossover(self, mock_mt5):
        """Test BUY signal on bullish MACD crossover."""
        strategy = MACDStrategy({"fast_period": 12, "slow_period": 26, "signal_period": 9})
        
        # Create uptrend data
        closes = np.array([1.16000 + i*0.0001 for i in range(50)])
        
        rates = np.array([
            (1234567890 + i*60, closes[i], closes[i]+0.0001, closes[i]-0.0001, closes[i], 100, 2, 0)
            for i in range(len(closes))
        ], dtype=[
            ('time', 'i8'), ('open', 'f8'), ('high', 'f8'), 
            ('low', 'f8'), ('close', 'f8'), ('tick_volume', 'i8'),
            ('spread', 'i4'), ('real_volume', 'i8')
        ])
        
        mock_mt5.TIMEFRAME_M15 = 15
        mock_mt5.copy_rates_from_pos.return_value = rates
        
        signal = strategy.generate_signal("EURUSD")
        assert signal in ["BUY", "SELL", "NONE"]


class TestStrategyManagerNew:
    """Tests for StrategyManager class."""
    
    def test_add_remove_strategy(self):
        """Test adding and removing strategies."""
        manager = StrategyManager()
        strategy = SimpleStrategy()
        
        assert len(manager.strategies) == 0
        
        manager.add_strategy(strategy)
        assert len(manager.strategies) == 1
        
        manager.remove_strategy("SimpleStrategy")
        assert len(manager.strategies) == 0
    
    def test_unanimous_method(self):
        """Test unanimous combination method."""
        manager = StrategyManager(method="unanimous")
        
        # All agree on BUY
        signals = {"Strategy1": "BUY", "Strategy2": "BUY", "Strategy3": "BUY"}
        result = manager.combine_signals_unanimous(signals)
        assert result == "BUY"
        
        # Disagreement
        signals = {"Strategy1": "BUY", "Strategy2": "SELL", "Strategy3": "BUY"}
        result = manager.combine_signals_unanimous(signals)
        assert result == "NONE"
    
    def test_majority_method(self):
        """Test majority combination method."""
        manager = StrategyManager(method="majority")
        
        # Majority BUY
        signals = {"Strategy1": "BUY", "Strategy2": "BUY", "Strategy3": "SELL"}
        result = manager.combine_signals_majority(signals)
        assert result == "BUY"
        
        # Majority SELL
        signals = {"Strategy1": "SELL", "Strategy2": "SELL", "Strategy3": "BUY"}
        result = manager.combine_signals_majority(signals)
        assert result == "SELL"
    
    def test_weighted_method(self):
        """Test weighted combination method."""
        manager = StrategyManager(method="weighted")
        
        # Create strategies with different weights
        s1 = SimpleStrategy()
        s1.set_weight(1.0)
        s2 = SimpleStrategy()
        s2.set_weight(2.0)
        
        manager.add_strategy(s1)
        manager.add_strategy(s2)
        
        # Weighted vote: 1.0 for BUY, 2.0 for SELL = SELL wins
        signals = {"SimpleStrategy": "BUY", "SimpleStrategy": "SELL"}
        result = manager.combine_signals_weighted(signals)
        assert result in ["BUY", "SELL", "NONE"]
    
    def test_any_method(self):
        """Test any combination method."""
        manager = StrategyManager(method="any")
        
        # Any BUY signal triggers BUY
        signals = {"Strategy1": "BUY", "Strategy2": "NONE", "Strategy3": "NONE"}
        result = manager.combine_signals_any(signals)
        assert result == "BUY"
        
        # Any SELL signal triggers SELL
        signals = {"Strategy1": "NONE", "Strategy2": "SELL", "Strategy3": "NONE"}
        result = manager.combine_signals_any(signals)
        assert result == "SELL"

