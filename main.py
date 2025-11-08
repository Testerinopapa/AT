import MetaTrader5 as mt5
import sys
import json
import os
import time
import signal
import pickle
from datetime import datetime
from pathlib import Path

try:
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
except ImportError:  # pragma: no cover - Python < 3.9 fallback
    ZoneInfo = None

    class ZoneInfoNotFoundError(Exception):
        """Fallback exception when zoneinfo is unavailable."""


# Import new strategy system
from strategies import (
    SimpleStrategy,
    MAStrategy,
    RSIStrategy,
    MACDStrategy,
    StrategyManager
)

# Import risk management
from risk_manager import RiskManager

# Import logging and analytics
from trade_logger import TradeLogger
from analytics import PerformanceAnalytics
from agents import EnvironmentAgent
from market_data.environment import MarketEnvironment

from mt5_helpers import OrderRequest, close_position_by_ticket, send_market_order


MT5_TIMEFRAME_MAP = {
    "M1": mt5.TIMEFRAME_M1,
    "M5": mt5.TIMEFRAME_M5,
    "M15": mt5.TIMEFRAME_M15,
    "M30": mt5.TIMEFRAME_M30,
    "H1": mt5.TIMEFRAME_H1,
    "H4": mt5.TIMEFRAME_H4,
    "D1": mt5.TIMEFRAME_D1,
}


def _resolve_timezone(name: str):
    """Resolve a timezone name into a ZoneInfo object when available."""

    if not name:
        return None

    if ZoneInfo is None:
        print(
            f"WARNING:  zoneinfo module not available; unable to localize timezone '{name}'."
        )
        return None

    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError:
        print(f"WARNING:  Unknown timezone '{name}'. Falling back to naive datetimes.")
        return None


def _parse_datetime(candidate, tzinfo):
    """Parse ISO datetime strings or timestamps into datetime objects."""

    if candidate in (None, ""):
        return None

    if isinstance(candidate, (int, float)):
        try:
            return datetime.fromtimestamp(candidate, tz=tzinfo)
        except (OverflowError, OSError, ValueError):
            print(f"WARNING:  Invalid timestamp '{candidate}' in backtest history config.")
            return None

    if isinstance(candidate, str):
        try:
            parsed = datetime.fromisoformat(candidate)
        except ValueError:
            print(f"WARNING:  Unable to parse datetime string '{candidate}'.")
            return None

        if parsed.tzinfo is None and tzinfo is not None:
            parsed = parsed.replace(tzinfo=tzinfo)

        return parsed

    print(f"WARNING:  Unsupported datetime value '{candidate}' ({type(candidate).__name__}).")
    return None


