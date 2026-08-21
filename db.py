"""
Работа с базой данных (SQLite).
Хранит watchlist каждого пользователя и историю отправленных сигналов
(нужна для последующей оценки точности модели).
"""
import sqlite3
from contextlib import contextmanager
from datetime import datetime

from config import DB_PATH


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS watchlist (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                ticker TEXT NOT NULL,
                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(user_id, ticker)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS signals_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                ticker TEXT NOT NULL,
                action TEXT NOT NULL,
                price_at_signal REAL NOT NULL,
                forecast_1w REAL,
                forecast_2w REAL,
                forecast_1m REAL,
                forecast_3m REAL,
                confidence REAL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)


# --- Watchlist ---

def add_ticker(user_id: int, ticker: str) -> bool:
    with get_conn() as conn:
        try:
            conn.execute(
                "INSERT INTO watchlist (user_id, ticker) VALUES (?, ?)",
                (user_id, ticker.upper()),
            )
            return True
        except sqlite3.IntegrityError:
            return False


def remove_ticker(user_id: int, ticker: str) -> bool:
    with get_conn() as conn:
        cur = conn.execute(
            "DELETE FROM watchlist WHERE user_id=? AND ticker=?",
            (user_id, ticker.upper()),
        )
        return cur.rowcount > 0


def get_watchlist(user_id: int) -> list[str]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT ticker FROM watchlist WHERE user_id=? ORDER BY added_at",
            (user_id,),
        ).fetchall()
        return [r["ticker"] for r in rows]


def get_all_users() -> list[int]:
    with get_conn() as conn:
        rows = conn.execute("SELECT DISTINCT user_id FROM watchlist").fetchall()
        return [r["user_id"] for r in rows]


# --- Signals history ---

def log_signal(user_id: int, ticker: str, action: str, price: float,
                forecast: dict, confidence: float):
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO signals_history
            (user_id, ticker, action, price_at_signal, forecast_1w, forecast_2w,
             forecast_1m, forecast_3m, confidence)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            user_id, ticker, action, price,
            forecast.get("1w"), forecast.get("2w"),
            forecast.get("1m"), forecast.get("3m"),
            confidence,
        ))


def get_signal_history(user_id: int, limit: int = 20) -> list[sqlite3.Row]:
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT * FROM signals_history
            WHERE user_id=?
            ORDER BY created_at DESC
            LIMIT ?
        """, (user_id, limit)).fetchall()
        return rows


def get_all_signals(user_id: int) -> list[sqlite3.Row]:
    """Вся история сигналов пользователя (без лимита) — нужна для честной
    оценки точности в accuracy.py: последние 10-20 сигналов дали бы
    смещённую, нерепрезентативную статистику."""
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT * FROM signals_history
            WHERE user_id=?
            ORDER BY created_at ASC
        """, (user_id,)).fetchall()
        return rows
