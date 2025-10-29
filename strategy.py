import MetaTrader5 as mt5

def trade_decision(symbol: str) -> str:
    """
    Returns one of: 'BUY', 'SELL', or 'NONE'
    based on last two 1-minute candle closes.
    """
    rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M1, 0, 20)
    if rates is None or len(rates) < 2:
        print("[Strategy] Not enough data.")
        return "NONE"

    last_close = rates[-1]['close']
    prev_close = rates[-2]['close']

    if last_close > prev_close:
        print(f"[Strategy] Detected upward momentum → BUY signal.")
        return "BUY"
    elif last_close < prev_close:
        print(f"[Strategy] Detected downward momentum → SELL signal.")
        return "SELL"
    else:
        print(f"[Strategy] No clear trend → no trade.")
        return "NONE"
