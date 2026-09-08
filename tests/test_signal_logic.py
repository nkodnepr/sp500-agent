"""Тесты для signal_logic.py — правила BUY/SELL/HOLD и модификаторы контекста."""
from signal_logic import generate_signal


def _forecast(votes: list[int], confidences: list[float] = None, expected_returns: list[float] = None):
    """Строит тестовый forecast-словарь с заданными направлениями по 4 горизонтам."""
    horizons = ["1w", "2w", "1m", "3m"]
    confidences = confidences or [0.7] * 4
    expected_returns = expected_returns or [0.05 if v == 1 else (-0.05 if v == -1 else 0.0) for v in votes]
    return {"horizons": {
        h: {"direction": v, "confidence": c, "expected_return": r}
        for h, v, c, r in zip(horizons, votes, confidences, expected_returns)
    }}


def test_buy_signal_on_strong_consensus():
    forecast = _forecast([1, 1, 1, 0])
    signal = generate_signal(forecast)
    assert signal["action"] == "BUY"


def test_sell_signal_on_strong_consensus():
    forecast = _forecast([-1, -1, -1, 0])
    signal = generate_signal(forecast)
    assert signal["action"] == "SELL"


def test_hold_on_conflicting_signals():
    forecast = _forecast([1, -1, 1, -1])
    signal = generate_signal(forecast)
    assert signal["action"] == "HOLD"


def test_hold_on_low_confidence():
    forecast = _forecast([1, 1, 1, 0], confidences=[0.3, 0.3, 0.3, 0.3])
    signal = generate_signal(forecast)
    assert signal["action"] == "HOLD"


def test_hold_when_model_error_present():
    forecast = {"horizons": {
        "1w": {"error": "недостаточно данных"},
        "2w": {"direction": 1, "confidence": 0.8, "expected_return": 0.05},
        "1m": {"direction": 1, "confidence": 0.8, "expected_return": 0.05},
        "3m": {"direction": 1, "confidence": 0.8, "expected_return": 0.05},
    }}
    signal = generate_signal(forecast)
    assert signal["action"] == "HOLD"


def test_negative_sentiment_downgrades_buy_to_hold():
    forecast = _forecast([1, 1, 1, 0])
    negative = {"score": -0.5, "label": "Негативный", "num_articles": 5}
    signal = generate_signal(forecast, sentiment=negative)
    assert signal["action"] == "HOLD"
    assert "новостной" in signal["reason"].lower()


def test_weak_sentiment_does_not_override_buy():
    forecast = _forecast([1, 1, 1, 0])
    weak = {"score": -0.1, "label": "Нейтральный", "num_articles": 3}
    signal = generate_signal(forecast, sentiment=weak)
    assert signal["action"] == "BUY"


def test_bear_market_requires_unanimous_votes_for_buy():
    forecast = _forecast([1, 1, 1, 0])  # 3/4 — обычно достаточно для BUY
    bear = {"regime": "bear", "label": "Медвежий (падающий рынок)"}
    signal = generate_signal(forecast, market=bear)
    assert signal["action"] == "HOLD"


def test_bear_market_allows_buy_on_unanimous_votes():
    forecast = _forecast([1, 1, 1, 1])  # 4/4 — единогласно
    bear = {"regime": "bear", "label": "Медвежий (падающий рынок)"}
    signal = generate_signal(forecast, market=bear)
    assert signal["action"] == "BUY"


def test_earnings_warning_does_not_block_signal():
    forecast = _forecast([1, 1, 1, 0])
    earnings = {"next_earnings_date": "2026-09-01", "within": {"1m": True}, "days_until": 5}
    signal = generate_signal(forecast, earnings=earnings)
    assert signal["action"] == "BUY"
    assert signal["earnings_warning"] is not None


def test_no_earnings_warning_when_far_away():
    forecast = _forecast([1, 1, 1, 0])
    earnings = {"next_earnings_date": "2027-01-01", "within": {"1m": False}, "days_until": 130}
    signal = generate_signal(forecast, earnings=earnings)
    assert signal["earnings_warning"] is None
