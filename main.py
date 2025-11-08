import MetaTrader5 as mt5
import sys
import json
import os
import time
import signal
import pickle
from datetime import datetime
from pathlib import Path


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

from backtesting.config import (
    MT5_TIMEFRAME_MAP,
    format_history_bound,
    parse_backtest_config,
)
from backtesting.runner import run_backtest as run_backtest_workflow
from trading import (
    can_open_new_trade as shared_can_open_new_trade,
    close_position as shared_close_position,
    execute_trade as shared_execute_trade,
    get_open_positions as shared_get_open_positions,
    has_open_position as shared_has_open_position,
    log_trade as shared_log_trade,
)


# ------------------------------
# GLOBAL STATE
# ------------------------------
running = True  # Flag for graceful shutdown


def signal_handler(sig, frame):
    """Handle CTRL+C for graceful shutdown."""
    global running
    print("\n\n⚠️  Shutdown signal received. Closing positions and exiting gracefully...")
    running = False


# Register signal handler
signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

# ------------------------------
# CONFIGURATION
# ------------------------------
CONFIG_PATH = os.path.join("config", "settings.json")
LOG_PATH = os.path.join("logs", "trades.log")

# Load config
try:
    with open(CONFIG_PATH, "r") as f:
        config = json.load(f)
except FileNotFoundError:
    print("❌ settings.json not found. Please create config/settings.json")
    sys.exit(1)

MARKET_DATA_CONFIG = config.get("market_data", {}) if isinstance(config, dict) else {}
ALLOWED_MARKET_MODES = {"live", "snapshot", "backtest"}
MARKET_MODE = str(MARKET_DATA_CONFIG.get("mode", "live")).strip().lower()
if MARKET_MODE not in ALLOWED_MARKET_MODES:
    print(f"⚠️  Unknown market_data.mode '{MARKET_MODE}' - defaulting to live mode.")
    MARKET_MODE = "live"

SNAPSHOT_PATH = MARKET_DATA_CONFIG.get("snapshot_path", "data/env_data.pkl")
BACKTEST_CONFIG = parse_backtest_config(MARKET_DATA_CONFIG.get("backtest"))

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
    history_section = BACKTEST_CONFIG.get("history", {})
    print(
        f"[Config] Backtest timeframe: {BACKTEST_CONFIG.get('timeframe_key')}"
    )
    print(
        "[Config] Backtest history window: "
        f"{format_history_bound(history_section, 'start')}"
        f" → {format_history_bound(history_section, 'end')}"
    )
    timezone_label = history_section.get("timezone_name", "UTC")
    if history_section.get("timezone") is None and timezone_label:
        timezone_label += " (unresolved)"
    print(f"[Config] Backtest timezone: {timezone_label}")
    align_flag = history_section.get("align_to_broker_timezone", False)
    print(f"[Config] Align to broker timezone: {align_flag}")
    print(
        f"[Config] Backtest initial cash: {BACKTEST_CONFIG.get('initial_cash'):.2f}"
    )
    commission_cfg = BACKTEST_CONFIG.get("commission", {})
    print(
        "[Config] Commission model: "
        f"{commission_cfg.get('model')} (rate={commission_cfg.get('rate')}, per_trade={commission_cfg.get('per_trade')})"
    )

# Initialize Trade Logger and Analytics
TRADE_LOGGER = TradeLogger()
ANALYTICS = PerformanceAnalytics()
print(f"[Config] Trade Logger and Analytics initialized")

# ------------------------------
# HELPER FUNCTIONS
# ------------------------------
def initialize_mt5():
    """Initialize MT5 connection and validate account."""
    print("🔌 Initializing MetaTrader 5...")

    if not mt5.initialize():
        print("❌ MT5 initialization failed:", mt5.last_error())
        return False

    account_info = mt5.account_info()
    if account_info is None:
        print("❌ Could not retrieve account info. Is MetaTrader 5 logged in?")
        return False

    print(f"✅ Connected to account #{account_info.login} | Balance: {account_info.balance:.2f}\n")
    return True


def prepare_symbol(symbol):
    """Prepare and validate trading symbol."""
    if not mt5.symbol_select(symbol, True):
        print(f"❌ Could not select symbol {symbol}")
        return False

    symbol_info = mt5.symbol_info(symbol)
    if not symbol_info:
        print(f"❌ Symbol {symbol} not found.")
        return False

    print(f"✅ Symbol {symbol} ready for trading.\n")
    return True


