"""
Risk Management Module for TraderBot

This module provides comprehensive risk management features including:
- Dynamic lot sizing based on account balance and risk percentage
- Automatic stop-loss and take-profit calculation
- Daily loss/profit limits with auto-disable
- Position size validation
- Profit/Loss tracking and logging
"""

import MetaTrader5 as mt5
import numpy as np
from datetime import datetime, date
from typing import Dict, Optional, Tuple
import json
import os


class RiskManager:
    """
    Manages risk for trading operations including position sizing,
    stop-loss/take-profit calculation, and daily limits.
    """
    
    def __init__(self, config: Dict):
        """
        Initialize RiskManager with configuration.
        
        Args:
            config: Dictionary containing risk management settings
        """
        self.config = config
        self.risk_config = config.get("risk_management", {})
        
        # Risk parameters
        self.risk_percentage = float(self.risk_config.get("risk_percentage", 1.0))  # % of balance per trade
        self.max_risk_percentage = float(self.risk_config.get("max_risk_percentage", 5.0))  # Max % risk
        self.min_lot_size = float(self.risk_config.get("min_lot_size", 0.01))
        self.max_lot_size = float(self.risk_config.get("max_lot_size", 1.0))
        
        # SL/TP calculation method: "fixed_pips", "atr", "percentage"
        self.sl_method = self.risk_config.get("sl_method", "atr")
        self.tp_method = self.risk_config.get("tp_method", "atr")
        
        # Fixed pips (if using fixed_pips method)
        self.fixed_sl_pips = float(self.risk_config.get("fixed_sl_pips", 100))
        self.fixed_tp_pips = float(self.risk_config.get("fixed_tp_pips", 200))
        
        # ATR multipliers (if using atr method)
        self.atr_period = int(self.risk_config.get("atr_period", 14))
        self.atr_sl_multiplier = float(self.risk_config.get("atr_sl_multiplier", 2.0))
        self.atr_tp_multiplier = float(self.risk_config.get("atr_tp_multiplier", 3.0))
        
        # Percentage (if using percentage method)
        self.sl_percentage = float(self.risk_config.get("sl_percentage", 0.5))  # 0.5%
        self.tp_percentage = float(self.risk_config.get("tp_percentage", 1.0))  # 1.0%
        
        # Daily limits
        self.daily_loss_limit = float(self.risk_config.get("daily_loss_limit", 500.0))  # $ amount
        self.daily_profit_target = float(self.risk_config.get("daily_profit_target", 1000.0))  # $ amount
        self.enable_daily_limits = self.risk_config.get("enable_daily_limits", True)
        
        # P/L tracking
        self.daily_pnl_file = "logs/daily_pnl.json"
        self.ensure_pnl_file()
        
        # Cache
        self._atr_cache = {}
        
    def ensure_pnl_file(self):
        """Ensure the daily P/L tracking file exists."""
        os.makedirs("logs", exist_ok=True)
        if not os.path.exists(self.daily_pnl_file):
            with open(self.daily_pnl_file, "w") as f:
                json.dump({}, f)
    
    def calculate_lot_size(self, symbol: str, stop_loss_pips: float, account_balance: float = None) -> float:
        """
        Calculate optimal lot size based on risk percentage and stop-loss distance.
        
        Args:
            symbol: Trading symbol
            stop_loss_pips: Stop-loss distance in pips
            account_balance: Account balance (if None, fetches from MT5)
        
        Returns:
            Calculated lot size
        """
        if account_balance is None:
            account_info = mt5.account_info()
            if account_info is None:
                print("⚠️  Could not fetch account info, using min lot size")
                return self.min_lot_size
            account_balance = account_info.balance
        
        # Get symbol info for pip value calculation
        symbol_info = mt5.symbol_info(symbol)
        if symbol_info is None:
            print(f"⚠️  Could not fetch symbol info for {symbol}, using min lot size")
            return self.min_lot_size
        
        # Calculate risk amount in account currency
        risk_amount = account_balance * (self.risk_percentage / 100.0)
        
        # Calculate pip value (for 1 standard lot)
        # For most forex pairs: pip_value = (0.0001 / current_price) * contract_size
        tick = mt5.symbol_info_tick(symbol)
        if tick is None:
            return self.min_lot_size
        
        # Get contract size (usually 100,000 for forex)
        contract_size = symbol_info.trade_contract_size
        
        # Calculate pip value for 1 lot
        if symbol_info.digits == 5 or symbol_info.digits == 3:
            point_value = symbol_info.point * 10  # For 5-digit brokers
        else:
            point_value = symbol_info.point
        
        pip_value_per_lot = point_value * contract_size
        
        # Calculate lot size: risk_amount / (stop_loss_pips * pip_value_per_lot)
        if stop_loss_pips <= 0:
            print("⚠️  Invalid stop-loss distance, using min lot size")
            return self.min_lot_size
        
        lot_size = risk_amount / (stop_loss_pips * pip_value_per_lot)
        
        # Apply min/max constraints
        lot_size = max(self.min_lot_size, min(lot_size, self.max_lot_size))
        
        # Round to symbol's volume step
        volume_step = symbol_info.volume_step
        lot_size = round(lot_size / volume_step) * volume_step
        
        return lot_size
    
    def calculate_atr(self, symbol: str, period: int = None, timeframe: int = mt5.TIMEFRAME_H1) -> Optional[float]:
        """
        Calculate Average True Range (ATR) for volatility-based SL/TP.
        
        Args:
            symbol: Trading symbol
            period: ATR period (default: self.atr_period)
            timeframe: Timeframe for calculation
        
        Returns:
            ATR value or None if calculation fails
        """
        if period is None:
            period = self.atr_period
        
        # Check cache
        cache_key = f"{symbol}_{period}_{timeframe}"
        if cache_key in self._atr_cache:
            cached_time, cached_atr = self._atr_cache[cache_key]
            # Cache valid for 1 minute
            if (datetime.now() - cached_time).seconds < 60:
                return cached_atr
        
        # Fetch candles (need period + 1 for TR calculation)
        rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, period + 1)
        if rates is None or len(rates) < period + 1:
            return None
        
        # Calculate True Range
        high = rates['high']
        low = rates['low']
        close = rates['close']
        
        tr = np.maximum(
            high[1:] - low[1:],  # High - Low
            np.maximum(
                np.abs(high[1:] - close[:-1]),  # |High - Previous Close|
                np.abs(low[1:] - close[:-1])    # |Low - Previous Close|
            )
        )
        
        # Calculate ATR (simple moving average of TR)
        atr = np.mean(tr[-period:])
        
        # Cache result
        self._atr_cache[cache_key] = (datetime.now(), atr)
        
        return atr
    
    def calculate_sl_tp(self, symbol: str, action: str, entry_price: float) -> Tuple[float, float]:
        """
        Calculate stop-loss and take-profit levels.
        
        Args:
            symbol: Trading symbol
            action: Trade action ('BUY' or 'SELL')
            entry_price: Entry price
        
        Returns:
            Tuple of (stop_loss, take_profit)
        """
        symbol_info = mt5.symbol_info(symbol)
        if symbol_info is None:
            # Fallback to fixed pips
            sl = entry_price - 0.001 if action == "BUY" else entry_price + 0.001
            tp = entry_price + 0.002 if action == "BUY" else entry_price - 0.002
            return sl, tp
        
        point = symbol_info.point
        
        # Calculate SL
        if self.sl_method == "atr":
            atr = self.calculate_atr(symbol)
            if atr is not None:
                sl_distance = atr * self.atr_sl_multiplier
            else:
                # Fallback to fixed pips
                sl_distance = self.fixed_sl_pips * point * 10
        elif self.sl_method == "percentage":
            sl_distance = entry_price * (self.sl_percentage / 100.0)
        else:  # fixed_pips
            sl_distance = self.fixed_sl_pips * point * 10
        
        # Calculate TP
        if self.tp_method == "atr":
            atr = self.calculate_atr(symbol)
            if atr is not None:
                tp_distance = atr * self.atr_tp_multiplier
            else:
                # Fallback to fixed pips
                tp_distance = self.fixed_tp_pips * point * 10
        elif self.tp_method == "percentage":
            tp_distance = entry_price * (self.tp_percentage / 100.0)
        else:  # fixed_pips
            tp_distance = self.fixed_tp_pips * point * 10
        
        # Apply direction
        if action == "BUY":
            sl = entry_price - sl_distance
            tp = entry_price + tp_distance
        else:  # SELL
            sl = entry_price + sl_distance
            tp = entry_price - tp_distance
        
        return sl, tp
    
    def get_daily_pnl(self) -> float:
        """
        Get today's profit/loss from tracking file.
        
        Returns:
            Today's P/L in account currency
        """
        try:
            with open(self.daily_pnl_file, "r") as f:
                data = json.load(f)
            
            today = str(date.today())
            return data.get(today, {}).get("pnl", 0.0)
        except Exception as e:
            print(f"⚠️  Error reading daily P/L: {e}")
            return 0.0
    
    def update_daily_pnl(self, profit: float):
        """
        Update today's profit/loss.
        
        Args:
            profit: Profit/loss from closed trade
        """
        try:
            with open(self.daily_pnl_file, "r") as f:
                data = json.load(f)
            
            today = str(date.today())
            if today not in data:
                data[today] = {"pnl": 0.0, "trades": 0}
            
            data[today]["pnl"] += profit
            data[today]["trades"] += 1
            
            with open(self.daily_pnl_file, "w") as f:
                json.dump(data, f, indent=2)
            
            print(f"📊 Daily P/L updated: {data[today]['pnl']:.2f} ({data[today]['trades']} trades)")
        except Exception as e:
            print(f"⚠️  Error updating daily P/L: {e}")
    
    def can_trade(self) -> Tuple[bool, str]:
        """
        Check if trading is allowed based on daily limits.
        
        Returns:
            Tuple of (can_trade: bool, reason: str)
        """
        if not self.enable_daily_limits:
            return True, "Daily limits disabled"
        
        daily_pnl = self.get_daily_pnl()
        
        # Check daily loss limit
        if daily_pnl <= -self.daily_loss_limit:
            return False, f"Daily loss limit reached: {daily_pnl:.2f}"
        
        # Check daily profit target
        if daily_pnl >= self.daily_profit_target:
            return False, f"Daily profit target reached: {daily_pnl:.2f}"
        
        return True, f"Daily P/L: {daily_pnl:.2f}"
    
    def validate_trade(self, symbol: str, action: str, lot_size: float) -> Tuple[bool, str]:
        """
        Validate if a trade meets risk management criteria.
        
        Args:
            symbol: Trading symbol
            action: Trade action
            lot_size: Proposed lot size
        
        Returns:
            Tuple of (is_valid: bool, reason: str)
        """
        # Check daily limits
        can_trade, reason = self.can_trade()
        if not can_trade:
            return False, reason
        
        # Check lot size
        if lot_size < self.min_lot_size:
            return False, f"Lot size {lot_size} below minimum {self.min_lot_size}"
        
        if lot_size > self.max_lot_size:
            return False, f"Lot size {lot_size} above maximum {self.max_lot_size}"
        
        # Check symbol info
        symbol_info = mt5.symbol_info(symbol)
        if symbol_info is None:
            return False, f"Could not fetch symbol info for {symbol}"
        
        if lot_size < symbol_info.volume_min:
            return False, f"Lot size {lot_size} below symbol minimum {symbol_info.volume_min}"
        
        if lot_size > symbol_info.volume_max:
            return False, f"Lot size {lot_size} above symbol maximum {symbol_info.volume_max}"
        
        return True, "Trade validated"

