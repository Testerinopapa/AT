# core/portfolio/risk_manager.py
from typing import Dict, Optional
import numpy as np
from .position_tracker import PositionTracker

class RiskManager:
    """
    Manages position sizing and risk limits
    Replaces the various sizers with unified risk management
    """
    
    def __init__(self, 
                 max_position_size: float = 0.1,  # 10% of portfolio per trade
                 max_daily_loss: float = 0.02,   # 2% max daily loss
                 risk_per_trade: float = 0.01,   # 1% risk per trade
                 volatility_lookback: int = 20):
        
        self.max_position_size = max_position_size
        self.max_daily_loss = max_daily_loss
        self.risk_per_trade = risk_per_trade
        self.volatility_lookback = volatility_lookback
        
    def calculate_position_size(self, 
                              portfolio: PositionTracker,
                              entry_price: float,
                              stop_loss: float,
                              symbol: str) -> float:
        """
        Calculate position size based on risk parameters
        Consolidates your various sizer approaches
        """
        portfolio_equity = portfolio.get_total_equity()
        
        # Method 1: Fixed risk percentage
        risk_amount = portfolio_equity * self.risk_per_trade
        stop_distance = abs(entry_price - stop_loss)
        
        if stop_distance == 0:
            return 0
            
        base_size = risk_amount / stop_distance
        
        # Method 2: Portfolio percentage cap
        max_size_by_portfolio = portfolio_equity * self.max_position_size / entry_price
        
        # Use the more conservative approach
        position_size = min(base_size, max_size_by_portfolio)
        
        return max(position_size, 0)  # Ensure non-negative
    
    def validate_trade(self, 
                      portfolio: PositionTracker,
                      symbol: str,
                      size: float,
                      price: float) -> Dict[str, bool]:
        """
        Check if trade meets risk criteria
        Returns validation result with reasons
        """
        validation = {
            'is_valid': True,
            'reasons': [],
            'adjusted_size': size
        }
        
        equity = portfolio.get_total_equity()
        
        # Check position size limits
        position_value = size * price
        if position_value > equity * self.max_position_size:
            validation['is_valid'] = False
            validation['reasons'].append(f"Position size {position_value/equity:.1%} exceeds max {self.max_position_size:.1%}")
            # Suggest adjusted size
            validation['adjusted_size'] = (equity * self.max_position_size) / price
        
        # Check if already in position
        if portfolio.has_position(symbol):
            validation['is_valid'] = False
            validation['reasons'].append(f"Already in position for {symbol}")
        
        # Check daily loss limits (simplified)
        if len(portfolio.equity_history) > 1:
            daily_return = (portfolio.equity_history[-1] / portfolio.equity_history[-2] - 1)
            if daily_return < -self.max_daily_loss:
                validation['is_valid'] = False
                validation['reasons'].append(f"Daily loss {daily_return:.1%} exceeds limit {-self.max_daily_loss:.1%}")
        
        return validation
    
    def calculate_dynamic_stops(self, 
                              df: 'pd.DataFrame',
                              entry_price: float,
                              side: str) -> Dict[str, float]:
        """
        Calculate dynamic stop loss and take profit levels
        Based on market volatility and your strategy parameters
        """
        # Use ATR for volatility-based stops
        if len(df) >= self.volatility_lookback:
            highs = df['high'].tail(self.volatility_lookback)
            lows = df['low'].tail(self.volatility_lookback)
            atr = (highs - lows).mean()
        else:
            atr = entry_price * 0.002  # Default 0.2%
        
        if side == 'BUY':
            sl = entry_price - 2 * atr  # 2 ATR stop loss
            tp = entry_price + 3 * atr  # 3 ATR take profit
        else:  # SELL
            sl = entry_price + 2 * atr
            tp = entry_price - 3 * atr
        
        return {'sl': sl, 'tp': tp, 'atr': atr}