"""
Общие фикстуры для тестов. Все тесты работают на синтетических данных —
без реальных сетевых запросов к yfinance, чтобы CI на GitHub Actions был
быстрым, детерминированным и не зависел от доступности внешних API.
"""
import os
import shutil
import sys

import numpy as np
import pandas as pd
import pytest

# Даёт тестам доступ к модулям проекта из корня репозитория
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture
def synthetic_ohlcv():
    """Фабрика синтетических дневных OHLCV-данных (геометрическое случайное
    блуждание) — используется вместо реальных котировок во всех тестах."""
    def _make(seed=1, n=800, start="2021-01-01", drift=0.0005, vol=0.015):
        rng = np.random.default_rng(seed)
        dates = pd.bdate_range(start, periods=n, tz="America/New_York")
        price = 100 * np.cumprod(1 + rng.normal(drift, vol, n))
        return pd.DataFrame({
            "Open": price * 0.99,
            "High": price * 1.015,
            "Low": price * 0.985,
            "Close": price,
            "Volume": rng.integers(1_000_000, 5_000_000, n),
        }, index=dates)
    return _make


@pytest.fixture(autouse=True)
def clean_models_cache():
    """Гарантирует, что тесты кэша моделей не оставляют мусор и не влияют
    друг на друга — кэш очищается до и после каждого теста."""
    for path in ("models_cache", "test_models_cache"):
        if os.path.exists(path):
            shutil.rmtree(path)
    yield
    for path in ("models_cache", "test_models_cache"):
        if os.path.exists(path):
            shutil.rmtree(path)
