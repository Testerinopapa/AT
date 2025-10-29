import MetaTrader5 as mt5
import sys
import json
import os
from datetime import datetime
from strategy import trade_decision

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

# Ensure logs folder exists
os.makedirs("logs", exist_ok=True)

# ------------------------------
# INITIALIZE MT5
# ------------------------------
print("🔌 Initializing MetaTrader 5...")

if not mt5.initialize():
    print("❌ MT5 initialization failed:", mt5.last_error())
    sys.exit(1)

account_info = mt5.account_info()
if account_info is None:
    print("❌ Could not retrieve account info. Is MetaTrader 5 logged in?")
    sys.exit(1)

print(f"✅ Connected to account #{account_info.login} | Balance: {account_info.balance:.2f}\n")

# ------------------------------
# SYMBOL PREPARATION
# ------------------------------
if not mt5.symbol_select(SYMBOL, True):
    print(f"❌ Could not select symbol {SYMBOL}")
    mt5.shutdown()
    sys.exit(1)

symbol_info = mt5.symbol_info(SYMBOL)
if not symbol_info:
    print(f"❌ Symbol {SYMBOL} not found.")
    mt5.shutdown()
    sys.exit(1)

print(f"✅ Symbol {SYMBOL} ready for trading.\n")

# ------------------------------
# STRATEGY DECISION
# ------------------------------
action = trade_decision(SYMBOL)

if action not in ["BUY", "SELL"]:
    print("⚠️ No trade signal from strategy.")
    mt5.shutdown()
    sys.exit(0)

# Determine order type
order_type = mt5.ORDER_TYPE_BUY if action == "BUY" else mt5.ORDER_TYPE_SELL

print(f"📤 Sending {action} trade request...")

# Get latest prices
tick = mt5.symbol_info_tick(SYMBOL)
price = tick.ask if action == "BUY" else tick.bid

sl = price - 0.001 if action == "BUY" else price + 0.001
tp = price + 0.002 if action == "BUY" else price - 0.002

# ------------------------------
# ORDER REQUEST
# ------------------------------
request = {
    "action": mt5.TRADE_ACTION_DEAL,
    "symbol": SYMBOL,
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

# ------------------------------
# EXECUTE ORDER
# ------------------------------
result = mt5.order_send(request)

print("\nTrade Result:")
print(result)

# ------------------------------
# LOGGING
# ------------------------------
def log_trade(action, result, price, sl, tp):
    with open(LOG_PATH, "a") as f:
        f.write(
            f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | "
            f"{action:<4} | "
            f"{result.order:<12} | "
            f"Price: {price:.5f} | SL: {sl:.5f} | TP: {tp:.5f} | Retcode: {result.retcode}\n"
        )

if result.retcode == mt5.TRADE_RETCODE_DONE:
    print(f"\n✅ {action} executed successfully!")
    print(f"   Ticket: {result.order}")
    print(f"   Price:  {result.price}")
    print(f"   SL:     {sl}")
    print(f"   TP:     {tp}")
    log_trade(action, result, price, sl, tp)
else:
    print(f"\n❌ {action} failed! Code {result.retcode}: {result.comment}")
    log_trade(f"{action}_FAILED", result, price, sl, tp)

# ------------------------------
# CLEANUP
# ------------------------------
print("\n🔚 MT5 connection closed.")
mt5.shutdown()
