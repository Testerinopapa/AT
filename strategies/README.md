# Trading Strategies Documentation

This directory contains the modular strategy system for the TraderBot. Each strategy implements the `BaseStrategy` abstract class and generates trading signals (`BUY`, `SELL`, or `NONE`) based on technical analysis.

---

## 📁 Package Structure

```
strategies/
├── __init__.py              # Package exports
├── base_strategy.py         # Abstract base class
├── simple_strategy.py       # Momentum-based strategy
├── ma_strategy.py           # Moving Average Crossover
├── rsi_strategy.py          # RSI Overbought/Oversold
├── macd_strategy.py         # MACD Crossover
├── strategy_manager.py      # Multi-strategy combiner
└── README.md                # This file
```

---

## 🎯 Available Strategies

### 1. **SimpleStrategy** (Momentum)

**Description**: Basic momentum strategy that compares the last two candle closes.

**Logic**:
- **BUY**: Last close > Previous close (upward momentum)
- **SELL**: Last close < Previous close (downward momentum)
- **NONE**: Last close == Previous close (no momentum)

**Parameters**:
```json
{
  "timeframe": "M1",      // Timeframe (M1, M5, M15, etc.)
  "lookback": 20          // Number of candles to fetch
}
```

**Default Weight**: 1.0

**Use Case**: Quick reaction to price movements, good for scalping.

---

### 2. **MAStrategy** (Moving Average Crossover)

**Description**: Classic moving average crossover strategy using fast and slow MAs.

**Logic**:
- **BUY**: Fast MA crosses above Slow MA (Golden Cross)
- **SELL**: Fast MA crosses below Slow MA (Death Cross)
- **NONE**: No crossover detected

**Parameters**:
```json
{
  "timeframe": "M5",      // Timeframe
  "fast_period": 10,      // Fast MA period
  "slow_period": 20,      // Slow MA period
  "ma_type": "EMA"        // MA type: "SMA" or "EMA"
}
```

**Default Weight**: 1.5

**Technical Details**:
- **SMA**: Simple Moving Average (arithmetic mean)
- **EMA**: Exponential Moving Average (weighted toward recent prices)
- **EMA Formula**: `EMA = (Close - EMA_prev) * multiplier + EMA_prev`
- **Multiplier**: `2 / (period + 1)`

**Use Case**: Trend following, works well in trending markets.

---

### 3. **RSIStrategy** (Relative Strength Index)

**Description**: Momentum oscillator that measures overbought/oversold conditions.

**Logic**:
- **BUY**: RSI crosses above oversold threshold (default: 30)
- **SELL**: RSI crosses below overbought threshold (default: 70)
- **NONE**: RSI in neutral zone

**Parameters**:
```json
{
  "timeframe": "M5",      // Timeframe
  "period": 14,           // RSI calculation period
  "oversold": 30,         // Oversold threshold
  "overbought": 70        // Overbought threshold
}
```

**Default Weight**: 1.2

**Technical Details**:
- **RSI Formula**: `RSI = 100 - (100 / (1 + RS))`
- **RS**: Average Gain / Average Loss
- **Smoothing**: Uses Wilder's smoothing method
- **Range**: 0-100 (30 = oversold, 70 = overbought)

**Use Case**: Mean reversion, identifying reversal points.

---

### 4. **MACDStrategy** (Moving Average Convergence Divergence)

**Description**: Trend-following momentum indicator using EMA differences.

**Logic**:
- **BUY**: MACD line crosses above Signal line (bullish crossover)
- **SELL**: MACD line crosses below Signal line (bearish crossover)
- **NONE**: No crossover detected

**Parameters**:
```json
{
  "timeframe": "M15",     // Timeframe
  "fast_period": 12,      // Fast EMA period
  "slow_period": 26,      // Slow EMA period
  "signal_period": 9      // Signal line EMA period
}
```

**Default Weight**: 1.0

**Technical Details**:
- **MACD Line**: Fast EMA - Slow EMA
- **Signal Line**: EMA of MACD Line
- **Histogram**: MACD Line - Signal Line
- **Crossover**: When MACD crosses Signal line

**Use Case**: Trend confirmation, momentum shifts.

---

## 🔧 Strategy Manager

The `StrategyManager` combines signals from multiple strategies using different methods.

### Combination Methods

#### 1. **Unanimous** (Most Conservative)
All enabled strategies must agree on the signal.

```python
# Example: All must agree
SimpleStrategy: BUY
MAStrategy: BUY
RSIStrategy: BUY
→ Combined: BUY

# If any disagrees
SimpleStrategy: BUY
MAStrategy: SELL
RSIStrategy: BUY
→ Combined: NONE
```

**Use Case**: High-confidence trades, low frequency.

---

#### 2. **Majority** (Balanced)
Most common signal wins (>50% of active strategies).

```python
# Example: Majority BUY
SimpleStrategy: BUY
MAStrategy: BUY
RSIStrategy: SELL
→ Combined: BUY (2/3 = 66%)

# Example: No majority
SimpleStrategy: BUY
MAStrategy: SELL
RSIStrategy: NONE
→ Combined: NONE (no signal > 50%)
```

