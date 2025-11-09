import MetaTrader5 as mt5
import sys
import json
import os
import time
import signal
import pickle
from datetime import datetime
from pathlib import Path


def _delegated_agents_live_args(argv):
    """Return sanitized argv when delegating to scripts.test_agents_live."""

    delegate_tokens = {"--agents-live", "agents-live", "test-agents-live"}
    if not any(token in argv[1:] for token in delegate_tokens):
        return None

    sanitized = [argv[0]]
    for token in argv[1:]:
        if token in delegate_tokens:
            continue
        sanitized.append(token)

    return sanitized


def _print_agents_live_examples() -> None:
    """Display Markdown examples for the agents-live delegation path."""

    message = """\
## Agents Live quickstart

The delegated `scripts.test_agents_live` harness needs an explicit symbol, date
range, and optional LLM model. Copy one of the setups below or adapt it to your
session:

- **EURUSD — London (Europe/London)**  \
  `python main.py --agents-live --symbol EURUSD --start 2024-02-01 --end 2024-02-07 --model minimax/minimax-m2:free --verbose`
- **GBPUSD — New York (America/New_York)**  \
  `python main.py --agents-live --symbol GBPUSD --start 2024-03-11 --end 2024-03-15 --model mistral/mistral-medium`
- **USDJPY — Tokyo (Asia/Tokyo)**  \
  `python main.py --agents-live --symbol USDJPY --start 2024-04-08 --end 2024-04-12 --model openrouter/auto`
- **XAUUSD — Sydney (Australia/Sydney)**  \
  `python main.py --agents-live --symbol XAUUSD --start 2024-05-06 --end 2024-05-10 --no-llm --verbose`

Dates are interpreted as UTC by the integration test; adjust the window to match
your session. Include `--no-llm` if you do not wish to call the configured LLM
backend.
"""

    print(message)


if __name__ == "__main__":
    delegated = _delegated_agents_live_args(sys.argv)
    if delegated is not None:
        if len(delegated) == 1:
            _print_agents_live_examples()
            raise SystemExit(2)
        sys.argv = delegated
        from scripts.test_agents_live import main as _agents_live_main

        print(
            "[Delegation] Routing to scripts.test_agents_live. "
            "Original main.py live trading workflow will not run."
        )
        _agents_live_main()
        raise SystemExit(0)


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
from trading.execution import (
    get_open_positions as shared_get_open_positions,
    has_open_position as shared_has_open_position,
    can_open_new_trade as shared_can_open_new_trade,
    log_trade as shared_log_trade,
)


MT5_TIMEFRAME_MAP = {
    "M1": mt5.TIMEFRAME_M1,
    "M5": mt5.TIMEFRAME_M5,
    "M15": mt5.TIMEFRAME_M15,
    "M30": mt5.TIMEFRAME_M30,
    "H1": mt5.TIMEFRAME_H1,
    "H4": mt5.TIMEFRAME_H4,
    "D1": mt5.TIMEFRAME_D1,
}

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
        print("For the agents+LLM integration harness, run:")
        print(
            "  python -m scripts.test_agents_live --symbol EURUSD --start 2024-02-01 --end 2024-02-07"
        )
        print("  (alias: python main.py --agents-live --symbol EURUSD --start 2024-02-01 --end 2024-02-07)")
    elif ENABLE_CONTINUOUS:
        # Live trading (continuous loop) via MetaTrader 5
        run_continuous_trading()
    else:
        # Live single-shot trade via MetaTrader 5
        run_single_trade()