def parse_backtest_config(raw_config):
    """Normalize backtest configuration and apply sensible defaults."""

    default_timezone_name = "UTC"
    default_timezone = _resolve_timezone(default_timezone_name)

    normalized = {
        "timeframe_key": "H1",
        "timeframe": MT5_TIMEFRAME_MAP.get("H1", mt5.TIMEFRAME_H1),
        "history": {
            "start": None,
            "start_raw": None,
            "end": None,
            "end_raw": None,
            "timezone_name": default_timezone_name,
            "timezone": default_timezone,
            "align_to_broker_timezone": False,
        },
        "initial_cash": 100000.0,
        "commission": {
            "model": "percentage",
            "rate": 0.0002,
            "per_trade": 0.0,
        },
    }

    if not isinstance(raw_config, dict):
        return normalized

    timeframe_key = str(raw_config.get("timeframe", normalized["timeframe_key"])).upper()
    if timeframe_key not in MT5_TIMEFRAME_MAP:
        print(
            f"WARNING:  Unsupported backtest timeframe '{timeframe_key}'. Defaulting to {normalized['timeframe_key']}."
        )
        timeframe_key = normalized["timeframe_key"]

    normalized["timeframe_key"] = timeframe_key
    normalized["timeframe"] = MT5_TIMEFRAME_MAP.get(timeframe_key, normalized["timeframe"])

    history_raw = raw_config.get("history", {})
    if not isinstance(history_raw, dict):
        history_raw = {}

    timezone_name = str(
        history_raw.get("timezone", normalized["history"]["timezone_name"])
    )
    timezone_obj = _resolve_timezone(timezone_name)

    history = normalized["history"]
    history["timezone_name"] = timezone_name
    history["timezone"] = timezone_obj
    history["align_to_broker_timezone"] = bool(
        history_raw.get(
            "align_to_broker_timezone", history["align_to_broker_timezone"]
        )
    )

    history["start_raw"] = history_raw.get("start")
    history["end_raw"] = history_raw.get("end")
    history["start"] = _parse_datetime(history["start_raw"], timezone_obj)
    history["end"] = _parse_datetime(history["end_raw"], timezone_obj)

    try:
        normalized["initial_cash"] = float(
            raw_config.get("initial_cash", normalized["initial_cash"])
        )
    except (TypeError, ValueError):
        print(
            f"WARNING:  Invalid initial_cash '{raw_config.get('initial_cash')}'. Using default {normalized['initial_cash']}."
        )

    commission_raw = raw_config.get("commission", {})
    commission_cfg = normalized["commission"]
    if isinstance(commission_raw, dict):
        if "model" in commission_raw:
            commission_cfg["model"] = str(commission_raw["model"]).strip().lower()
        if "rate" in commission_raw:
            try:
                commission_cfg["rate"] = float(commission_raw["rate"])
            except (TypeError, ValueError):
                print(
                    f"WARNING:  Invalid commission rate '{commission_raw.get('rate')}'. Using default {commission_cfg['rate']}."
                )
        if "per_trade" in commission_raw:
            try:
                commission_cfg["per_trade"] = float(commission_raw["per_trade"])
            except (TypeError, ValueError):
                fallback_value = commission_cfg.get("per_trade")
                print(
                    "WARNING:  Invalid commission per_trade "
                    f"'{commission_raw.get('per_trade')}'. Using default {fallback_value}."
                )

    return normalized


def _format_history_bound(history_section, bound):
    """Return a human-friendly representation of a history boundary."""

    dt_obj = history_section.get(bound)
    if dt_obj is not None:
        return dt_obj.isoformat()

    raw_value = history_section.get(f"{bound}_raw")
    return raw_value if raw_value not in (None, "") else "not set"


# ------------------------------
# GLOBAL STATE
# ------------------------------
running = True  # Flag for graceful shutdown


def signal_handler(sig, frame):
    """Handle CTRL+C for graceful shutdown."""
    global running
    print("\n\nWARNING:  Shutdown signal received. Closing positions and exiting gracefully...")
    running = False


# Register signal handler
signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

# ------------------------------
# CONFIGURATION
# ------------------------------
LIVE_CONFIG_CANDIDATES = [
    os.path.join("config", "settings.live.json"),
    os.path.join("config", "settings.json"),
]
LOG_PATH = os.path.join("logs", "trades.log")

# Load live config (prefer settings.live.json)
config = None
CONFIG_PATH = None
for _path in LIVE_CONFIG_CANDIDATES:
    try:
        with open(_path, "r", encoding="utf-8-sig") as f:
            config = json.load(f)
            CONFIG_PATH = _path
            break
    except FileNotFoundError:
        continue
if config is None:
    print("ERROR: No live config found. Create config/settings.live.json or config/settings.json")
    sys.exit(1)

MARKET_DATA_CONFIG = config.get("market_data", {}) if isinstance(config, dict) else {}
ALLOWED_MARKET_MODES = {"live", "snapshot", "backtest"}
MARKET_MODE = str(MARKET_DATA_CONFIG.get("mode", "live")).strip().lower()
if MARKET_MODE not in ALLOWED_MARKET_MODES:
    print(f"WARNING:  Unknown market_data.mode '{MARKET_MODE}' - defaulting to live mode.")
    MARKET_MODE = "live"

SNAPSHOT_PATH = MARKET_DATA_CONFIG.get("snapshot_path", "data/env_data.pkl")
# Decoupled: main.py does not load or use backtest config
BACKTEST_CONFIG = {}

SYMBOL = config.get("symbol", "EURUSD")
VOLUME = float(config.get("volume", 0.1))
DEVIATION = int(config.get("deviation", 50))
TRADE_INTERVAL = int(config.get("trade_interval_seconds", 300))  # Default 5 minutes
MAX_CONCURRENT_TRADES = int(config.get("max_concurrent_trades", 3))
ENABLE_CONTINUOUS = config.get("enable_continuous_trading", False)