def get_open_positions(symbol=None):
    """
    Get open positions, optionally filtered by symbol.

    Args:
        symbol: Optional symbol to filter positions

    Returns:
        List of open positions
    """
    positions = shared_get_open_positions(symbol=symbol, mt5_module=mt5)
    return list(positions)


def has_open_position(symbol):
    """
    Check if there's already an open position for the symbol.

    Args:
        symbol: Trading symbol to check

    Returns:
        Boolean indicating if position exists
    """
    return shared_has_open_position(symbol, mt5_module=mt5)


def can_open_new_trade():
    """
    Check if we can open a new trade based on max concurrent trades limit.

    Returns:
        Boolean indicating if new trade can be opened
    """
    return shared_can_open_new_trade(
        max_concurrent_trades=MAX_CONCURRENT_TRADES,
        get_positions=get_open_positions,
    )

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
    shared_log_trade(
        symbol=SYMBOL,
        action=action,
        result=result,
        volume=volume,
        price=price,
        sl=sl,
        tp=tp,
        strategy=strategy,
        trade_logger=TRADE_LOGGER,
        log_path=LOG_PATH,
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
    return shared_execute_trade(
        symbol=symbol,
        action=action,
        risk_manager=RISK_MANAGER,
        trade_logger=TRADE_LOGGER,
        strategy_manager=STRATEGY_MANAGER,
        deviation=DEVIATION,
        log_path=LOG_PATH,
        default_volume=VOLUME,
        config=config,
        magic=123456,
        comment_prefix="Python MT5 Bot",
        mt5_module=mt5,
        order_sender=lambda request: mt5.order_send(request.to_request()),
    )


def close_position(position):
    """
    Close an open position.

    Args:
        position: MT5 position object

    Returns:
        bool: True if closed successfully, False otherwise
    """
    return shared_close_position(
        position,
        trade_logger=TRADE_LOGGER,
        risk_manager=RISK_MANAGER,
        deviation=DEVIATION,
        magic=234000,
        comment="python script close",
        mt5_module=mt5,
    )


def trading_iteration(symbol):
    """
    Perform one trading iteration: check signal, validate, and execute if appropriate.

    Args:
        symbol: Trading symbol
    """
    print(f"\n{'='*60}")
    print(f"🔄 Trading iteration at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*60}")

    # Display daily P/L status
    daily_pnl = RISK_MANAGER.get_daily_pnl()
    can_trade, reason = RISK_MANAGER.can_trade()
    print(f"📊 Daily P/L: ${daily_pnl:.2f} | Status: {reason}")

    if not can_trade:
        print(f"🚫 Trading halted: {reason}")
        return

    # Get combined strategy decision
    action = STRATEGY_MANAGER.generate_combined_signal(symbol)

    if action not in ["BUY", "SELL"]:
        print("⚠️  No trade signal from strategy.")
        return

    # Check existing positions on this symbol
    existing_positions = get_open_positions(symbol)

    if existing_positions:
        # Check if we have opposite positions to close
        for pos in existing_positions:
            pos_type = "BUY" if pos.type == mt5.ORDER_TYPE_BUY else "SELL"

            # If signal is opposite to position, close the position
            if (action == "BUY" and pos_type == "SELL") or (action == "SELL" and pos_type == "BUY"):
                print(f"🔄 Signal changed from {pos_type} to {action}. Closing position #{pos.ticket}...")
                close_position(pos)
            elif pos_type == action:
                print(f"ℹ️  Already have a {pos_type} position on {symbol}. Signal agrees.")
                # Check if we can add more positions
                if can_open_new_trade():
                    print(f"💡 Adding another {action} position (pyramiding)...")
                else:
                    print(f"⚠️  Max concurrent trades reached. Skipping additional position.")
                    return

    # Check if we can open new trade
    if not can_open_new_trade():
        open_count = len(get_open_positions())
        print(f"⚠️  Max concurrent trades reached ({open_count}/{MAX_CONCURRENT_TRADES}). Skipping trade.")
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

    print("\n🔚 MT5 connection closed.")
    mt5.shutdown()


def run_continuous_trading():
    """Run continuous trading loop with scheduler."""
    global running

    if not initialize_mt5():
        sys.exit(1)

    if not prepare_symbol(SYMBOL):
        mt5.shutdown()
        sys.exit(1)

    print(f"\n🔁 Starting continuous trading mode...")
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
        print(f"\n❌ Error in trading loop: {e}")

    finally:
        print(f"\n🔚 Shutting down after {iteration_count} iterations...")

        # Generate and display performance report
        try:
            print("\n" + "="*80)
            print("📊 GENERATING PERFORMANCE REPORT...")
            print("="*80)
            ANALYTICS.print_summary_report(days=7)
        except Exception as e:
            print(f"⚠️  Could not generate performance report: {e}")

        print("\n   Closing MT5 connection...")
        mt5.shutdown()
        print("✅ Shutdown complete.")


def load_environment_snapshots(path_str: str):
    """Load pickled market environment snapshots from disk."""

    candidate = Path(path_str)
    if not candidate.is_absolute():
        candidate = Path.cwd() / candidate

    if not candidate.exists():
        print(f"❌ Snapshot file not found: {candidate}")
        sys.exit(1)

    try:
        with candidate.open("rb") as handle:
            snapshots = pickle.load(handle)
    except (OSError, pickle.UnpicklingError) as exc:
        print(f"❌ Failed to load snapshot data from {candidate}: {exc}")
        sys.exit(1)

    if not isinstance(snapshots, dict):
        print("❌ Snapshot payload must be a dictionary keyed by date.")
        sys.exit(1)

    return snapshots, candidate


def run_backtest():
    """Run the configured backtest using the Backtrader bridge."""

    print("\n" + "=" * 80)
    print("🧪 Starting Backtrader backtest")
    print("=" * 80)

    history_section = BACKTEST_CONFIG.get("history", {})
    print(f"[Backtest] Timeframe: {BACKTEST_CONFIG.get('timeframe_key')}")
    print(
        f"[Backtest] History: {format_history_bound(history_section, 'start')}"
        f" → {format_history_bound(history_section, 'end')}"
    )
    tz_label = history_section.get("timezone_name", "UTC")
    if history_section.get("timezone") is None and tz_label:
        tz_label = f"{tz_label} (unresolved)"
    print(f"[Backtest] Timezone: {tz_label}")
    print(f"[Backtest] Align to broker timezone: {history_section.get('align_to_broker_timezone')}")
    print(f"[Backtest] Initial cash: {BACKTEST_CONFIG.get('initial_cash')}")
    commission_cfg = BACKTEST_CONFIG.get('commission', {})
    print(
        "[Backtest] Commission: "
        f"model={commission_cfg.get('model')}, rate={commission_cfg.get('rate')}, "
        f"per_trade={commission_cfg.get('per_trade')}"
    )

    try:
        run_backtest_workflow(
            config=config,
            strategy_manager=STRATEGY_MANAGER,
            risk_manager=RISK_MANAGER,
            trade_logger=TRADE_LOGGER,
            analytics=ANALYTICS,
        )
    except Exception as exc:
        print(f"❌ Backtest execution failed: {exc}")
        raise
    finally:
        print("\n🔚 MT5 connection closed.")
        mt5.shutdown()
        if hasattr(TRADE_LOGGER, "text_log"):
            try:
                with open(TRADE_LOGGER.text_log, "a"):
                    pass
            except OSError:
                print("⚠️  Unable to touch trade log file during shutdown.")


def run_snapshot_replay():
    """Replay pre-collected market environment snapshots."""

    global running

    snapshots, resolved_path = load_environment_snapshots(SNAPSHOT_PATH)
    environment = MarketEnvironment(snapshots=snapshots, trade_logger=TRADE_LOGGER)
    first_state = environment.reset()

    if first_state is None:
        print(f"⚠️  Snapshot file {resolved_path} does not contain any entries.")
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
    print(f"🧪 Starting snapshot replay ({total_snapshots} snapshots from {resolved_path})")
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
            print("🚫 Trade skipped due to risk limits.")
        elif decision in {"BUY", "SELL"}:
            print(f"✅ Simulated {decision} action triggered in snapshot mode.")
        else:
            print("ℹ️  No actionable trade signal for this snapshot.")

        if done:
            print("\n📦 Reached end of snapshot dataset.")
            break

    print(f"\n🔚 Snapshot replay completed after {iteration} steps.")


# ------------------------------
# MAIN EXECUTION
# ------------------------------
if __name__ == "__main__":
    if MARKET_MODE == "snapshot":
        run_snapshot_replay()
    elif MARKET_MODE == "backtest":
        run_backtest()
    elif ENABLE_CONTINUOUS:
        run_continuous_trading()
    else:
        run_single_trade()
