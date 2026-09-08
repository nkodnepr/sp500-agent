"""
Быстрый технический скрининг всех компаний S&P 500.

ПОЧЕМУ ДВА ЭТАПА, А НЕ ПОЛНЫЙ АНАЛИЗ СРАЗУ: полный анализ (обучение
RandomForest по 4 горизонтам, фундаментал, sentiment, риск-уровни —
всё, что делает build_full_analysis в desktop_engine.py) для одного
тикера занимает до минуты. Для 500 тикеров это часы — непрактично для
разового запуска и рискует упереться в ограничения источника данных.

Вместо этого — двухэтапный подход, стандартный в квантовом скрининге:

1. БЫСТРЫЙ ЭТАП (этот модуль): один batch-запрос котировок по всем ~500
   тикерам сразу (fetch_history_bulk) + простой технический скор без
   обучения модели — занимает минуты, не часы.
2. ГЛУБОКИЙ ЭТАП: полный анализ (build_full_analysis) запускается только
   по шорт-листу лучших/худших кандидатов из этапа 1 — уже посильно по
   времени, как обычный скан нескольких тикеров.

Быстрый скор — НЕ замена полному анализу. Это грубый технический фильтр
для сужения 500 компаний до управляемого числа кандидатов, которые уже
стоит разбирать подробно.
"""
import numpy as np
import pandas as pd

import data_fetcher
from features import build_features

# Веса компонентов скора должны суммироваться в 1.0 — это гарантируется
# тестом test_sp500_screener.py::test_score_weights_sum_to_one
SCORE_WEIGHTS = {
    "momentum_20": 0.30,
    "momentum_60": 0.25,
    "price_to_sma50": 0.20,
    "price_to_sma200": 0.15,
    "rsi_14": 0.10,
}


def compute_quick_score(feat_df: pd.DataFrame) -> float:
    """
    Простой технический скор последней доступной точки без обучения
    модели: взвешенная сумма моментума на разных горизонтах и позиции
    цены относительно скользящих средних, нормированная в диапазон
    примерно [-1, 1]. Положительный — бычьи технические признаки,
    отрицательный — медвежьи.
    """
    last = feat_df.iloc[-1]

    momentum_20 = np.clip(last["momentum_20"], -0.3, 0.3) / 0.3
    momentum_60 = np.clip(last["momentum_60"], -0.3, 0.3) / 0.3
    price_to_sma50 = np.clip(last["price_to_sma50"], -0.2, 0.2) / 0.2
    price_to_sma200 = np.clip(last["price_to_sma200"], -0.2, 0.2) / 0.2
    rsi_component = np.clip((last["rsi_14"] - 50) / 50, -1, 1)

    score = (
        SCORE_WEIGHTS["momentum_20"] * momentum_20
        + SCORE_WEIGHTS["momentum_60"] * momentum_60
        + SCORE_WEIGHTS["price_to_sma50"] * price_to_sma50
        + SCORE_WEIGHTS["price_to_sma200"] * price_to_sma200
        + SCORE_WEIGHTS["rsi_14"] * rsi_component
    )
    return float(score)


def screen_universe(tickers: list[str], progress_callback=None) -> list[dict]:
    """
    Прогоняет быстрый скрининг по всем переданным тикерам.

    Возвращает список {"ticker", "score", "price"}, отсортированный по
    убыванию score (самые технически "бычьи" — сверху). Тикеры, по
    которым не удалось получить или посчитать данные, молча пропускаются
    — ожидаемо для батча такого размера (делистинги, паузы в торгах,
    слишком короткая история для индикаторов).
    """
    if progress_callback:
        progress_callback(0, 1, f"Загружаю котировки по {len(tickers)} тикерам...")

    bulk_data = data_fetcher.fetch_history_bulk(tickers, period="1y")

    results = []
    total = len(bulk_data)
    for i, (ticker, raw) in enumerate(bulk_data.items()):
        if progress_callback and i % 20 == 0:
            progress_callback(i, total, ticker)
        try:
            feat = build_features(raw)
            if feat.empty:
                continue
            score = compute_quick_score(feat)
            results.append({
                "ticker": ticker,
                "score": score,
                "price": float(feat["close"].iloc[-1]),
            })
        except Exception:
            continue

    results.sort(key=lambda r: r["score"], reverse=True)
    return results


def shortlist_candidates(screened: list[dict], top_n: int = 10) -> list[str]:
    """
    Top_n самых бычьих + top_n самых медвежьих кандидатов по быстрому
    скору — их и стоит разобрать полным анализом на следующем этапе.
    Если после дедупликации (при малом списке верх и низ могут
    пересекаться) кандидатов меньше 2*top_n — это ожидаемо и не ошибка.
    """
    if not screened:
        return []
    bullish = [r["ticker"] for r in screened[:top_n]]
    bearish = [r["ticker"] for r in screened[-top_n:]]
    # dict.fromkeys сохраняет порядок и убирает дубликаты (могут
    # возникнуть, если общий список короче 2*top_n)
    return list(dict.fromkeys(bullish + bearish))