# Ensure logs folder exists
os.makedirs("logs", exist_ok=True)


# ------------------------------
# STRATEGY INITIALIZATION
# ------------------------------
def initialize_strategies():
    """
    Initialize trading strategies from configuration.

    Returns:
        StrategyManager: Configured strategy manager
    """
    strategy_config = config.get("strategy_config", {})
    combination_method = strategy_config.get("combination_method", "majority")

    # Create strategy manager
    manager = StrategyManager(method=combination_method)

    # Strategy class mapping
    strategy_classes = {
        "SimpleStrategy": SimpleStrategy,
        "MAStrategy": MAStrategy,
        "RSIStrategy": RSIStrategy,
        "MACDStrategy": MACDStrategy
    }

    # Initialize each configured strategy
    for strategy_name, strategy_class in strategy_classes.items():
        strategy_settings = strategy_config.get(strategy_name, {})

        if not strategy_settings:
            continue

        # Get parameters and convert timeframe strings
        params = strategy_settings.get("params", {}).copy()
        if "timeframe" in params and isinstance(params["timeframe"], str):
            timeframe_key = params["timeframe"].upper()
            params["timeframe"] = MT5_TIMEFRAME_MAP.get(
                timeframe_key, mt5.TIMEFRAME_M5
            )

        # Create strategy instance
        strategy = strategy_class(params)

        # Set enabled state
        if not strategy_settings.get("enabled", True):
            strategy.disable()

        # Set weight
        weight = strategy_settings.get("weight", 1.0)
        strategy.set_weight(weight)

        # Add to manager
        manager.add_strategy(strategy)

    print(f"\n[Config] Strategy Manager initialized: {manager}")
    print(f"[Config] Active strategies: {len([s for s in manager.strategies if s.enabled])}/{len(manager.strategies)}")

    return manager


# Initialize strategy manager
STRATEGY_MANAGER = initialize_strategies()

# Initialize Risk Manager
RISK_MANAGER = RiskManager(config)
print(f"[Config] Risk Manager initialized")
print(f"[Config] Risk per trade: {RISK_MANAGER.risk_percentage}%")
print(f"[Config] SL/TP method: {RISK_MANAGER.sl_method}/{RISK_MANAGER.tp_method}")
print(f"[Config] Daily limits: Loss=${RISK_MANAGER.daily_loss_limit}, Profit=${RISK_MANAGER.daily_profit_target}")
print(f"[Config] Market data mode: {MARKET_MODE}")
if MARKET_MODE == "snapshot":
    print(f"[Config] Snapshot path: {SNAPSHOT_PATH}")
elif MARKET_MODE == "backtest":
    print("[Config] Backtest mode selected, but main.py does not run backtests.")
    print("[Config] Use CLI: python scripts/run_backtest.py --symbol EURUSD --period 7 --interval 1h")

# Initialize Trade Logger and Analytics
TRADE_LOGGER = TradeLogger()
ANALYTICS = PerformanceAnalytics()
print(f"[Config] Trade Logger and Analytics initialized")

# ------------------------------
# HELPER FUNCTIONS
# ------------------------------
def initialize_mt5():
    """Initialize MT5 connection and validate account."""
    print("Initializing MetaTrader 5...")

    if not mt5.initialize():
        print("MT5 initialization failed:", mt5.last_error())
        return False

    account_info = mt5.account_info()
    if account_info is None:
        print("ERROR: Could not retrieve account info. Is MetaTrader 5 logged in?")
        return False

    print(f"Connected to account #{account_info.login} | Balance: {account_info.balance:.2f}\n")
    return True


def prepare_symbol(symbol):
    """Prepare and validate trading symbol."""
    if not mt5.symbol_select(symbol, True):
        print(f"ERROR: Could not select symbol {symbol}")
        return False

    symbol_info = mt5.symbol_info(symbol)
    if not symbol_info:
        print(f"ERROR: Symbol {symbol} not found.")
        return False

    print(f"OK: Symbol {symbol} ready for trading.\n")
    return True


def get_open_positions(symbol=None):
    """
    Get open positions, optionally filtered by symbol.

    Args:
        symbol: Optional symbol to filter positions

    Returns:
        List of open positions
    """
    if symbol:
        positions = mt5.positions_get(symbol=symbol)
    else:
        positions = mt5.positions_get()

    return positions if positions is not None else []


