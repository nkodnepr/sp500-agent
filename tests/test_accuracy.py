"""Тесты для accuracy.py — сверка прошлых сигналов с реальными ценами."""
from datetime import timedelta

import numpy as np
import pandas as pd
import pytest

from timeutils import utc_now
import accuracy
import data_fetcher


class _FakeRow(dict):
    """Имитирует sqlite3.Row (доступ по [] с именем колонки)."""
    def __getitem__(self, key):
        return dict.get(self, key)


@pytest.fixture
def rising_price_history(monkeypatch):
    """Синтетическая история: устойчивый рост со 100 до 150 за ~год,
    оканчивающаяся сегодняшним днём."""
    dates = pd.bdate_range(end=pd.Timestamp.now(tz="America/New_York").normalize(),
                            periods=300, tz="America/New_York")
    # len(dates), а не константа 300: pd.bdate_range с таймзоной иногда
    # возвращает на одну метку меньше на границе перехода летнего/зимнего
    # времени — привязка к len(dates) делает тест устойчивым к дате запуска
    price = np.linspace(100, 150, len(dates))
    hist = pd.DataFrame({"Close": price}, index=dates)
    monkeypatch.setattr(data_fetcher, "fetch_history", lambda ticker, years=2: hist)
    return hist


def test_correct_buy_signal_on_rising_price(rising_price_history):
    price_40d_ago = float(rising_price_history["Close"].iloc[-40])
    row = _FakeRow({
        "ticker": "FAKE", "created_at": (utc_now() - timedelta(days=40)).isoformat(),
        "price_at_signal": price_40d_ago, "action": "BUY",
        "forecast_1w": 0.03, "forecast_2w": 0.04, "forecast_1m": 0.05, "forecast_3m": None,
    })
    stats = accuracy.evaluate_accuracy([row])
    assert stats["horizon_stats"]["1w"]["total"] == 1
    assert stats["horizon_stats"]["1w"]["correct"] == 1  # предсказан рост, цена реально росла
    assert stats["action_stats"]["BUY"]["total"] == 1
    assert stats["action_stats"]["BUY"]["positive_outcome"] == 1


def test_incorrect_sell_signal_on_rising_price(rising_price_history):
    price_40d_ago = float(rising_price_history["Close"].iloc[-40])
    row = _FakeRow({
        "ticker": "FAKE", "created_at": (utc_now() - timedelta(days=40)).isoformat(),
        "price_at_signal": price_40d_ago, "action": "SELL",
        "forecast_1w": -0.03, "forecast_2w": None, "forecast_1m": -0.04, "forecast_3m": None,
    })
    stats = accuracy.evaluate_accuracy([row])
    assert stats["horizon_stats"]["1w"]["correct"] == 0  # предсказано падение, а цена росла
    assert stats["action_stats"]["SELL"]["positive_outcome"] == 0


def test_recent_signal_not_yet_evaluated(rising_price_history):
    """Сигнал 3 дня назад: горизонт 1 неделя ещё не наступил — должен
    быть честно пропущен, а не додуман."""
    price_recent = float(rising_price_history["Close"].iloc[-3])
    row = _FakeRow({
        "ticker": "FAKE", "created_at": (utc_now() - timedelta(days=3)).isoformat(),
        "price_at_signal": price_recent, "action": "BUY",
        "forecast_1w": 0.02, "forecast_2w": None, "forecast_1m": None, "forecast_3m": None,
    })
    stats = accuracy.evaluate_accuracy([row])
    assert stats["horizon_stats"]["1w"]["total"] == 0


def test_empty_history_gives_no_data_message():
    stats = accuracy.evaluate_accuracy([])
    report = accuracy.format_accuracy_report(stats)
    assert "нет" in report.lower() or "недостаточно" in report.lower()
