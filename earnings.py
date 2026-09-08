"""
Отслеживание даты ближайшей отчётности.

Публикация квартального отчёта — один из немногих моментов, когда цена
акции может резко скакнуть (5-15%+ за одну сессию) по причинам, которые
технический анализ по определению не может предсказать: рынок реагирует
на неожиданность (surprise) относительно ожиданий аналитиков, а не на
паттерн в графике. Если горизонт прогноза захватывает дату отчётности —
модель, обученная на "обычных" рыночных днях, скорее всего недооценивает
реальный риск на этот период.
"""
import logging
import pandas as pd

from timeutils import utc_now

logger = logging.getLogger(__name__)


def get_next_earnings_date(ticker: str):
    """Возвращает datetime следующей отчётности или None, если не найдено."""
    try:
        import yfinance as yf
        tkr = yf.Ticker(ticker)
        cal = tkr.calendar
        if cal is None:
            return None

        # yfinance периодически меняет формат: то dict, то DataFrame
        if isinstance(cal, dict):
            date_val = cal.get("Earnings Date")
        else:
            date_val = cal.loc["Earnings Date"].iloc[0] if "Earnings Date" in getattr(cal, "index", []) else None

        if date_val is None:
            return None
        if isinstance(date_val, (list, tuple)):
            date_val = date_val[0]

        return pd.Timestamp(date_val).to_pydatetime() if date_val else None
    except Exception as e:
        logger.debug("Не удалось получить дату отчётности для %s: %s", ticker, e)
        return None


def check_earnings_within_horizons(ticker: str, horizon_days: dict) -> dict:
    """
    Проверяет, попадает ли ближайшая отчётность в каждый из горизонтов
    прогноза (1w/2w/1m/3m). Возвращает {"next_earnings_date": ..., "within": {horizon: bool}}
    """
    next_date = get_next_earnings_date(ticker)
    result = {"next_earnings_date": next_date, "within": {}}

    if next_date is None:
        result["within"] = {h: False for h in horizon_days}
        return result

    days_until = (next_date.date() - utc_now().date()).days
    for h_name, h_trading_days in horizon_days.items():
        # Грубый перевод торговых дней в календарные (запас x1.45)
        calendar_days = int(h_trading_days * 1.45)
        result["within"][h_name] = 0 <= days_until <= calendar_days

    result["days_until"] = days_until
    return result