**Use Case**: Balanced approach, moderate frequency.

---

#### 3. **Weighted** (Customizable)
Signals weighted by strategy importance.

```python
# Example with weights
SimpleStrategy (weight=1.0): BUY  → +1.0
MAStrategy (weight=1.5): BUY      → +1.5
RSIStrategy (weight=1.2): SELL    → -1.2
→ Total: BUY=2.5, SELL=1.2
→ Combined: BUY

# Calculation
BUY_weight = sum(weights where signal=BUY)
SELL_weight = sum(weights where signal=SELL)
if BUY_weight > SELL_weight: return BUY
elif SELL_weight > BUY_weight: return SELL
else: return NONE
```

**Use Case**: Prioritize trusted strategies, flexible tuning.

---

#### 4. **Any** (Most Aggressive)
Any strategy signal triggers action.

```python
# Example: Any signal triggers
SimpleStrategy: NONE
MAStrategy: BUY
RSIStrategy: NONE
→ Combined: BUY

# Priority: BUY > SELL > NONE
SimpleStrategy: BUY
MAStrategy: SELL
RSIStrategy: NONE
→ Combined: BUY (BUY has priority)
```

**Use Case**: High-frequency trading, capture all opportunities.

---

## ⚙️ Configuration Example

```json
{
  "strategy_config": {
    "combination_method": "majority",
    "enabled_strategies": ["SimpleStrategy", "MAStrategy", "RSIStrategy"],
    
    "SimpleStrategy": {
      "enabled": true,
      "weight": 1.0,
      "params": {
        "timeframe": "M1",
        "lookback": 20
      }
    },
    
    "MAStrategy": {
      "enabled": true,
      "weight": 1.5,
      "params": {
        "timeframe": "M5",
        "fast_period": 10,
        "slow_period": 20,
        "ma_type": "EMA"
      }
    },
    
    "RSIStrategy": {
      "enabled": true,
      "weight": 1.2,
      "params": {
        "timeframe": "M5",
        "period": 14,
        "oversold": 30,
        "overbought": 70
      }
    },
    
    "MACDStrategy": {
      "enabled": false,
      "weight": 1.0,
      "params": {
        "timeframe": "M15",
        "fast_period": 12,
        "slow_period": 26,
        "signal_period": 9
      }
    }
  }
}
```

---

## 🧪 Testing

All strategies have comprehensive unit tests in `tests/test_strategies_new.py`:

```bash
# Run all strategy tests
pytest tests/test_strategies_new.py -v

# Run specific strategy tests
pytest tests/test_strategies_new.py::TestSimpleStrategyNew -v
pytest tests/test_strategies_new.py::TestMAStrategyNew -v
pytest tests/test_strategies_new.py::TestRSIStrategyNew -v
pytest tests/test_strategies_new.py::TestMACDStrategyNew -v
pytest tests/test_strategies_new.py::TestStrategyManagerNew -v
```

**Test Coverage**:
- ✅ Signal generation (BUY, SELL, NONE)
- ✅ Enable/disable functionality
- ✅ Weight adjustments
- ✅ Combination methods
- ✅ Edge cases (insufficient data, equal prices)

---

## 🚀 Adding New Strategies

To create a new strategy:

1. **Create new file** in `strategies/` (e.g., `bollinger_strategy.py`)

2. **Inherit from BaseStrategy**:
```python
from strategies.base_strategy import BaseStrategy
import MetaTrader5 as mt5

class BollingerStrategy(BaseStrategy):
    def __init__(self, params=None):
        super().__init__("BollingerStrategy", params)
    
    def generate_signal(self, symbol: str) -> str:
        # Your logic here
        # Return "BUY", "SELL", or "NONE"
        pass
```

3. **Add to `__init__.py`**:
```python
from .bollinger_strategy import BollingerStrategy
```

4. **Update configuration** in `config/settings.json`

5. **Add tests** in `tests/test_strategies_new.py`

---

## 📊 Performance Tips

1. **Timeframe Selection**:
   - Lower timeframes (M1, M5): More signals, more noise
   - Higher timeframes (H1, H4): Fewer signals, stronger trends

2. **Strategy Combination**:
   - Mix trend-following (MA, MACD) with mean-reversion (RSI)
   - Use different timeframes for multi-timeframe analysis

3. **Weight Tuning**:
   - Higher weights for strategies with better historical performance
   - Backtest to find optimal weights

4. **Combination Method**:
   - `unanimous`: Low frequency, high confidence
   - `majority`: Balanced approach
   - `weighted`: Customizable, requires tuning
   - `any`: High frequency, requires good risk management

---

## 📝 Notes

- All strategies use numpy for efficient calculations
- Strategies are stateless (no memory between calls)
- Signal history is tracked by StrategyManager
- Each strategy can use different timeframes
- Strategies are independent and can be enabled/disabled individually

---

## 🔗 Related Files

- `main.py`: Strategy initialization and usage
- `config/settings.json`: Strategy configuration
- `tests/test_strategies_new.py`: Strategy tests
- `CHANGELOG.md`: Version history