def has_open_position(symbol):
    """
    Check if there's already an open position for the symbol.

    Args:
        symbol: Trading symbol to check

    Returns:
        Boolean indicating if position exists
    """
    positions = get_open_positions(symbol)
    return len(positions) > 0


def can_open_new_trade():
    """
    Check if we can open a new trade based on max concurrent trades limit.

    Returns:
        Boolean indicating if new trade can be opened
    """
    all_positions = get_open_positions()
    return len(all_positions) < MAX_CONCURRENT_TRADES

def log_trade(action, result, volume, price, sl, tp, strategy="Combined"):
    """
    Log trade execution using enhanced logger.

    Args:
        action: Trade action (BUY/SELL)
        result: MT5 order result
        volume: Trade volume
        price: Entry price
        sl: Stop loss
        tp: Take profit
        strategy: Strategy name
    """
    # Use new enhanced logger
    TRADE_LOGGER.log_trade_open(
        symbol=SYMBOL,
        action=action,
        result=result,
        volume=volume,
        entry_price=price,
        sl=sl,
        tp=tp,
        strategy=strategy
    )

    # Also keep old format for backward compatibility
    with open(LOG_PATH, "a") as f:
        f.write(
            f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | "
            f"{action:<12} | "
            f"{result.order:<12} | "
            f"Price: {price:.5f} | SL: {sl:.5f} | TP: {tp:.5f} | Retcode: {result.retcode}\n"
        )


def execute_trade(symbol, action):
    """
    Execute a trade based on the action signal with risk management.

    Args:
        symbol: Trading symbol
        action: Trade action ('BUY' or 'SELL')

    Returns:
        Boolean indicating success
    """
    # Check if trading is allowed (daily limits)
    can_trade, reason = RISK_MANAGER.can_trade()
    if not can_trade:
        print(f"BLOCKED: Trading disabled: {reason}")
        return False

    print(f"📤 Sending {action} trade request...")

    # Get latest prices
    tick = mt5.symbol_info_tick(symbol)
    if tick is None:
        print(f"ERROR: Could not get tick data for {symbol}")
        return False

    price = tick.ask if action == "BUY" else tick.bid

    # Calculate SL/TP using Risk Manager
    sl, tp = RISK_MANAGER.calculate_sl_tp(symbol, action, price)

    # Calculate SL distance in pips for lot sizing
    symbol_info = mt5.symbol_info(symbol)
    if symbol_info is None:
        print(f"ERROR: Could not get symbol info for {symbol}")
        return False

    point = symbol_info.point
    sl_distance_pips = abs(price - sl) / (point * 10)  # Convert to pips

    # Calculate optimal lot size (if dynamic sizing enabled)
    if config.get("risk_management", {}).get("enable_dynamic_lot_sizing", False):
        volume = RISK_MANAGER.calculate_lot_size(symbol, sl_distance_pips)
        print(f"💰 Dynamic lot size: {volume} (Risk: {RISK_MANAGER.risk_percentage}%, SL: {sl_distance_pips:.1f} pips)")
    else:
        volume = VOLUME
        print(f"💰 Fixed lot size: {volume}")

    # Validate trade
    is_valid, validation_reason = RISK_MANAGER.validate_trade(symbol, action, volume)
    if not is_valid:
        print(f"BLOCKED: Trade validation failed: {validation_reason}")
        return False

    order_request = OrderRequest(
        symbol=symbol,
        action=action,
        volume=volume,
        price=price,
        sl=sl,
        tp=tp,
        deviation=DEVIATION,
        magic=123456,
        comment=f"Python MT5 Bot {action}",
    )

    # Execute order
    try:
        result = send_market_order(order_request)
    except RuntimeError as exc:
        print(f"ERROR: Order send failed: {exc}")
        return False

    if result is None:
        print("ERROR: Order send failed - no result returned")
        return False

    print(f"\nTrade Result: {result}")

    # Log and report result
    if result.retcode == mt5.TRADE_RETCODE_DONE:
        print(f"\nOK: {action} executed successfully!")
        print(f"   Ticket: {result.order}")
        print(f"   Price:  {result.price}")
        print(f"   SL:     {sl}")
        print(f"   TP:     {tp}")

        # Get strategy name from manager
        strategy_name = STRATEGY_MANAGER.method.upper()
        log_trade(action, result, volume, price, sl, tp, strategy=strategy_name)
        return True
    else:
        print(f"\nERROR: {action} failed! Code {result.retcode}: {result.comment}")
        log_trade(f"{action}_FAILED", result, volume, price, sl, tp, strategy="FAILED")
        return False


