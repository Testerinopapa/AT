# TraderBot Changelog

All notable changes to this project will be documented in this file.

## [Unreleased]

### Milestone 2 - Continuous Trading Loop ✅ COMPLETED (2025-10-29)

#### Added
- **Continuous Trading Mode**: Bot can now run indefinitely with configurable intervals
  - Single trade mode (original behavior)
  - Continuous loop mode with scheduler
  - Configurable via `enable_continuous_trading` in settings.json

- **Position Tracking System**:
  - `get_open_positions()`: Retrieve all or filtered open positions
  - `has_open_position()`: Check if position exists for symbol
  - `can_open_new_trade()`: Validate against max concurrent trades limit
  - Prevents duplicate trades on same symbol
  - Enforces max concurrent trades limit

- **Graceful Shutdown Handling**:
  - CTRL+C (SIGINT) signal handler
  - SIGTERM signal handler for service environments
  - Clean MT5 connection closure
  - Iteration count reporting
  - No orphaned processes

- **Enhanced Configuration**:
  - `trade_interval_seconds`: Time between trading checks (default: 300)
  - `max_concurrent_trades`: Maximum open positions (default: 3)
  - `enable_continuous_trading`: Toggle continuous mode (default: false)

- **Refactored Code Structure**:
  - `initialize_mt5()`: Modular MT5 initialization
  - `prepare_symbol()`: Symbol validation and preparation
  - `execute_trade()`: Centralized trade execution
  - `trading_iteration()`: Single iteration logic
  - `run_single_trade()`: Single trade mode
  - `run_continuous_trading()`: Continuous mode with loop

#### Testing
- **Comprehensive Test Suite** (38 passing tests):
  - `tests/__init__.py`: Test package initialization
  - `tests/conftest.py`: Shared fixtures and mocks
  - `tests/test_main.py`: Main bot functionality tests
  - `tests/test_strategy.py`: Strategy tests with future placeholders
  - `tests/test_milestone2.py`: Milestone 2 feature tests (19 tests)
  - `tests/README.md`: Complete testing documentation

- **Test Coverage**:
  - Configuration loading and validation
  - MT5 connection and initialization
  - Symbol preparation
  - Order execution (BUY/SELL)
  - Trade logging
  - Position tracking
  - Max concurrent trades enforcement
  - Graceful shutdown
  - Trading iteration logic

#### Documentation
- **USAGE.md**: Complete usage guide
  - Installation instructions
  - Configuration reference
  - Trading modes explanation
  - Monitoring guidelines
  - Safety features overview
  - Troubleshooting guide
  - Best practices
  - Advanced usage (Windows/Linux services)

- **tests/README.md**: Testing documentation
  - Test structure overview
  - Running tests guide
  - Test categories explanation
  - Fixtures documentation
  - Writing new tests guide

- **CHANGELOG.md**: This file

#### Infrastructure
- **Enhanced .gitignore**:
  - Comprehensive Python patterns
  - Trading bot specific (logs, configs, data)
  - ML/AI model files
  - IDE configurations
  - OS-specific files
  - Security (credentials, keys, secrets)
  - Future-proof structure

### Milestone 1 - Core Bot Foundation ✅ COMPLETED

#### Added
- Split logic into `main.py` and `strategy.py`
- MT5 connection and account info logging
- BUY/SELL trade execution with proper rounding
- Stop-loss and take-profit implementation
- Trade logging to `logs/trades.log`
- FOK order filling mode
- Safe handling for "no signal" scenarios
- Configuration via `config/settings.json`

## Project Statistics

### Code Metrics
- **Main Files**: 2 (main.py, strategy.py)
- **Test Files**: 4 (55 total tests, 38 passing, 17 future placeholders)
- **Configuration Files**: 1 (settings.json)
- **Documentation Files**: 4 (README, USAGE, ROADMAP, CHANGELOG)
- **Lines of Code**: ~600+ (excluding tests)
- **Test Coverage**: Core functionality fully tested

