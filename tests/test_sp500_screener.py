"""Тесты для sp500_screener.py — быстрый технический скрининг без обучения модели."""
import pandas as pd
import pytest

import data_fetcher
import sp500_screener
from features import build_features


def test_score_weights_sum_to_one():
    """Сумма весов компонентов скора должна быть 1.0 — иначе скор
    не интерпретируется как взвешенное среднее в ожидаемом диапазоне."""
    assert abs(sum(sp500_screener.SCORE_WEIGHTS.values()) - 1.0) < 1e-9


def test_quick_score_positive_for_uptrend(synthetic_ohlcv):
    raw = synthetic_ohlcv(seed=10, drift=0.003, vol=0.01, n=300)
    feat = build_features(raw)
    score = sp500_screener.compute_quick_score(feat)
    assert score > 0


def test_quick_score_negative_for_downtrend(synthetic_ohlcv):
    raw = synthetic_ohlcv(seed=11, drift=-0.003, vol=0.01, n=300)
    feat = build_features(raw)
    score = sp500_screener.compute_quick_score(feat)
    assert score < 0


def test_shortlist_candidates_picks_top_and_bottom():
    screened = [{"ticker": f"T{i}", "score": 10 - i, "price": 100.0} for i in range(20)]
    shortlist = sp500_screener.shortlist_candidates(screened, top_n=3)
    assert shortlist[:3] == ["T0", "T1", "T2"]
    assert shortlist[-3:] == ["T17", "T18", "T19"]


def test_shortlist_candidates_empty_input():
    assert sp500_screener.shortlist_candidates([], top_n=5) == []


def test_shortlist_candidates_deduplicates_small_lists():
    """Если общий список короче 2*top_n, верх и низ могут пересекаться —
    в результате не должно быть дубликатов тикеров."""
    screened = [{"ticker": "A", "score": 1.0, "price": 1}, {"ticker": "B", "score": 0.5, "price": 1}]
    shortlist = sp500_screener.shortlist_candidates(screened, top_n=5)
    assert len(shortlist) == len(set(shortlist))


def test_screen_universe_ranks_and_skips_broken_tickers(monkeypatch, synthetic_ohlcv):
    bull = synthetic_ohlcv(seed=20, drift=0.004, vol=0.01, n=300)
    bear = synthetic_ohlcv(seed=21, drift=-0.004, vol=0.01, n=300)

    fake_bulk = {
        "BULL": bull,
        "BEAR": bear,
        "EMPTY": pd.DataFrame(),  # должен быть пропущен
    }
    monkeypatch.setattr(data_fetcher, "fetch_history_bulk", lambda tickers, period="1y": fake_bulk)

    calls = []
    results = sp500_screener.screen_universe(
        ["BULL", "BEAR", "EMPTY", "MISSING"],
        progress_callback=lambda i, total, ticker: calls.append((i, total, ticker)),
    )

    assert len(results) == 2  # EMPTY и MISSING отсеяны
    assert results[0]["ticker"] == "BULL"  # самый бычий сверху
    assert results[-1]["ticker"] == "BEAR"
    assert len(calls) >= 1


def test_screen_universe_empty_bulk_data(monkeypatch):
    monkeypatch.setattr(data_fetcher, "fetch_history_bulk", lambda tickers, period="1y": {})
    results = sp500_screener.screen_universe(["ANY"])
    assert results == []
