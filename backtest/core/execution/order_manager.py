# core/execution/order_manager.py
from typing import Dict, List, Optional
from dataclasses import dataclass
import pandas as pd

@dataclass
class Order:
    symbol: str
    side: str  # BUY/SELL
    order_type: str  # MARKET/LIMIT/STOP
    size: float
    price: Optional[float] = None
    sl_price: Optional[float] = None
    tp_price: Optional[float] = None
    status: str = "PENDING"  # PENDING, FILLED, CANCELLED, REJECTED

class OrderManager:
    """
    Manages order execution and order lifecycle
    """
    
    def __init__(self, slippage_simulator = None):
        self.orders: List[Order] = []
        self.slippage_simulator = slippage_simulator
        self.filled_orders = []
    
    def create_order(self, 
                    symbol: str,
                    side: str,
                    size: float,
                    order_type: str = "MARKET",
                    price: float = None,
                    sl: float = None,
                    tp: float = None) -> Order:
        """Create a new order"""
        order = Order(
            symbol=symbol,
            side=side,
            order_type=order_type,
            size=size,
            price=price,
            sl_price=sl,
            tp_price=tp
        )
        
        self.orders.append(order)
        return order
    
    def execute_order(self, order: Order, current_price: float) -> Dict:
        """Execute an order with realistic fills"""
        if order.status != "PENDING":
            return {'success': False, 'reason': 'Order already processed'}
        
        # Apply slippage if simulator available
        if self.slippage_simulator:
            executed_price = self.slippage_simulator.apply_slippage(
                order, current_price
            )
        else:
            executed_price = current_price
        
        # Simulate order fill
        order.status = "FILLED"
        order.price = executed_price  # Update with actual fill price
        
        fill_result = {
            'success': True,
            'order_id': id(order),
            'symbol': order.symbol,
            'side': order.side,
            'size': order.size,
            'requested_price': current_price,
            'executed_price': executed_price,
            'slippage': executed_price - current_price,
            'timestamp': pd.Timestamp.now()
        }
        
        self.filled_orders.append(fill_result)
        
        # Remove from pending orders
        self.orders = [o for o in self.orders if o.status == "PENDING"]
        
        return fill_result
    
    def cancel_order(self, order: Order) -> bool:
        """Cancel a pending order"""
        if order.status == "PENDING":
            order.status = "CANCELLED"
            self.orders.remove(order)
            return True
        return False
    
    def get_pending_orders(self) -> List[Order]:
        """Get all pending orders"""
        return [order for order in self.orders if order.status == "PENDING"]
    
    def has_pending_orders(self) -> bool:
        """Check if there are any pending orders"""
        return any(order.status == "PENDING" for order in self.orders)

class TradeExecutor:
    """
    High-level trade execution coordinating order manager and risk management
    """
    
    def __init__(self, order_manager: OrderManager, risk_manager: RiskManager):
        self.order_manager = order_manager
        self.risk_manager = risk_manager
    
    def execute_trade_signal(self,
                           portfolio: PositionTracker,
                           signal: str,
                           current_data: pd.Series,
                           symbol: str) -> Optional[Dict]:
        """Execute a complete trade based on signal"""
        if signal not in ['BUY', 'SELL']:
            return None
        
        current_price = current_data['close']
        
        # Calculate position size with risk management
        stops = self.risk_manager.calculate_dynamic_stops(
            # You'd pass relevant market data here
            pd.DataFrame([current_data]),  # Simplified
            current_price,
            signal
        )
        
        position_size = self.risk_manager.calculate_position_size(
            portfolio, current_price, stops['sl'], symbol
        )
        
        # Validate the trade
        validation = self.risk_manager.validate_trade(
            portfolio, symbol, position_size, current_price
        )
        
        if not validation['is_valid']:
            print(f"Trade rejected: {', '.join(validation['reasons'])}")
            return None
        
        # Use adjusted size if provided
        if validation['adjusted_size'] != position_size:
            position_size = validation['adjusted_size']
            print(f"Position size adjusted to {position_size:.2f}")
        
        # Create and execute order
        order = self.order_manager.create_order(
            symbol=symbol,
            side=signal,
            size=position_size,
            sl=stops['sl'],
            tp=stops['tp']
        )
        
        fill_result = self.order_manager.execute_order(order, current_price)
        
        if fill_result['success']:
            # Update portfolio
            portfolio.open_position(
                symbol=symbol,
                side=signal,
                price=fill_result['executed_price'],
                size=position_size,
                sl=stops['sl'],
                tp=stops['tp']
            )
        
        return fill_result