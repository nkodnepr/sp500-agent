"""Тесты для risk_management.py — ATR, стоп-лосс/тейк-профит, сайзинг позиции."""
import numpy as np

from risk_management import compute_atr, compute_risk_levels, suggest_position_size


def test_compute_atr_returns_positive_values(synthetic_ohlcv):
    raw = synthetic_ohlcv()
    atr = compute_atr(raw)
    valid = atr.dropna()
    assert len(valid) > 0
    assert (valid > 0).all()


def test_risk_levels_for_buy_direction():
    levels = compute_risk_levels(current_price=100.0, atr=2.0, direction=1)
    assert levels is not None
    assert levels["stop_loss"] < 100.0
    assert levels["take_profit"] > 100.0
    assert levels["risk_reward_ratio"] > 0


def test_risk_levels_for_sell_direction():
    levels = compute_risk_levels(current_price=100.0, atr=2.0, direction=-1)
    assert levels is not None
    assert levels["stop_loss"] > 100.0
    assert levels["take_profit"] < 100.0


def test_risk_levels_none_for_hold():
    levels = compute_risk_levels(current_price=100.0, atr=2.0, direction=0)
    assert levels is None


def test_risk_levels_none_when_atr_invalid():
    assert compute_risk_levels(100.0, atr=None, direction=1) is None
    assert compute_risk_levels(100.0, atr=float("nan"), direction=1) is None
    assert compute_risk_levels(100.0, atr=0, direction=1) is None


def test_position_size_respects_risk_budget():
    # Стоп в 2$ от входа, риск 1% от портфеля 10000$ = 100$ максимального убытка
    result = suggest_position_size(current_price=100.0, stop_loss=98.0,
                                    portfolio_value=10000.0, risk_pct=0.01)
    # 100$ риска / 2$ риска на акцию = 50 акций
    assert abs(result["shares"] - 50.0) < 0.01
    assert result["pct_of_portfolio"] <= 1.0


def test_position_size_zero_when_no_stop_distance():
    result = suggest_position_size(current_price=100.0, stop_loss=100.0)
    assert result["shares"] == 0
