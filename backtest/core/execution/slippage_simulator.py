# core/execution/slippage_simulator.py
import numpy as np
from typing import Dict
from .order_manager import Order

class SlippageSimulator:
    """
    Realistic slippage and market impact simulation
    Enhanced version of your DynamicExecution class
    """
    
    def __init__(self,
                 base_slippage: float = 0.00005,  # 0.5 pips base slippage
                 volatility_factor: float = 2.0,
                 latency_ms: int = 100,
                 spread_ratio: float = 0.0001):   # 1 pip typical spread
        
        self.base_slippage = base_slippage
        self.volatility_factor = volatility_factor
        self.latency_ms = latency_ms
        self.spread_ratio = spread_ratio
    
    def apply_slippage(self, order: Order, current_price: float) -> float:
        """Apply realistic slippage to order execution"""
        # Base slippage
        slippage = self.base_slippage
        
        # Size-based slippage (market impact)
        size_impact = min(order.size / 100000, 0.001)  # Cap at 1 pip
        slippage += size_impact
        
        # Volatility-based slippage (simplified)
        # In real implementation, you'd use recent volatility
        volatility_component = np.random.normal(0, self.volatility_factor * 0.0001)
        slippage += abs(volatility_component)
        
        # Spread cost
        spread_cost = self.spread_ratio / 2  # Pay half spread
        
        # Determine final price based on order side
        if order.side == 'BUY':
            executed_price = current_price + slippage + spread_cost
        else:  # SELL
            executed_price = current_price - slippage - spread_cost
        
        # Ensure positive price
        return max(executed_price, 0.00001)
    
    def simulate_latency_fill(self, 
                            order: Order, 
                            current_prices: Dict[str, float]) -> Dict:
        """
        Simulate latency in order filling
        Returns whether order would fill in real market conditions
        """
        symbol = order.symbol
        current_price = current_prices.get(symbol, 0)
        
        # Simulate price movement during latency period
        latency_move = np.random.normal(0, 0.0001)  # Small random move
        
        potential_fill_price = current_price + latency_move
        
        # Check if limit orders would fill
        if order.order_type == "LIMIT":
            if order.side == "BUY" and potential_fill_price <= order.price:
                can_fill = True
            elif order.side == "SELL" and potential_fill_price >= order.price:
                can_fill = True
            else:
                can_fill = False
        else:  # MARKET orders always fill
            can_fill = True
        
        return {
            'can_fill': can_fill,
            'potential_price': potential_fill_price,
            'latency_move': latency_move
        }