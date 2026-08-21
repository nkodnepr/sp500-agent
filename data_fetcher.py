"""
Загрузка исторических котировок через yfinance.
"""
import pandas as pd
import yfinance as yf

from config import HISTORY_YEARS


def is_valid_ticker(ticker: str) -> bool:
    """Проверяет, что тикер существует и по нему есть данные."""
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
    df = yf.Ticker(ticker).history(period=f"{years}y", interval="1d")
    if df.empty:
        raise ValueError(f"Нет данных по тикеру {ticker}")
    df = df.dropna()
    return df


def fetch_current_price(ticker: str) -> float:
    """Последняя доступная цена закрытия."""
    df = yf.Ticker(ticker).history(period="1d")
    if df.empty:
        raise ValueError(f"Нет данных по тикеру {ticker}")
    return float(df["Close"].iloc[-1])
