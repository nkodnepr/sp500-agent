"""Тесты для desktop_engine.py — бизнес-логика настольного приложения."""
import os

import pandas as pd
import pytest

import config
import data_fetcher
import db
import desktop_engine as engine
import earnings
import fundamentals
import market_context
import sp500_screener as sp500_screener_module
import sp500_universe as sp500_universe_module


@pytest.fixture
def desktop_env(tmp_path, monkeypatch, synthetic_ohlcv):
    """
    Полное окружение для тестов desktop_engine: временная БД, синтетические
    котировки/фундаментал/рынок вместо реальных сетевых запросов, watchlist
    с одним тестовым тикером.
    """
    db_path = str(tmp_path / "test_watchlist.db")
    monkeypatch.setattr(config, "DB_PATH", db_path)
    db.init_db()

    raw = synthetic_ohlcv(seed=42, drift=0.0007, vol=0.013)
    monkeypatch.setattr(data_fetcher, "fetch_history", lambda ticker, years=5: raw)
    monkeypatch.setattr(fundamentals, "fetch_fundamentals_timeseries", lambda ticker: pd.DataFrame())
    monkeypatch.setattr(fundamentals, "latest_fundamentals_snapshot", lambda ticker: None)
    monkeypatch.setattr(
        earnings, "check_earnings_within_horizons",
        lambda ticker, horizons: {"next_earnings_date": None, "within": {h: False for h in horizons}},
    )

    spy = synthetic_ohlcv(seed=7, drift=0.0003, vol=0.009).rename(columns={"Close": "Close"})
    market_context._spy_cache = spy

    db.add_ticker(engine.LOCAL_USER_ID, "DESKTEST")
    yield db_path


def test_build_full_analysis_returns_expected_keys(desktop_env):
    analysis = engine.build_full_analysis("DESKTEST")
    assert set(analysis.keys()) == {"forecast", "signal", "fundamentals", "position_size"}
    assert analysis["forecast"]["ticker"] == "DESKTEST"
    assert analysis["signal"]["action"] in ("BUY", "SELL", "HOLD")


def test_render_analysis_segments_structure(desktop_env):
    analysis = engine.build_full_analysis("DESKTEST")
    segments = engine.render_analysis_segments(analysis)

    assert len(segments) > 5
    assert all(isinstance(s, tuple) and len(s) == 2 for s in segments)
    assert all(isinstance(text, str) and isinstance(tag, str) for text, tag in segments)

    # Первый сегмент — заголовок с тикером
    assert segments[0][1] == "header"
    assert "DESKTEST" in segments[0][0]

    # Где-то должна быть строка с рекомендацией
    all_text = "".join(t for t, _ in segments)
    assert "РЕКОМЕНДАЦИЯ" in all_text


def test_render_analysis_segments_tags_are_known(desktop_env):
    """Все используемые теги должны быть из согласованного набора — иначе
    GUI-слой не сможет их раскрасить (нет соответствующего tag_configure)."""
    known_tags = {"header", "subheader", "normal", "buy", "sell", "hold", "warning", "muted"}
    analysis = engine.build_full_analysis("DESKTEST")
    segments = engine.render_analysis_segments(analysis)
    used_tags = {tag for _, tag in segments}
    assert used_tags.issubset(known_tags)


def test_scan_watchlist_returns_one_result_per_ticker(desktop_env):
    results = engine.scan_watchlist()
    assert len(results) == 1
    assert results[0]["ticker"] == "DESKTEST"
    assert "action" in results[0]


def test_scan_watchlist_calls_progress_callback(desktop_env):
    calls = []
    engine.scan_watchlist(progress_callback=lambda i, total, ticker: calls.append((i, total, ticker)))
    assert calls == [(0, 1, "DESKTEST")]


