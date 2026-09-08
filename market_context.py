"""
Рыночный контекст: относительная сила акции против рынка (S&P 500) и
режим рынка (бычий/медвежий/боковой).

Зачем это нужно: модель, обученная только на индикаторах самой акции, не
"знает", падает или растёт рынок в целом. Акция может технически выглядеть
"на покупку" просто потому, что весь рынок растёт — а не потому, что у
неё есть собственное преимущество. Относительная сила (excess return
против SPY) отделяет движение конкретной акции от общерыночного шума —
это то, что реальные аналитики называют "alpha vs beta".

Признаки безопасны для обучения/бэктеста без утечки будущего: на каждую
дату используется только доходность акции и SPY ЗА ПРОШЕДШИЕ N дней —
та же логика, что и у моментум-признаков в features.py.
"""
import logging
from datetime import timedelta

import pandas as pd
import yfinance as yf

from timeutils import utc_now

logger = logging.getLogger(__name__)

RELATIVE_STRENGTH_WINDOWS = {"relative_strength_20": 20, "relative_strength_60": 60}

# Сколько живёт кэш истории SPY в памяти процесса.
#
# ЗАЧЕМ СРОК ЖИЗНИ: бот на сервере работает неделями без перезапуска, а
# кэш без TTL означал бы, что режим рынка и относительная сила навсегда
# считаются по котировкам на дату старта процесса. Ежедневный прогон
# продолжал бы выдавать сигналы, опираясь на всё более устаревшую
# картину рынка, и заметить это по логам было бы невозможно — ошибок
# нет, просто данные тихо не обновляются. Дневные свечи меняются раз в
# сутки, поэтому нескольких часов более чем достаточно.
MARKET_CACHE_TTL = timedelta(hours=6)

_spy_cache: pd.DataFrame | None = None
_spy_cache_at = None


def clear_market_cache() -> None:
    """Принудительно сбрасывает кэш SPY (нужен тестам и ручному обновлению)."""
    global _spy_cache, _spy_cache_at
    _spy_cache = None
    _spy_cache_at = None


def fetch_market_history(years: int = 5) -> pd.DataFrame:
    """Дневная история SPY (прокси на весь рынок США). Кэшируется в памяти
    процесса на MARKET_CACHE_TTL — SPY нужен для каждого тикера, незачем
    перезагружать по сети на каждый вызов, но и держать вечно нельзя."""
    global _spy_cache, _spy_cache_at

    if (_spy_cache is not None and _spy_cache_at is not None
            and utc_now() - _spy_cache_at < MARKET_CACHE_TTL):
        return _spy_cache

    try:
        df = yf.Ticker("SPY").history(period=f"{years}y", interval="1d")
        error = None
    except Exception as e:
        df, error = pd.DataFrame(), e

    if df.empty:
        # Обновить не удалось. Если в кэше остались прошлые данные — они
        # устарели, но всё равно ближе к реальности, чем нулевая
        # относительная сила и режим "Н/д", в которые превратится
        # исключение выше по стеку.
        if _spy_cache is not None:
            logger.warning(
                "Не удалось обновить историю SPY (%s) — использую предыдущие "
                "данные из кэша (получены %s)", error, _spy_cache_at,
            )
            return _spy_cache
        raise ValueError("Не удалось загрузить данные SPY для рыночного контекста")

    _spy_cache = df.dropna()
    _spy_cache_at = utc_now()
    return _spy_cache


def add_relative_strength(feat_df: pd.DataFrame, close_col: str = "close") -> pd.DataFrame:
    """
    Добавляет колонки relative_strength_20 / relative_strength_60 —
    доходность акции МИНУС доходность SPY за тот же период. Положительное
    значение = акция обгоняет рынок (алгоритмически: собственная сила,
    а не просто "рынок растёт, всё растёт").
    """
    out = feat_df.copy()
    try:
        spy = fetch_market_history()
        spy_close = spy["Close"]
        if spy_close.index.tz is not None and out.index.tz is None:
            spy_close.index = spy_close.index.tz_localize(None)
        elif spy_close.index.tz is None and out.index.tz is not None:
            spy_close = spy_close.copy()
            spy_close.index = spy_close.index.tz_localize(out.index.tz)

        spy_aligned = spy_close.reindex(out.index, method="ffill")

        for col_name, window in RELATIVE_STRENGTH_WINDOWS.items():
            stock_return = out[close_col].pct_change(window)
            spy_return = spy_aligned.pct_change(window)
            out[col_name] = (stock_return - spy_return).fillna(0.0)
    except Exception:
        # Если SPY недоступен — не роняем весь прогноз, просто без
        # рыночного контекста (нейтральные нули)
        for col_name in RELATIVE_STRENGTH_WINDOWS:
            out[col_name] = 0.0

    return out


def get_market_regime() -> dict:
    """
    Простое определение режима рынка по SPY: цена выше/ниже 200-дневной
    средней плюс недавний моментум определяют "бычий"/"медвежий"/"боковой".
    Используется как контекст в сообщении и как ограничивающий фактор в
    signal_logic.py (не покупать вопреки сильному медвежьему рынку без
    очень сильного собственного сигнала у акции).
    """
    try:
        spy = fetch_market_history()
        close = spy["Close"]
        sma200 = close.rolling(200).mean()
        current = float(close.iloc[-1])
        sma_now = float(sma200.iloc[-1])
        momentum_20 = float(close.pct_change(20).iloc[-1])

        price_vs_sma = current / sma_now - 1

        if price_vs_sma > 0.02 and momentum_20 > 0:
            regime = "bull"
            label = "Бычий (растущий рынок)"
        elif price_vs_sma < -0.02 and momentum_20 < 0:
            regime = "bear"
            label = "Медвежий (падающий рынок)"
        else:
            regime = "sideways"
            label = "Боковой (без выраженного тренда)"

        return {
            "regime": regime,
            "label": label,
            "spy_price": current,
            "price_vs_sma200": price_vs_sma,
            "momentum_20d": momentum_20,
        }
    except Exception:
        return {"regime": "unknown", "label": "Н/д", "spy_price": None,
                "price_vs_sma200": None, "momentum_20d": None}
