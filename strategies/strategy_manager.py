"""
Strategy Manager

Manages multiple trading strategies and combines their signals.
"""

from typing import List, Dict, Any
from collections import Counter
from .base_strategy import BaseStrategy


class StrategyManager:
    """
    Manages multiple trading strategies and combines their signals.
    
    Supports multiple combination methods:
    - unanimous: All strategies must agree
    - majority: Majority vote wins
    - weighted: Weighted voting based on strategy weights
    - any: Any strategy signal triggers action
    """
    
    def __init__(self, strategies: List[BaseStrategy] = None, method: str = "majority"):
        """
        Initialize Strategy Manager.
        
        Args:
            strategies: List of strategy instances
            method: Combination method ("unanimous", "majority", "weighted", "any")
        """
        self.strategies = strategies or []
        self.method = method
        self.signal_history = []
    
    def add_strategy(self, strategy: BaseStrategy):
        """
        Add a strategy to the manager.
        
        Args:
            strategy: Strategy instance to add
        """
        self.strategies.append(strategy)
        print(f"[StrategyManager] Added strategy: {strategy.name}")
    
    def remove_strategy(self, strategy_name: str) -> bool:
        """
        Remove a strategy by name.
        
        Args:
            strategy_name: Name of strategy to remove
            
        Returns:
            bool: True if removed, False if not found
        """
        for i, strategy in enumerate(self.strategies):
            if strategy.name == strategy_name:
                self.strategies.pop(i)
                print(f"[StrategyManager] Removed strategy: {strategy_name}")
                return True
        
        print(f"[StrategyManager] Strategy not found: {strategy_name}")
        return False
    
    def set_method(self, method: str):
        """
        Set the signal combination method.
        
        Args:
            method: Combination method ("unanimous", "majority", "weighted", "any")
        """
        valid_methods = ["unanimous", "majority", "weighted", "any"]
        
        if method not in valid_methods:
            print(f"[StrategyManager] Invalid method: {method}. Using 'majority'")
            self.method = "majority"
        else:
            self.method = method
            print(f"[StrategyManager] Combination method set to: {method}")
    
    def get_individual_signals(self, symbol: str) -> Dict[str, str]:
        """
        Get signals from all enabled strategies.
        
        Args:
            symbol: Trading symbol
            
        Returns:
            dict: Strategy name -> signal mapping
        """
        signals = {}
        
        for strategy in self.strategies:
            if strategy.enabled:
                signal = strategy.generate_signal(symbol)
                signals[strategy.name] = signal
        
        return signals
    
    def combine_signals_unanimous(self, signals: Dict[str, str]) -> str:
        """
        Unanimous: All strategies must agree.
        
        Args:
            signals: Strategy signals dictionary
            
        Returns:
            str: Combined signal
        """
        if not signals:
            return "NONE"
        
        # Remove NONE signals for voting
        active_signals = [s for s in signals.values() if s != "NONE"]
        
        if not active_signals:
            return "NONE"
        
        # All must be the same
        if len(set(active_signals)) == 1:
            return active_signals[0]
        
        return "NONE"
    
    def combine_signals_majority(self, signals: Dict[str, str]) -> str:
        """
        Majority: Most common signal wins.
        
        Args:
            signals: Strategy signals dictionary
            
        Returns:
            str: Combined signal
        """
        if not signals:
            return "NONE"
        
        # Count signals
        counter = Counter(signals.values())
        
        # Remove NONE from voting
        if "NONE" in counter:
            del counter["NONE"]
        
        if not counter:
            return "NONE"
        
        # Get most common signal
        most_common = counter.most_common(1)[0]
        signal, count = most_common
        
        # Need more than 50% for majority
        total_active = sum(counter.values())
        if count > total_active / 2:
            return signal
        
        return "NONE"
    
    def combine_signals_weighted(self, signals: Dict[str, str]) -> str:
        """
        Weighted: Signals weighted by strategy weights.
        
        Args:
            signals: Strategy signals dictionary
            
        Returns:
            str: Combined signal
        """
        if not signals:
            return "NONE"
        
        # Calculate weighted votes
        buy_weight = 0.0
        sell_weight = 0.0
        
        for strategy in self.strategies:
            if strategy.name in signals and strategy.enabled:
                signal = signals[strategy.name]
                
                if signal == "BUY":
                    buy_weight += strategy.weight
                elif signal == "SELL":
                    sell_weight += strategy.weight
        
        # Determine winner
        if buy_weight > sell_weight and buy_weight > 0:
            return "BUY"
        elif sell_weight > buy_weight and sell_weight > 0:
            return "SELL"
        
        return "NONE"
    
    def combine_signals_any(self, signals: Dict[str, str]) -> str:
        """
        Any: Any strategy signal triggers action (most aggressive).
        
        Args:
            signals: Strategy signals dictionary
            
        Returns:
            str: Combined signal
        """
        if not signals:
            return "NONE"
        
        # Count BUY and SELL signals
        buy_count = sum(1 for s in signals.values() if s == "BUY")
        sell_count = sum(1 for s in signals.values() if s == "SELL")
        
        # Prioritize BUY if more BUY signals
        if buy_count > sell_count:
            return "BUY"
        elif sell_count > buy_count:
            return "SELL"
        elif buy_count > 0:  # Equal, prefer BUY
            return "BUY"
        
        return "NONE"
    
    def generate_combined_signal(self, symbol: str) -> str:
        """
        Generate combined signal from all strategies.
        
        Args:
            symbol: Trading symbol
            
        Returns:
            str: Combined signal ("BUY", "SELL", or "NONE")
        """
        if not self.strategies:
            print("[StrategyManager] No strategies configured")
            return "NONE"
        
        # Get individual signals
        signals = self.get_individual_signals(symbol)
        
        if not signals:
            print("[StrategyManager] No enabled strategies")
            return "NONE"
        
        # Combine based on method
        if self.method == "unanimous":
            combined = self.combine_signals_unanimous(signals)
        elif self.method == "weighted":
            combined = self.combine_signals_weighted(signals)
        elif self.method == "any":
            combined = self.combine_signals_any(signals)
        else:  # majority (default)
            combined = self.combine_signals_majority(signals)
        
        # Log results
        print(f"\n[StrategyManager] Individual signals: {signals}")
        print(f"[StrategyManager] Combined signal ({self.method}): {combined}")
        
        # Store in history
        self.signal_history.append({
            "symbol": symbol,
            "individual": signals,
            "combined": combined,
            "method": self.method
        })
        
        return combined
    
    def get_strategy_info(self) -> List[Dict[str, Any]]:
        """
        Get information about all strategies.
        
        Returns:
            list: List of strategy info dictionaries
        """
        return [strategy.get_info() for strategy in self.strategies]
    
    def enable_all(self):
        """Enable all strategies."""
        for strategy in self.strategies:
            strategy.enable()
        print("[StrategyManager] All strategies enabled")
    
    def disable_all(self):
        """Disable all strategies."""
        for strategy in self.strategies:
            strategy.disable()
        print("[StrategyManager] All strategies disabled")
    
    def __str__(self) -> str:
        """String representation."""
        enabled_count = sum(1 for s in self.strategies if s.enabled)
        return f"StrategyManager ({enabled_count}/{len(self.strategies)} enabled, method: {self.method})"
    
    def __repr__(self) -> str:
        """Detailed representation."""
        return f"<StrategyManager: {len(self.strategies)} strategies, method={self.method}>"