def test_scan_watchlist_logs_signal_when_actionable(desktop_env, monkeypatch):
    """Если сигнал BUY/SELL — он должен попасть в историю сигналов (для accuracy)."""
    import signal_logic
    monkeypatch.setattr(
        signal_logic, "generate_signal",
        lambda *a, **k: {"action": "BUY", "reason": "тест", "confidence": 0.9,
                          "sentiment": None, "market": None, "earnings_warning": None},
    )

    engine.scan_watchlist()
    history = db.get_all_signals(engine.LOCAL_USER_ID)
    assert len(history) == 1
    assert history[0]["action"] == "BUY"


def test_retrain_all_reports_success(desktop_env):
    results = engine.retrain_all()
    assert len(results) == 1
    ticker, success, message = results[0]
    assert ticker == "DESKTEST"
    assert success is True
    assert message == ""


def test_retrain_all_calls_progress_callback(desktop_env):
    calls = []
    engine.retrain_all(progress_callback=lambda i, total, ticker: calls.append((i, total, ticker)))
    assert calls == [(0, 1, "DESKTEST")]


def test_empty_watchlist_returns_empty_results(tmp_path, monkeypatch):
    db_path = str(tmp_path / "empty.db")
    monkeypatch.setattr(config, "DB_PATH", db_path)
    db.init_db()
    assert engine.scan_watchlist() == []
    assert engine.retrain_all() == []


def test_scan_sp500_two_stage_flow(desktop_env, monkeypatch, synthetic_ohlcv):
    """Полный сквозной прогон scan_sp500: подмена списка тикеров индекса +
    подмена bulk-фетча для быстрого этапа; глубокий анализ переиспользует
    ту же синтетическую историю, что уже настроена в desktop_env."""
    bull = synthetic_ohlcv(seed=50, drift=0.004, vol=0.01, n=800)
    bear = synthetic_ohlcv(seed=51, drift=-0.004, vol=0.01, n=800)

    monkeypatch.setattr(
        sp500_universe_module, "fetch_sp500_tickers",
        lambda: (["SPBULL", "SPBEAR"], False),
    )
    monkeypatch.setattr(
        data_fetcher, "fetch_history_bulk",
        lambda tickers, period="1y": {"SPBULL": bull, "SPBEAR": bear},
    )

    fake_histories = {"SPBULL": bull, "SPBEAR": bear}
    monkeypatch.setattr(data_fetcher, "fetch_history", lambda ticker, years=5: fake_histories[ticker])

    result = engine.scan_sp500(top_n=1, deep_dive=True)

    assert result["universe_size"] == 2
    assert result["screened_size"] == 2
    assert result["used_fallback_tickers"] is False
    assert len(result["screened"]) == 2
    assert result["screened"][0]["ticker"] == "SPBULL"  # самый бычий сверху
    assert result["shortlist_analysis"] is not None
    assert len(result["shortlist_analysis"]) == 2  # top_n=1 бычий + 1 медвежий
    assert {r["ticker"] for r in result["shortlist_analysis"]} == {"SPBULL", "SPBEAR"}


def test_scan_sp500_without_deep_dive(desktop_env, monkeypatch, synthetic_ohlcv):
    """deep_dive=False — только быстрый этап, без обучения моделей."""
    bull = synthetic_ohlcv(seed=52, drift=0.003, vol=0.01, n=300)
    monkeypatch.setattr(sp500_universe_module, "fetch_sp500_tickers", lambda: (["SPONLY"], False))
    monkeypatch.setattr(data_fetcher, "fetch_history_bulk", lambda tickers, period="1y": {"SPONLY": bull})

    result = engine.scan_sp500(top_n=5, deep_dive=False)

    assert result["shortlist_analysis"] is None
    assert len(result["screened"]) == 1


def test_scan_sp500_surfaces_fallback_flag(desktop_env, monkeypatch):
    """Если получить актуальный список не удалось — флаг должен дойти до
    результата, чтобы GUI мог честно предупредить пользователя."""
    monkeypatch.setattr(sp500_universe_module, "fetch_sp500_tickers", lambda: (["X"], True))
    monkeypatch.setattr(data_fetcher, "fetch_history_bulk", lambda tickers, period="1y": {})

    result = engine.scan_sp500(top_n=5, deep_dive=False)
    assert result["used_fallback_tickers"] is True
    assert result["screened"] == []
