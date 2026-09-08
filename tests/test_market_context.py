"""
Тесты рыночного контекста (SPY).

Ключевое здесь — что кэш истории SPY НЕ живёт вечно. Бот работает на
сервере неделями без перезапуска, и без срока жизни кэша режим рынка и
относительная сила навсегда считались бы по котировкам на дату старта
процесса — молча, без единой ошибки в логах.
"""
from datetime import timedelta

import pandas as pd
import pytest

import market_context
from timeutils import utc_now


@pytest.fixture
def fake_spy(monkeypatch):
    """Подменяет yfinance: считает обращения к сети и отдаёт разные данные."""
    state = {"calls": 0, "fail": False}
    index = pd.bdate_range("2024-01-01", periods=300, tz="America/New_York")

    class FakeTicker:
        def __init__(self, symbol):
            self.symbol = symbol

        def history(self, **kwargs):
            state["calls"] += 1
            if state["fail"]:
                return pd.DataFrame()
            # цена растёт с каждым обращением — так видно, обновились данные или нет
            base = 100.0 + state["calls"]
            return pd.DataFrame({"Close": [base] * 300}, index=index)

    monkeypatch.setattr(market_context.yf, "Ticker", FakeTicker)
    market_context.clear_market_cache()
    yield state
    market_context.clear_market_cache()


def _expire_cache(monkeypatch):
    """Сдвигает время получения кэша за пределы TTL."""
    monkeypatch.setattr(
        market_context, "_spy_cache_at",
        utc_now() - market_context.MARKET_CACHE_TTL - timedelta(minutes=1),
    )


def test_second_call_within_ttl_uses_cache(fake_spy):
    market_context.fetch_market_history()
    market_context.fetch_market_history()
    assert fake_spy["calls"] == 1


def test_cache_is_refreshed_after_ttl(fake_spy, monkeypatch):
    first = market_context.fetch_market_history()
    _expire_cache(monkeypatch)
    second = market_context.fetch_market_history()

    assert fake_spy["calls"] == 2
    assert float(second["Close"].iloc[-1]) != float(first["Close"].iloc[-1])


def test_stale_cache_is_used_when_refresh_fails(fake_spy, monkeypatch):
    """Если сеть отвалилась, устаревшие данные лучше, чем режим «Н/д»."""
    first = market_context.fetch_market_history()
    _expire_cache(monkeypatch)
    fake_spy["fail"] = True

    result = market_context.fetch_market_history()
    assert float(result["Close"].iloc[-1]) == float(first["Close"].iloc[-1])


def test_error_raised_when_no_cache_at_all(fake_spy):
    fake_spy["fail"] = True
    with pytest.raises(ValueError):
        market_context.fetch_market_history()


def test_clear_market_cache_forces_refetch(fake_spy):
    market_context.fetch_market_history()
    market_context.clear_market_cache()
    market_context.fetch_market_history()
    assert fake_spy["calls"] == 2


def test_market_regime_reports_unknown_without_data(fake_spy):
    """get_market_regime не должен падать, если данных нет вовсе."""
    fake_spy["fail"] = True
    regime = market_context.get_market_regime()
    assert regime["regime"] == "unknown"
