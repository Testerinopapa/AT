# TraderBot Test Suite

Comprehensive test suite for the TraderBot MetaTrader 5 automated trading system.

## Test Structure

```
tests/
├── __init__.py              # Test package initialization
├── conftest.py              # Shared pytest fixtures and configuration
├── test_main.py             # Tests for main bot functionality
├── test_strategy.py         # Tests for trading strategies
├── test_milestone2.py       # Tests for Milestone 2 features
└── README.md                # This file
```

## Running Tests

### Run All Tests
```bash
pytest tests/ -v
```

### Run Specific Test File
```bash
pytest tests/test_strategy.py -v
pytest tests/test_milestone2.py -v
```

### Run Specific Test Class
```bash
pytest tests/test_strategy.py::TestSimpleStrategy -v
```

### Run Specific Test
```bash
pytest tests/test_strategy.py::TestSimpleStrategy::test_buy_signal_on_uptrend -v
```

### Run with Coverage
```bash
pytest tests/ --cov=. --cov-report=html
```

### Run Only Non-Skipped Tests
```bash
pytest tests/ -v -k "not skip"
```

## Test Categories

### 1. Configuration Tests (`test_main.py::TestConfiguration`)
- Configuration file loading
- Default value handling
- Missing configuration handling

### 2. MT5 Connection Tests (`test_main.py::TestMT5Connection`)
- MT5 initialization
- Account info retrieval
- Connection error handling

### 3. Symbol Tests (`test_main.py::TestSymbolPreparation`)
- Symbol selection
- Symbol validation
- Symbol info retrieval

### 4. Order Execution Tests (`test_main.py::TestOrderExecution`)
- BUY order execution
- SELL order execution
- Order failure handling

### 5. Trade Logging Tests (`test_main.py::TestTradeLogging`)
- Successful trade logging
- Failed trade logging
- Log file format validation

### 6. Strategy Tests (`test_strategy.py`)
- **SimpleStrategy**: Momentum-based trading signals
  - BUY signal on uptrend
  - SELL signal on downtrend
  - NONE signal on sideways/equal prices
  - Insufficient data handling
- **Future Strategies** (placeholder tests):
  - Moving Average Crossover
  - RSI Strategy
  - MACD Strategy
  - Strategy Manager

### 7. Milestone 2 Tests (`test_milestone2.py`)
- **Position Tracking**:
  - Get open positions (filtered and unfiltered)
  - Check for existing positions
  - Max concurrent trades limit
- **Trade Execution**:
  - BUY/SELL execution with new structure
  - Tick data validation
  - Order failure handling
- **Trading Iteration**:
  - Signal execution
  - Duplicate trade prevention
  - Max trades enforcement
- **Initialization**:
  - MT5 initialization
  - Symbol preparation

## Fixtures

### `mock_mt5` (conftest.py)
Provides a fully mocked MetaTrader5 module for testing without actual MT5 connection.

**Usage:**
```python
def test_something(mock_mt5):
    mock_mt5.initialize.return_value = True
    # Your test code
```

### `mock_rates_data` (conftest.py)
Generates mock OHLC price data for strategy testing.

**Usage:**
```python
def test_strategy(mock_rates_data):
    uptrend_data = mock_rates_data("uptrend", 20)
    downtrend_data = mock_rates_data("downtrend", 20)
    sideways_data = mock_rates_data("sideways", 20)
    volatile_data = mock_rates_data("volatile", 20)
```

### `sample_config` (conftest.py)
Provides a sample configuration dictionary for testing.

### `temp_log_file` (conftest.py)
Creates a temporary log file for testing logging functionality.

### `temp_config_file` (conftest.py)
Creates a temporary configuration file for testing config loading.

## Test Coverage

Current test coverage:
- ✅ **38 tests passing**
- ⏭️ **17 tests skipped** (future features)
- ❌ **0 tests failing**

### Implemented Features (Tested)
- ✅ Configuration loading and validation
- ✅ MT5 connection and initialization
- ✅ Symbol preparation
- ✅ Order execution (BUY/SELL)
- ✅ Trade logging
- ✅ Simple momentum strategy
- ✅ Position tracking (Milestone 2)
- ✅ Continuous trading loop structure (Milestone 2)
- ✅ Max concurrent trades limit (Milestone 2)
- ✅ Graceful shutdown handling (Milestone 2)

### Future Features (Placeholder Tests)
- ⏭️ Moving Average Crossover strategy
- ⏭️ RSI strategy
- ⏭️ MACD strategy
- ⏭️ Strategy Manager
- ⏭️ Risk management features
- ⏭️ Advanced analytics

## Writing New Tests

### Example Test Structure
```python
import pytest
from unittest.mock import patch, Mock

class TestNewFeature:
    """Tests for new feature."""
    
    @patch('module.dependency')
    def test_feature_success(self, mock_dependency):
        """Test successful feature execution."""
        # Arrange
        mock_dependency.return_value = expected_value
        
        # Act
        result = function_to_test()
        
        # Assert
        assert result == expected_result
        mock_dependency.assert_called_once()
```

### Best Practices
1. **Use descriptive test names**: `test_buy_signal_on_uptrend` is better than `test_buy`
2. **Follow AAA pattern**: Arrange, Act, Assert
3. **Mock external dependencies**: Use `@patch` for MT5, file I/O, etc.
4. **Test edge cases**: Empty data, None values, errors
5. **Use fixtures**: Reuse common setup code
6. **Add docstrings**: Explain what each test validates

## Continuous Integration

Tests are designed to run in CI/CD pipelines without requiring actual MT5 installation.

### GitHub Actions Example
```yaml
name: Tests
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      - uses: actions/setup-python@v2
        with:
          python-version: '3.12'
      - run: pip install -r requirements.txt
      - run: pytest tests/ -v
```

## Troubleshooting

### Import Errors
If you get import errors, make sure you're running pytest from the project root:
```bash
cd D:\Projects\TraderBot
pytest tests/ -v
```

### Mock Issues
If mocks aren't working, ensure you're patching the correct module path:
```python
# Patch where it's used, not where it's defined
@patch('main.mt5')  # Correct
@patch('MetaTrader5')  # May not work
```

### Fixture Not Found
Make sure `conftest.py` is in the tests directory and pytest can find it.

## Future Enhancements

- [ ] Add integration tests with demo MT5 account
- [ ] Add performance/load tests
- [ ] Add mutation testing
- [ ] Increase code coverage to 90%+
- [ ] Add property-based testing with Hypothesis
- [ ] Add contract tests for external APIs

