import MetaTrader5 as mt5
import sys
import json
import os
import time
import signal
from datetime import datetime
from strategy import trade_decision

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

SYMBOL = config.get("symbol", "EURUSD")
VOLUME = float(config.get("volume", 0.1))
DEVIATION = int(config.get("deviation", 50))
TRADE_INTERVAL = int(config.get("trade_interval_seconds", 300))  # Default 5 minutes
MAX_CONCURRENT_TRADES = int(config.get("max_concurrent_trades", 3))
ENABLE_CONTINUOUS = config.get("enable_continuous_trading", False)

# Ensure logs folder exists
os.makedirs("logs", exist_ok=True)

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

def log_trade(action, result, price, sl, tp):
    """Log trade execution to file."""
    with open(LOG_PATH, "a") as f:
        f.write(
            f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | "
            f"{action:<12} | "
            f"{result.order:<12} | "
            f"Price: {price:.5f} | SL: {sl:.5f} | TP: {tp:.5f} | Retcode: {result.retcode}\n"
        )


def execute_trade(symbol, action):
    """
    Execute a trade based on the action signal.

    Args:
        symbol: Trading symbol
        action: Trade action ('BUY' or 'SELL')

    Returns:
        Boolean indicating success
    """
    # Determine order type
    order_type = mt5.ORDER_TYPE_BUY if action == "BUY" else mt5.ORDER_TYPE_SELL

    print(f"📤 Sending {action} trade request...")

    # Get latest prices
    tick = mt5.symbol_info_tick(symbol)
    if tick is None:
        print(f"❌ Could not get tick data for {symbol}")
        return False

    price = tick.ask if action == "BUY" else tick.bid

    # Calculate SL/TP (simple fixed pip values for now)
    sl = price - 0.001 if action == "BUY" else price + 0.001
    tp = price + 0.002 if action == "BUY" else price - 0.002

    # Build order request
    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": symbol,
        "volume": VOLUME,
        "type": order_type,
        "price": price,
        "sl": sl,
        "tp": tp,
        "deviation": DEVIATION,
        "magic": 123456,
        "comment": f"Python MT5 Bot {action}",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_FOK,
    }

    # Execute order
    result = mt5.order_send(request)

    if result is None:
        print("❌ Order send failed - no result returned")
        return False

    print(f"\nTrade Result: {result}")

    # Log and report result
    if result.retcode == mt5.TRADE_RETCODE_DONE:
        print(f"\n✅ {action} executed successfully!")
        print(f"   Ticket: {result.order}")
        print(f"   Price:  {result.price}")
        print(f"   SL:     {sl}")
        print(f"   TP:     {tp}")
        log_trade(action, result, price, sl, tp)
        return True
    else:
        print(f"\n❌ {action} failed! Code {result.retcode}: {result.comment}")
        log_trade(f"{action}_FAILED", result, price, sl, tp)
        return False


def close_position(position):
    """
    Close an open position.

    Args:
        position: MT5 position object

    Returns:
        bool: True if closed successfully, False otherwise
    """
    tick = mt5.symbol_info_tick(position.symbol)
    if tick is None:
        print(f"❌ Could not get tick data for {position.symbol}")
        return False

    # Determine close price and order type
    if position.type == mt5.ORDER_TYPE_BUY:
        close_price = tick.bid
        order_type = mt5.ORDER_TYPE_SELL
        action_str = "CLOSE_BUY"
    else:
        close_price = tick.ask
        order_type = mt5.ORDER_TYPE_BUY
        action_str = "CLOSE_SELL"

    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": position.symbol,
        "volume": position.volume,
        "type": order_type,
        "position": position.ticket,
        "price": close_price,
        "deviation": DEVIATION,
        "magic": 234000,
        "comment": "python script close",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_FOK,
    }

    result = mt5.order_send(request)

    if result.retcode == mt5.TRADE_RETCODE_DONE:
        profit = position.profit
        print(f"✅ Position #{position.ticket} closed | Profit: {profit:.2f}")
        return True
    else:
        print(f"❌ Failed to close position #{position.ticket} | Code: {result.retcode}")
        return False


def trading_iteration(symbol):
    """
    Perform one trading iteration: check signal, validate, and execute if appropriate.

    Args:
        symbol: Trading symbol
    """
    print(f"\n{'='*60}")
    print(f"🔄 Trading iteration at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*60}")

    # Get strategy decision
    action = trade_decision(symbol)

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
        print("   Closing MT5 connection...")
        mt5.shutdown()
        print("✅ Shutdown complete.")


# ------------------------------
# MAIN EXECUTION
# ------------------------------
if __name__ == "__main__":
    if ENABLE_CONTINUOUS:
        run_continuous_trading()
    else:
        run_single_trade()
