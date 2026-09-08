"""
Расчёт технических индикаторов (признаков) для модели.
"""
import numpy as np
import pandas as pd


def compute_rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.rolling(period).mean()
    avg_loss = loss.rolling(period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    return rsi


def compute_macd(close: pd.Series, fast=12, slow=26, signal=9):
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    hist = macd_line - signal_line
    return macd_line, signal_line, hist


def compute_bollinger(close: pd.Series, period=20, num_std=2):
    sma = close.rolling(period).mean()
    std = close.rolling(period).std()
    upper = sma + num_std * std
    lower = sma - num_std * std
    return upper, lower


def build_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    На вход — сырой OHLCV DataFrame (yfinance).
    На выход — DataFrame с техническими индикаторами как признаками.
    """
    out = pd.DataFrame(index=df.index)
    close = df["Close"]
    volume = df["Volume"]

    # Скользящие средние
    out["sma_10"] = close.rolling(10).mean()
    out["sma_50"] = close.rolling(50).mean()
    out["sma_200"] = close.rolling(200).mean()
    out["ema_12"] = close.ewm(span=12, adjust=False).mean()

    # Отношение цены к скользящим средним (нормализация)
    out["price_to_sma50"] = close / out["sma_50"] - 1
    out["price_to_sma200"] = close / out["sma_200"] - 1

    # RSI
    out["rsi_14"] = compute_rsi(close, 14)

    # MACD
    macd_line, signal_line, hist = compute_macd(close)
    out["macd_hist"] = hist

    # Bollinger Bands — позиция цены внутри полос
    upper, lower = compute_bollinger(close)
    out["bb_position"] = (close - lower) / (upper - lower)

    # Волатильность (ATR-подобная, упрощённая)
    out["volatility_20"] = close.pct_change().rolling(20).std()

    # Объём относительно среднего
    out["volume_ratio"] = volume / volume.rolling(20).mean()

    # Моментум за разные периоды
    out["momentum_5"] = close.pct_change(5)
    out["momentum_20"] = close.pct_change(20)
    out["momentum_60"] = close.pct_change(60)

    out["close"] = close
    return out.dropna()


def merge_fundamentals(feat_df: pd.DataFrame, fund_df: pd.DataFrame) -> pd.DataFrame:
    """
    Присоединяет фундаментальные метрики к дневным техническим признакам.

    Использует merge_asof (direction="backward"): для каждой даты берётся
    последняя ФАКТИЧЕСКИ ИЗВЕСТНАЯ на тот момент фундаментальная метрика
    (available_date <= дата строки). Это гарантирует отсутствие утечки
    будущих данных — важно как при обучении, так и при бэктесте.

    Если фундаментальные данные недоступны (fund_df пуст), заполняет
    нулями — модель тогда полагается только на технические индикаторы.
    """
    from fundamentals import FUNDAMENTAL_COLS

    if fund_df is None or fund_df.empty:
        out = feat_df.copy()
        for col in FUNDAMENTAL_COLS:
            out[col] = 0.0
        return out

    left = feat_df.reset_index()
    date_col = left.columns[0]
    left = left.rename(columns={date_col: "date"}).sort_values("date")

    right = fund_df.reset_index().rename(columns={"available_date": "date"}).sort_values("date")

    # Приводим типы дат к одной временной зоне (yfinance даёт tz-aware индекс)
    if left["date"].dt.tz is not None and right["date"].dt.tz is None:
        right["date"] = right["date"].dt.tz_localize(left["date"].dt.tz)
    elif left["date"].dt.tz is None and right["date"].dt.tz is not None:
        right["date"] = right["date"].dt.tz_localize(None)

    # pandas 3 требует, чтобы dtype ключей merge_asof совпадал ПОЛНОСТЬЮ,
    # включая разрешение: индекс котировок из yfinance приходит как
    # datetime64[s], а available_date строится через pd.Timestamp и даёт
    # datetime64[us]. pandas 2 такое расхождение допускал молча, начиная
    # с 3.0 оно приводит к MergeError. Приводим обе стороны к одному
    # разрешению явно — для дат потери точности здесь быть не может.
    left["date"] = left["date"].dt.as_unit("us")
    right["date"] = right["date"].dt.as_unit("us")

    merged = pd.merge_asof(left, right, on="date", direction="backward")
    merged = merged.set_index("date")

    for col in FUNDAMENTAL_COLS:
        merged[col] = merged[col].fillna(0.0)

    return merged
