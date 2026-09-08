"""
Загрузка исторических котировок через yfinance.
"""
import pandas as pd
import yfinance as yf

from config import HISTORY_YEARS
from ticker_validation import is_safe_ticker_format, sanitize_ticker


def is_valid_ticker(ticker: str) -> bool:
    """Проверяет, что тикер существует и по нему есть данные."""
    # Сначала дешёвая проверка формата (без сети) — заодно не даёт
    # мусорным/подозрительным строкам вообще дойти до внешнего запроса
    if not is_safe_ticker_format(ticker):
        return False
    try:
        hist = yf.Ticker(ticker).history(period="5d")
        return not hist.empty
    except Exception:
        return False


def fetch_history(ticker: str, years: int = HISTORY_YEARS) -> pd.DataFrame:
    """
    Загружает дневные OHLCV данные за N лет.
    Возвращает DataFrame с колонками: Open, High, Low, Close, Volume
    """
    ticker = sanitize_ticker(ticker)  # ValueError на некорректный формат — до похода в сеть
    df = yf.Ticker(ticker).history(period=f"{years}y", interval="1d")
    if df.empty:
        raise ValueError(f"Нет данных по тикеру {ticker}")
    df = df.dropna()
    return df


def fetch_current_price(ticker: str) -> float:
    """Последняя доступная цена закрытия."""
    ticker = sanitize_ticker(ticker)
    df = yf.Ticker(ticker).history(period="1d")
    if df.empty:
        raise ValueError(f"Нет данных по тикеру {ticker}")
    return float(df["Close"].iloc[-1])


def fetch_history_bulk(tickers: list[str], period: str = "1y") -> dict:
    """
    Массовая загрузка котировок для большого числа тикеров одним запросом —
    на порядок быстрее последовательных yf.Ticker(t).history() вызовов
    благодаря встроенной многопоточности yfinance.download(). Нужна для
    скрининга всего S&P 500 (500 последовательных запросов заняли бы
    слишком долго и рисковали упереться в ограничения Yahoo Finance).

    Тикеры, для которых не удалось получить данные (делистинг, опечатка,
    временный сбой источника), просто отсутствуют в результате — это
    ожидаемо для батча такого размера, не повод прерывать весь скрининг.
    """
    if not tickers:
        return {}

    raw = yf.download(
        tickers=tickers, period=period, group_by="ticker",
        threads=True, progress=False, auto_adjust=True,
    )

    result = {}
    if len(tickers) == 1:
        # yf.download с одним тикером не создаёт мультииндекс колонок —
        # результат сразу в "плоском" формате
        t = tickers[0]
        if not raw.empty:
            cleaned = raw.dropna()
            if not cleaned.empty:
                result[t] = cleaned
        return result

    for t in tickers:
        try:
            df = raw[t].dropna()
            if not df.empty:
                result[t] = df
        except Exception:
            # KeyError (тикера нет в ответе) — самый частый случай, но
            # ловим любую ошибку: батч на 500 тикеров не должен падать
            # целиком из-за одной проблемной бумаги. Перечислять KeyError
            # рядом с Exception бессмысленно — второй и так его покрывает.
            continue

    return result
