import MetaTrader5 as mt5
from datetime import datetime
import sys
import time


# ============================================================
# CONFIGURATION
# ============================================================
SYMBOL = "EURUSD"       # The symbol to trade
VOLUME = 0.1            # Lot size
SL_POINTS = 100         # Stop Loss (in points)
TP_POINTS = 200         # Take Profit (in points)
DEVIATION = 50          # Max price deviation (in points)
MAGIC_NUMBER = 123456   # Magic number to identify this bot's trades
COMMENT = "Python MT5 Bot Trade"
ORDER_TYPE = mt5.ORDER_TYPE_BUY   # Change to ORDER_TYPE_SELL for short


# ============================================================
# INITIALIZE CONNECTION
# ============================================================
print("🔌 Initializing connection to MetaTrader 5...")

if not mt5.initialize():
    print("❌ initialize() failed, error code:", mt5.last_error())
    sys.exit(1)

account_info = mt5.account_info()
if account_info is None:
    print("❌ Failed to get account info. Make sure MT5 is logged in.")
    mt5.shutdown()
    sys.exit(1)

print(f"✅ Connected to account #{account_info.login} | Balance: {account_info.balance:.2f}\n")


# ============================================================
# PREPARE SYMBOL
# ============================================================
if not mt5.symbol_select(SYMBOL, True):
    print(f"❌ Failed to select symbol {SYMBOL}")
    mt5.shutdown()
    sys.exit(1)

symbol_info = mt5.symbol_info(SYMBOL)
if symbol_info is None:
    print(f"❌ Symbol {SYMBOL} not found.")
    mt5.shutdown()
    sys.exit(1)

# --- Check if trading is allowed ---
if hasattr(symbol_info, "trade_mode"):
    if symbol_info.trade_mode != mt5.SYMBOL_TRADE_MODE_FULL:
        print(f"⚠️ Trading might be restricted for {SYMBOL} (mode: {symbol_info.trade_mode})")
else:
    print("⚠️ Could not verify trade permissions — proceeding anyway.")

print(f"✅ Symbol {SYMBOL} ready for trading.\n")


# ============================================================
# FETCH CURRENT TICK
# ============================================================
tick = mt5.symbol_info_tick(SYMBOL)
if tick is None:
    print(f"❌ Failed to get tick data for {SYMBOL}")
    mt5.shutdown()
    sys.exit(1)

print(f"{SYMBOL} Bid: {tick.bid} | Ask: {tick.ask}")

point = symbol_info.point

if ORDER_TYPE == mt5.ORDER_TYPE_BUY:
    price = round(tick.ask, symbol_info.digits)
    sl = round(price - SL_POINTS * point, symbol_info.digits)
    tp = round(price + TP_POINTS * point, symbol_info.digits)
else:
    price = round(tick.bid, symbol_info.digits)
    sl = round(price + SL_POINTS * point, symbol_info.digits)
    tp = round(price - TP_POINTS * point, symbol_info.digits)


# ============================================================
# CREATE ORDER REQUEST
# ============================================================
request = {
    "action": mt5.TRADE_ACTION_DEAL,
    "symbol": SYMBOL,
    "volume": VOLUME,
    "type": ORDER_TYPE,
    "price": price,
    "sl": sl,
    "tp": tp,
    "deviation": DEVIATION,
    "magic": MAGIC_NUMBER,
    "comment": COMMENT,
    "type_time": mt5.ORDER_TIME_GTC,
    "type_filling": mt5.ORDER_FILLING_FOK,
}

print("\n📤 Sending trade request...")
result = mt5.order_send(request)


# ============================================================
# PROCESS RESULT
# ============================================================
if result is None:
    print("❌ order_send() failed — no result returned.")
    mt5.shutdown()
    sys.exit(1)

print("\nTrade Result:")
print(result)

if result.retcode == mt5.TRADE_RETCODE_DONE:
    print(f"\n✅ Trade executed successfully!")
    print(f"   Ticket: {result.order}")
    print(f"   Price:  {result.price}")
    print(f"   SL:     {sl}")
    print(f"   TP:     {tp}")
else:
    print(f"\n⚠️ Trade failed with retcode={result.retcode}")
    print(f"Comment: {result.comment}")
    print("Check your broker settings, symbol availability, and order parameters.")


# ============================================================
# CLEANUP
# ============================================================
mt5.shutdown()
print("\n🔚 Connection closed.")