def close_position(position):
    """
    Close an open position.

    Args:
        position: MT5 position object

    Returns:
        bool: True if closed successfully, False otherwise
    """
    try:
        result = close_position_by_ticket(
            ticket=position.ticket,
            symbol=position.symbol,
            volume=position.volume,
            side="BUY" if position.type == mt5.ORDER_TYPE_BUY else "SELL",
            deviation=DEVIATION,
            magic=234000,
            comment="python script close",
        )
    except RuntimeError as exc:
        print(f"ERROR: Failed to close position #{position.ticket}: {exc}")
        return False

    if result.retcode == mt5.TRADE_RETCODE_DONE:
        profit = position.profit
        commission = position.commission if hasattr(position, 'commission') else 0
        swap = position.swap if hasattr(position, 'swap') else 0
        close_price = result.price if hasattr(result, "price") else None

        print(f"OK: Position #{position.ticket} closed | Profit: {profit:.2f}")

        # Log trade close
        TRADE_LOGGER.log_trade_close(
            ticket=position.ticket,
            exit_price=close_price,
            profit=profit,
            commission=commission,
            swap=swap
        )

        # Update daily P/L tracking
        RISK_MANAGER.update_daily_pnl(profit)

        return True
    else:
        print(f"ERROR: Failed to close position #{position.ticket} | Code: {result.retcode}")
        return False


def trading_iteration(symbol):
    """
    Perform one trading iteration: check signal, validate, and execute if appropriate.

    Args:
        symbol: Trading symbol
    """
    print(f"\n{'='*60}")
    print(f" Trading iteration at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*60}")

    # Display daily P/L status
    daily_pnl = RISK_MANAGER.get_daily_pnl()
    can_trade, reason = RISK_MANAGER.can_trade()
    print(f"📊 Daily P/L: ${daily_pnl:.2f} | Status: {reason}")

    if not can_trade:
        print(f"BLOCKED: Trading halted: {reason}")
        return

    # Get combined strategy decision
    action = STRATEGY_MANAGER.generate_combined_signal(symbol)

    if action not in ["BUY", "SELL"]:
        print("WARNING: No trade signal from strategy.")
        return

    # Check existing positions on this symbol
    existing_positions = get_open_positions(symbol)

    if existing_positions:
        # Check if we have opposite positions to close
        for pos in existing_positions:
            pos_type = "BUY" if pos.type == mt5.ORDER_TYPE_BUY else "SELL"

            # If signal is opposite to position, close the position
            if (action == "BUY" and pos_type == "SELL") or (action == "SELL" and pos_type == "BUY"):
                print(f" Signal changed from {pos_type} to {action}. Closing position #{pos.ticket}...")
                close_position(pos)
            elif pos_type == action:
                print(f"ℹ️  Already have a {pos_type} position on {symbol}. Signal agrees.")
                # Check if we can add more positions
                if can_open_new_trade():
                    print(f"💡 Adding another {action} position (pyramiding)...")
                else:
                    print(f"WARNING: Max concurrent trades reached. Skipping additional position.")
                    return

    # Check if we can open new trade
    if not can_open_new_trade():
        open_count = len(get_open_positions())
        print(f"WARNING: Max concurrent trades reached ({open_count}/{MAX_CONCURRENT_TRADES}). Skipping trade.")
        return

    # Execute the trade
    execute_trade(symbol, action)


def run_single_trade():
    """Run a single trade execution (original behavior)."""
    if not initialize_mt5():
        sys.exit(1)

    if not prepare_symbol(SYMBOL):
        mt5.shutdown()
        sys.exit(1)

    trading_iteration(SYMBOL)

    print("\n MT5 connection closed.")
    mt5.shutdown()


