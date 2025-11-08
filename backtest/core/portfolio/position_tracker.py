# core/portfolio/position_tracker.py
from dataclasses import dataclass
from typing import Optional, Dict, Any
import pandas as pd

@dataclass
class Position:
    symbol: str
    side: str  # 'BUY' or 'SELL'
    entry_price: float
    size: float
    entry_time: Any
    sl_price: Optional[float] = None
    tp_price: Optional[float] = None

class PositionTracker:
    """
    Tracks all open positions and their state
    """
    
    def __init__(self, initial_balance: float = 10000):
        self.positions: Dict[str, Position] = {}
        self.initial_balance = initial_balance
        self.cash = initial_balance
        self.equity_history = []
        self.trade_history = []
    
    def open_position(self, symbol: str, side: str, price: float, 
                     size: float, sl: float = None, tp: float = None) -> Position:
        """Open a new position"""
        position = Position(
            symbol=symbol,
            side=side,
            entry_price=price,
            size=size,
            entry_time=pd.Timestamp.now(),
            sl_price=sl,
            tp_price=tp
        )
        
        self.positions[symbol] = position
        self.cash -= price * size  # Simplified - adjust for leverage etc.
        
        self.trade_history.append({
            'action': 'OPEN',
            'symbol': symbol,
            'side': side,
            'price': price,
            'size': size,
            'timestamp': position.entry_time
        })
        
        return position
    
    def close_position(self, symbol: str, exit_price: float, reason: str = "MANUAL"):
        """Close an existing position"""
        if symbol not in self.positions:
            return None
        
        position = self.positions[symbol]
        
        # Calculate P&L
        if position.side == 'BUY':
            pnl = (exit_price - position.entry_price) * position.size
        else:  # SELL
            pnl = (position.entry_price - exit_price) * position.size
        
        self.cash += position.entry_price * position.size + pnl
        
        # Record trade
        trade_record = {
            'action': 'CLOSE',
            'symbol': symbol,
            'side': position.side,
            'entry_price': position.entry_price,
            'exit_price': exit_price,
            'size': position.size,
            'pnl': pnl,
            'reason': reason,
            'timestamp': pd.Timestamp.now()
        }
        self.trade_history.append(trade_record)
        
        # Remove position
        del self.positions[symbol]
        
        return trade_record
    
    def update_equity(self, current_prices: Dict[str, float]):
        """Update equity based on current market prices"""
        unrealized_pnl = 0
        for symbol, position in self.positions.items():
            current_price = current_prices.get(symbol, position.entry_price)
            
            if position.side == 'BUY':
                unrealized_pnl += (current_price - position.entry_price) * position.size
            else:  # SELL
                unrealized_pnl += (position.entry_price - current_price) * position.size
        
        current_equity = self.cash + unrealized_pnl
        self.equity_history.append(current_equity)
        
        return current_equity
    
    def get_position(self, symbol: str) -> Optional[Position]:
        """Get position for symbol"""
        return self.positions.get(symbol)
    
    def has_position(self, symbol: str) -> bool:
        """Check if we have a position in symbol"""
        return symbol in self.positions
    
    def get_total_equity(self) -> float:
        """Get current total equity"""
        return self.equity_history[-1] if self.equity_history else self.initial_balance