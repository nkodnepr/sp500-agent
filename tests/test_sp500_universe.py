"""Тесты для sp500_universe.py — получение списка компаний S&P 500."""
import pandas as pd

import sp500_universe


def test_fallback_used_when_source_unavailable(monkeypatch):
    """Если реальный источник (Wikipedia) недоступен — используется
    резервный список, и это явно помечается вторым элементом кортежа."""
    def broken_read_html(url):
        raise ConnectionError("сеть недоступна")

    monkeypatch.setattr(pd, "read_html", broken_read_html)

    tickers, used_fallback = sp500_universe.fetch_sp500_tickers()
    assert used_fallback is True
    assert tickers == sp500_universe.FALLBACK_TICKERS
    assert "AAPL" in tickers


def test_ticker_dot_to_dash_conversion(monkeypatch):
    """yfinance использует дефис вместо точки в тикерах классов акций
    (BRK.B на Wikipedia -> BRK-B для yfinance)."""
    fake_table = pd.DataFrame({"Symbol": ["AAPL", "BRK.B", "BF.B"] + [f"T{i}" for i in range(400)]})
    monkeypatch.setattr(pd, "read_html", lambda url: [fake_table])

    tickers, used_fallback = sp500_universe.fetch_sp500_tickers()
    assert used_fallback is False
    assert "BRK-B" in tickers
    assert "BF-B" in tickers
    assert "BRK.B" not in tickers


def test_suspiciously_small_table_triggers_fallback(monkeypatch):
    """Если таблица содержит подозрительно мало строк (формат страницы
    мог измениться) — не доверяем ей молча, переключаемся на резерв."""
    fake_table = pd.DataFrame({"Symbol": ["AAPL", "MSFT"]})  # всего 2 вместо ~500
    monkeypatch.setattr(pd, "read_html", lambda url: [fake_table])

    tickers, used_fallback = sp500_universe.fetch_sp500_tickers()
    assert used_fallback is True


def test_fallback_list_has_no_duplicates():
    assert len(sp500_universe.FALLBACK_TICKERS) == len(set(sp500_universe.FALLBACK_TICKERS))
