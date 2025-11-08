"""Tests for the :mod:`market_data.environment` module."""

from datetime import date

import pytest

from market_data.environment import MarketEnvironment
from trade_logger import TradeLogger


@pytest.fixture
def trade_logger(tmp_path):
    """Provide a TradeLogger instance scoped to a temporary directory."""

    return TradeLogger(log_dir=str(tmp_path))


def test_iteration_computes_future_returns(trade_logger):
    """The environment should iterate snapshots and compute future returns."""

    snapshots = {
        date(2024, 1, 1): {"price": {"close": 100.0}},
        date(2024, 1, 2): {"price": {"close": 110.0}},
        date(2024, 1, 3): {"price": {"close": 121.0}},
    }

    env = MarketEnvironment(snapshots=snapshots, trade_logger=trade_logger)
    env.reset()

    first_date, first_snapshot, done = env.step()
    assert first_date == date(2024, 1, 1)
    assert first_snapshot["future_return"] == pytest.approx(0.10)
    assert not done

    second_date, second_snapshot, done = env.step()
    assert second_date == date(2024, 1, 2)
    assert second_snapshot["future_return"] == pytest.approx(0.10)
    assert not done

    third_date, third_snapshot, done = env.step()
    assert third_date == date(2024, 1, 3)
    assert third_snapshot["future_return"] is None
    assert done


def test_missing_optional_fields_are_normalized(trade_logger):
    """Missing optional fields should be replaced with sensible defaults."""

    snapshots = {
        date(2024, 2, 1): {"price": {"close": 50.0}},
        date(2024, 2, 2): {"price": {"close": 55.0}},
    }

    env = MarketEnvironment(snapshots=snapshots, trade_logger=trade_logger)
    env.reset()

    current_date, snapshot, done = env.step()
    assert current_date == date(2024, 2, 1)
    assert snapshot["news"] == {"items": []}
    assert snapshot["filing_q"] == {}
    assert snapshot["filing_k"] == {}
    assert not done


def test_step_signals_completion(trade_logger):
    """After the final snapshot the environment should signal completion."""

    snapshots = {
        date(2024, 3, 10): {"price": {"close": 200.0}},
        date(2024, 3, 11): {"price": {"close": 180.0}},
    }

    env = MarketEnvironment(snapshots=snapshots, trade_logger=trade_logger)
    env.reset()

    _, _, done = env.step()
    assert not done

    _, _, done = env.step()
    assert done

    extra_date, extra_snapshot, extra_done = env.step()
    assert extra_date is None
    assert extra_snapshot is None
    assert extra_done