def run_continuous_trading():
    """Run continuous trading loop with scheduler."""
    global running

    if not initialize_mt5():
        sys.exit(1)

    if not prepare_symbol(SYMBOL):
        mt5.shutdown()
        sys.exit(1)

    print(f"\nStarting continuous trading mode...")
    print(f"   Trade interval: {TRADE_INTERVAL} seconds")
    print(f"   Max concurrent trades: {MAX_CONCURRENT_TRADES}")
    print(f"   Press CTRL+C to stop gracefully\n")

    iteration_count = 0

    try:
        while running:
            iteration_count += 1

            # Perform trading iteration
            trading_iteration(SYMBOL)

            # Display open positions summary
            positions = get_open_positions()
            print(f"\n📊 Open positions: {len(positions)}/{MAX_CONCURRENT_TRADES}")

            if not running:
                break

            # Wait for next iteration
            print(f"\n⏳ Waiting {TRADE_INTERVAL} seconds until next check...")

            # Sleep in small increments to allow for responsive shutdown
            for _ in range(TRADE_INTERVAL):
                if not running:
                    break
                time.sleep(1)

    except Exception as e:
        print(f"\nERROR: Error in trading loop: {e}")

    finally:
        print(f"\n Shutting down after {iteration_count} iterations...")

        # Generate and display performance report
        try:
            print("\n" + "="*80)
            print("📊 GENERATING PERFORMANCE REPORT...")
            print("="*80)
            ANALYTICS.print_summary_report(days=7)
        except Exception as e:
            print(f"WARNING: Could not generate performance report: {e}")

        print("\n   Closing MT5 connection...")
        mt5.shutdown()
        print("OK: Shutdown complete.")


def load_environment_snapshots(path_str: str):
    """Load pickled market environment snapshots from disk."""

    candidate = Path(path_str)
    if not candidate.is_absolute():
        candidate = Path.cwd() / candidate

    if not candidate.exists():
        print(f"ERROR: Snapshot file not found: {candidate}")
        sys.exit(1)

    try:
        with candidate.open("rb") as handle:
            snapshots = pickle.load(handle)
    except (OSError, pickle.UnpicklingError) as exc:
        print(f"ERROR: Failed to load snapshot data from {candidate}: {exc}")
        sys.exit(1)

    if not isinstance(snapshots, dict):
        print("ERROR: Snapshot payload must be a dictionary keyed by date.")
        sys.exit(1)

    return snapshots, candidate


def run_backtest():
    """Placeholder runner for future backtesting workflows."""

    history_section = BACKTEST_CONFIG.get("history", {})

    print("\n" + "=" * 80)
    print("Backtest configuration preview")
    print("=" * 80)
    print(f"Symbol: {SYMBOL}")
    print(f"Timeframe: {BACKTEST_CONFIG.get('timeframe_key')}")
    print(
        f"History window: {_format_history_bound(history_section, 'start')}"
        f" -> {_format_history_bound(history_section, 'end')}"
    )
    print(
        f"Timezone: {history_section.get('timezone_name')} | "
        f"Align to broker: {history_section.get('align_to_broker_timezone')}"
    )
    print(f"Initial cash: {BACKTEST_CONFIG.get('initial_cash')}")

    commission_cfg = BACKTEST_CONFIG.get("commission", {})
    print(
        "Commission: "
        f"model={commission_cfg.get('model')}, rate={commission_cfg.get('rate')}, "
        f"per_trade={commission_cfg.get('per_trade')}"
    )
    print("\nWARNING: Backtesting execution is not implemented yet. This is a configuration preview only.")


