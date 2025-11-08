"""Utilities for working with market data snapshots."""

__all__ = ["build_daily_snapshots", "MarketEnvironment"]


def __getattr__(name):
    if name == "build_daily_snapshots":
        from .snapshot_builder import build_daily_snapshots as builder

        return builder
    if name == "MarketEnvironment":
        from .environment import MarketEnvironment as environment

        return environment
    raise AttributeError(f"module 'market_data' has no attribute {name!r}")