### Features Implemented
- ✅ MT5 Integration
- ✅ Simple Momentum Strategy
- ✅ Trade Execution (BUY/SELL)
- ✅ Trade Logging
- ✅ Configuration Management
- ✅ Continuous Trading Loop
- ✅ Position Tracking
- ✅ Graceful Shutdown
- ✅ Max Concurrent Trades
- ✅ Comprehensive Testing

### Features Planned
- ⏳ Multiple Strategies (MA, RSI, MACD)
- ⏳ Strategy Manager
- ⏳ AI/ML Integration
- ⏳ Risk Management
- ⏳ Advanced Analytics
- ⏳ Web Dashboard
- ⏳ Notifications (Telegram/Slack)
- ⏳ Backtesting Framework

## Migration Guide

### Upgrading from Milestone 1 to Milestone 2

#### Configuration Changes
Add new parameters to `config/settings.json`:
```json
{
  "symbol": "EURUSD",
  "volume": 0.1,
  "deviation": 50,
  "trade_interval_seconds": 300,        // NEW
  "max_concurrent_trades": 3,           // NEW
  "enable_continuous_trading": false    // NEW
}
```

#### Behavior Changes
1. **Default Mode**: Still single trade execution (backward compatible)
2. **New Mode**: Enable `enable_continuous_trading: true` for continuous operation
3. **Position Checking**: Bot now checks for existing positions before trading
4. **Concurrent Limit**: Bot enforces max concurrent trades limit

#### Code Changes
- No breaking changes to existing functionality
- New functions added (backward compatible)
- Signal handler added (transparent to users)

## Known Issues

### Current Limitations
1. **Fixed SL/TP**: Stop-loss and take-profit use fixed pip values
   - Planned: ATR-based dynamic SL/TP (Milestone 5)

2. **Single Symbol**: Bot trades only one symbol at a time
   - Planned: Multi-symbol support (Milestone 7)

3. **Simple Strategy**: Only momentum-based strategy available
   - Planned: Multiple strategies (Milestone 3)

4. **No Risk Management**: Fixed lot size, no dynamic sizing
   - Planned: Dynamic lot sizing (Milestone 5)

5. **Basic Logging**: Simple text file logging
   - Planned: Database storage and analytics (Milestone 6)

### Workarounds
- **Fixed SL/TP**: Adjust values in `execute_trade()` function
- **Single Symbol**: Run multiple bot instances with different configs
- **Simple Strategy**: Modify `strategy.py` for custom logic
- **Fixed Lot Size**: Change `volume` in settings.json
- **Basic Logging**: Parse logs with external tools

## Security Notes

### Sensitive Data
- Never commit `config/settings.json` with real account credentials
- Use `.gitignore` to exclude sensitive files
- Keep API keys and passwords in environment variables

### Safe Practices
- Always test on demo account first
- Start with small lot sizes
- Monitor bot regularly
- Set appropriate max concurrent trades
- Use stop-loss on all trades

## Performance Notes

### Resource Usage
- **CPU**: Minimal (<1% during idle, <5% during execution)
- **Memory**: ~50-100 MB
- **Network**: Minimal (only MT5 API calls)
- **Disk**: Log files grow over time (rotate regularly)

### Optimization Tips
- Increase `trade_interval_seconds` to reduce API calls
- Limit `max_concurrent_trades` to reduce complexity
- Rotate log files weekly/monthly
- Use SSD for faster file I/O

## Contributing

### Development Workflow
1. Create feature branch from `main`
2. Implement feature with tests
3. Run test suite: `pytest tests/ -v`
4. Update documentation
5. Submit pull request

### Testing Requirements
- All new features must have tests
- Maintain >80% code coverage
- All tests must pass before merge
- Follow existing test patterns

## Support

- **GitHub Issues**: https://github.com/STHS24/AT/issues
- **Documentation**: See USAGE.md and ROADMAP.md
- **Tests**: Run `pytest tests/ -v` to verify installation

## License

See LICENSE file for details.

## Acknowledgments

- MetaTrader 5 Python API
- pytest testing framework
- Python community

---

**Note**: This is an active development project. Features and APIs may change between milestones. Always check this changelog before upgrading.