def run_backtest_bt():
    """Run Backtrader backtest via StrategyBridge with Yahoo data feed.

    - Mirrors live decision flow using EnvironmentAgent/StrategyManager
    - Avoids MT5 by disabling RiskManager inside the bridge
    """

    symbol = str(config.get("symbol", "EURUSD")).upper()
    timeframe_key = BACKTEST_CONFIG.get("timeframe_key", "H1")
    history_section = BACKTEST_CONFIG.get("history", {})

    try:
        import backtrader as bt  # type: ignore
        # Compatibility shims for Backtrader 1.9.78
        if not hasattr(bt.stores, "Store") and hasattr(bt.stores, "VCStore"):
            setattr(bt.stores, "Store", bt.stores.VCStore)
        if not hasattr(bt.brokers, "BrokerBase") and hasattr(bt.brokers, "BrokerBack"):
            setattr(bt.brokers, "BrokerBase", bt.brokers.BrokerBack)
        from backtesting.strategy_adapter import StrategyBridge  # type: ignore
    except Exception as exc:
        print(f"ERROR: Backtrader not available: {exc}")
        return

    interval_map = {
        "M1": "1m",
        "M5": "5m",
        "M15": "15m",
        "M30": "30m",
        "H1": "1h",
        "H4": "1h",
        "D1": "1d",
    }
    yf_interval = interval_map.get(str(timeframe_key).upper(), "1h")

    # Fetch data from Yahoo Finance
    df = None
    try:
        import yfinance as yf  # type: ignore
        start = history_section.get("start")
        end = history_section.get("end")
        ticker = "EURUSD=X" if symbol == "EURUSD" else symbol
        if start and end:
            df = yf.download(ticker, start=start, end=end, interval=yf_interval, auto_adjust=False, progress=False)
        else:
            period = "7d" if yf_interval != "1d" else "30d"
            df = yf.download(ticker, period=period, interval=yf_interval, auto_adjust=False, progress=False)
    except Exception as exc:
        print(f"ERROR: Failed to fetch data for backtest: {exc}")

    if df is None or getattr(df, "empty", True):
        # Fallback: try recent 7 days for intraday intervals
        try:
            import yfinance as yf  # type: ignore
            ticker = "EURUSD=X" if symbol == "EURUSD" else symbol
            df = yf.download(ticker, period="7d", interval=yf_interval, auto_adjust=False, progress=False)
            if df is None or getattr(df, "empty", True):
                print("ERROR: No historical data available for backtest.")
                return
            else:
                print("[Backtest] Falling back to last 7 days due to provider limits.")
        except Exception:
            print("ERROR: No historical data available for backtest.")
            return

    # Flatten possible MultiIndex columns from Yahoo and standardize names
    df = df.dropna()
    if hasattr(df, "columns") and any(isinstance(c, tuple) for c in df.columns):
        cols = []
        for c in df.columns:
            if isinstance(c, tuple):
                name = None
                for part in c:
                    if str(part).lower() in {"open", "high", "low", "close", "adj close", "volume"}:
                        name = str(part)
                        break
                cols.append(name or str(c[0]))
            else:
                cols.append(str(c))
        df.columns = cols
    rename = {"Adj Close": "Close", "adj close": "Close"}
    df = df.rename(columns=rename)
    if not set(["Open", "High", "Low", "Close", "Volume"]).issubset(set(df.columns)):
        print("ERROR: Data does not include OHLCV columns after normalization.")
        return
    data = bt.feeds.PandasData(dataname=df[["Open", "High", "Low", "Close", "Volume"]])

    initial_cash = float(BACKTEST_CONFIG.get("initial_cash", 100000.0))
    commission_cfg = BACKTEST_CONFIG.get("commission", {})
    rate = float(commission_cfg.get("rate", 0.0) or 0.0)

    cerebro = bt.Cerebro()
    cerebro.broker.set_cash(initial_cash)
    if rate > 0:
        cerebro.broker.setcommission(commission=rate)
    cerebro.adddata(data, name=f"{symbol}-{timeframe_key}")

    cerebro.addstrategy(
        StrategyBridge,
        strategy_manager=STRATEGY_MANAGER,
        symbol=symbol,
        trade_logger=TRADE_LOGGER,
        risk_manager=None,
        analytics=ANALYTICS,
        agent_kwargs=dict(memory_limits={"short": 64, "mid": 48, "long": 32}),
        default_volume=float(config.get("volume", 0.1)),
    )

    print("\n" + "=" * 80)
    print("Running Backtrader backtest via StrategyBridge")
    print("=" * 80)
    print(f"Symbol: {symbol}")
    print(f"Timeframe: {timeframe_key} (Yahoo: {yf_interval})")
    print(
        "History window: "
        f"{_format_history_bound(history_section, 'start')} "
        f"-> {_format_history_bound(history_section, 'end')}"
    )
    print(f"Initial cash: {initial_cash:.2f} | Commission rate: {rate}")

    try:
        cerebro.run(stdstats=False)
        print(f"[Backtest] Completed. Portfolio value: {cerebro.broker.getvalue():.2f}")
    except Exception as exc:
        print(f"ERROR: Backtest execution failed: {exc}")
    print(
        "\nWARNING:  Backtesting execution is not implemented yet. "
        "This is a configuration preview only."
    )


