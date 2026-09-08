"""
Тесты истории сигналов — прежде всего дедупликации.

Без неё ежедневный прогон бота (daily_analysis_job) записывал бы один и
тот же держащийся сигнал каждый день, и "честная точность" (accuracy.py)
считалась бы в основном по одной долгоиграющей позиции вместо реальной
выборки решений модели.
"""
import pytest

import config
import db

FORECAST = {"1w": 0.03, "2w": 0.04, "1m": 0.05, "3m": 0.06}


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    """Изолированная БД на каждый тест (db.py читает config.DB_PATH на каждый вызов)."""
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "test_watchlist.db"))
    db.init_db()


def _age_all_signals(days: int):
    """Искусственно состаривает все записи истории на days дней назад."""
    with db.get_conn() as conn:
        conn.execute("UPDATE signals_history SET created_at = datetime('now', ?)", (f"-{days} days",))


def test_first_signal_is_logged(temp_db):
    assert db.log_signal(1, "AAPL", "BUY", 100.0, FORECAST, 0.8) is True
    assert len(db.get_all_signals(1)) == 1


def test_repeated_signal_within_window_is_skipped(temp_db):
    db.log_signal(1, "AAPL", "BUY", 100.0, FORECAST, 0.8)
    assert db.log_signal(1, "AAPL", "BUY", 101.0, FORECAST, 0.85) is False
    assert len(db.get_all_signals(1)) == 1


def test_opposite_action_is_logged(temp_db):
    """Смена решения BUY -> SELL — новая информация, её пропускать нельзя."""
    db.log_signal(1, "AAPL", "BUY", 100.0, FORECAST, 0.8)
    assert db.log_signal(1, "AAPL", "SELL", 90.0, FORECAST, 0.8) is True
    assert len(db.get_all_signals(1)) == 2


def test_other_ticker_is_logged(temp_db):
    db.log_signal(1, "AAPL", "BUY", 100.0, FORECAST, 0.8)
    assert db.log_signal(1, "MSFT", "BUY", 400.0, FORECAST, 0.8) is True
    assert len(db.get_all_signals(1)) == 2


def test_other_user_is_not_affected(temp_db):
    """Дедупликация не должна съедать сигнал другого пользователя."""
    db.log_signal(1, "AAPL", "BUY", 100.0, FORECAST, 0.8)
    assert db.log_signal(2, "AAPL", "BUY", 100.0, FORECAST, 0.8) is True
    assert len(db.get_all_signals(2)) == 1


def test_signal_older_than_window_is_logged_again(temp_db):
    """Через неделю тот же сигнал — уже отдельное решение, а не дубль."""
    db.log_signal(1, "AAPL", "BUY", 100.0, FORECAST, 0.8)
    _age_all_signals(db.SIGNAL_DEDUP_DAYS + 1)
    assert db.log_signal(1, "AAPL", "BUY", 105.0, FORECAST, 0.8) is True
    assert len(db.get_all_signals(1)) == 2


def test_ticker_case_does_not_bypass_dedup(temp_db):
    db.log_signal(1, "aapl", "BUY", 100.0, FORECAST, 0.8)
    assert db.log_signal(1, "AAPL", "BUY", 100.0, FORECAST, 0.8) is False