def run_snapshot_replay():
    """Replay pre-collected market environment snapshots."""

    global running

    snapshots, resolved_path = load_environment_snapshots(SNAPSHOT_PATH)
    environment = MarketEnvironment(snapshots=snapshots, trade_logger=TRADE_LOGGER)
    first_state = environment.reset()

    if first_state is None:
        print(f"WARNING: Snapshot file {resolved_path} does not contain any entries.")
        return

    agent = EnvironmentAgent(
        strategy_manager=STRATEGY_MANAGER,
        symbol=SYMBOL,
        trade_logger=TRADE_LOGGER,
        llm_executor=MARKET_DATA_CONFIG.get("llm_executor"),
        llm_config=MARKET_DATA_CONFIG.get("llm_config"),
    )

    total_snapshots = len(snapshots)
    print("\n" + "=" * 80)
    print(f"Starting snapshot replay ({total_snapshots} snapshots from {resolved_path})")
    print("=" * 80)

    iteration = 0
    while running:
        current_date, snapshot, done = environment.step()
        if snapshot is None:
            print("\n📁 No additional snapshots available. Ending replay.")
            break

        iteration += 1
        date_label = current_date.isoformat() if hasattr(current_date, "isoformat") else str(current_date)

        price_block = snapshot.get("price") if isinstance(snapshot, dict) else None
        price = price_block.get("close") if isinstance(price_block, dict) else None

        news_source = snapshot.get("news") if isinstance(snapshot, dict) else None
        if isinstance(news_source, dict):
            news_items = EnvironmentAgent._ensure_iterable(news_source.get("items"))
        else:
            news_items = EnvironmentAgent._ensure_iterable(news_source)

        filing_q_items = EnvironmentAgent._ensure_iterable(
            snapshot.get("filing_q") if isinstance(snapshot, dict) else None
        )
        filing_k_items = EnvironmentAgent._ensure_iterable(
            snapshot.get("filing_k") if isinstance(snapshot, dict) else None
        )

        future_return = snapshot.get("future_return") if isinstance(snapshot, dict) else None

        step_result = agent.step(
            date_label,
            price,
            filing_k_items,
            filing_q_items,
            news_items,
            future_return=future_return,
        )

        decision = step_result.get("decision", "NONE")
        rationale = step_result.get("rationale", "")
        signals = step_result.get("signals", {})

        print("\n" + "-" * 80)
        print(f"📅 Snapshot #{iteration} | Date: {date_label}")
        if price is not None:
            print(f"💲 Close price: {price}")
        if future_return is not None:
            print(f"🔮 Future return: {future_return:+.2%}")
        print(f"📈 Strategy signals: {signals}")
        print(f"🧠 Decision: {decision}")
        if rationale:
            print(f"   ↳ Rationale: {rationale}")
        if "llm_output" in step_result:
            print(f"🤖 LLM output: {step_result['llm_output']}")

        can_trade, reason = RISK_MANAGER.can_trade()
        print(f"🛡️  Risk check: {reason}")

        if not can_trade:
            print("BLOCKED: Trade skipped due to risk limits.")
        elif decision in {"BUY", "SELL"}:
            print(f"OK: Simulated {decision} action triggered in snapshot mode.")
        else:
            print("ℹ️  No actionable trade signal for this snapshot.")

        if done:
            print("\n📦 Reached end of snapshot dataset.")
            break

    print(f"\n Snapshot replay completed after {iteration} steps.")


# ------------------------------
# MAIN EXECUTION
# ------------------------------
if __name__ == "__main__":
    if MARKET_MODE == "snapshot":
        # Snapshot replay is a lightweight way to test the live pipeline without MT5
        run_snapshot_replay()
    elif MARKET_MODE == "backtest":
        # Defer backtesting to dedicated scripts so main.py stays focused on MT5 live trading
        print("Backtesting is handled by CLI scripts. Try:")
        print("  python scripts/run_backtest.py --symbol EURUSD --period 7 --interval 1h")
        print("Or use your own CSV:  python scripts/run_backtest.py --source csv --csv <path>")
    elif ENABLE_CONTINUOUS:
        # Live trading (continuous loop) via MetaTrader 5
        run_continuous_trading()
    else:
        # Live single-shot trade via MetaTrader 5
        run_single_trade()





