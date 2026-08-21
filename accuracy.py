"""
Честная оценка точности прошлых сигналов.

Сверяет то, что модель прогнозировала (сохранено в signals_history при
каждом /check и каждом ежедневном сигнале), с тем, что случилось на
самом деле. Для каждого горизонта, по которому уже прошло достаточно
календарного времени, находится фактическая цена и сравнивается
направление движения с тем, что предсказывала модель.

Это единственный способ узнать, работает ли стратегия НА ПРАКТИКЕ, а не
полагаться на слова "модель уверена на 70%" — уверенность модели и
реальная точность часто расходятся, и увидеть это можно только сверив
прогнозы с реальностью задним числом.
"""
from datetime import datetime, timedelta

import pandas as pd

import data_fetcher

# Календарные (не торговые) дни — с запасом, чтобы рынок точно успел
# открыться рядом с целевой датой даже при выходных/праздниках
HORIZON_CALENDAR_DAYS = {"1w": 7, "2w": 14, "1m": 31, "3m": 93}

# Минимальное движение цены, чтобы считать его "направленным", а не шумом
NOISE_THRESHOLD = 0.005


def _find_price_near_date(price_series: pd.Series, target_date: pd.Timestamp,
                           tolerance_days: int = 5):
    """Ищет фактическую цену на ближайшую к target_date доступную торговую дату
    (в целевой день рынок мог быть закрыт — выходной/праздник)."""
    idx = price_series.index
    mask = (idx >= target_date - pd.Timedelta(days=tolerance_days)) & \
           (idx <= target_date + pd.Timedelta(days=tolerance_days))
    candidates = price_series[mask]
    if candidates.empty:
        return None
    closest_pos = (candidates.index - target_date).map(lambda d: abs(d.total_seconds())).argmin()
    return float(candidates.iloc[closest_pos])


def evaluate_accuracy(signal_rows, min_days_elapsed_buffer: int = 2) -> dict:
    """
    signal_rows — список записей из db.get_all_signals (полная история,
    не только последние N — иначе оценка точности будет нерепрезентативной).

    Возвращает статистику по каждому горизонту (доля верных направлений)
    и отдельно — реальную практическую эффективность BUY/SELL сигналов.
    """
    now = datetime.utcnow()
    price_cache: dict[str, pd.Series | None] = {}

    horizon_stats = {h: {"correct": 0, "total": 0} for h in HORIZON_CALENDAR_DAYS}
    action_stats = {"BUY": {"positive_outcome": 0, "total": 0},
                     "SELL": {"positive_outcome": 0, "total": 0}}

    for row in signal_rows:
        ticker = row["ticker"]
        created_at = datetime.fromisoformat(row["created_at"])
        price_at_signal = row["price_at_signal"]
        action = row["action"]

        if ticker not in price_cache:
            try:
                hist = data_fetcher.fetch_history(ticker, years=2)
                series = hist["Close"]
                series.index = series.index.tz_localize(None)
                price_cache[ticker] = series
            except Exception:
                price_cache[ticker] = None

        price_series = price_cache[ticker]
        if price_series is None:
            continue

        horizon_forecasts = {
            "1w": row["forecast_1w"], "2w": row["forecast_2w"],
            "1m": row["forecast_1m"], "3m": row["forecast_3m"],
        }

        for h_name, calendar_days in HORIZON_CALENDAR_DAYS.items():
            forecast_return = horizon_forecasts.get(h_name)
            if forecast_return is None:
                continue

            target_date = created_at + timedelta(days=calendar_days)
            # Горизонт ещё не наступил — честно пропускаем, а не додумываем
            if now < target_date + timedelta(days=min_days_elapsed_buffer):
                continue

            actual_price = _find_price_near_date(price_series, pd.Timestamp(target_date))
            if actual_price is None:
                continue

            actual_return = actual_price / price_at_signal - 1
            predicted_direction = 1 if forecast_return > 0 else (-1 if forecast_return < 0 else 0)
            actual_direction = (1 if actual_return > NOISE_THRESHOLD
                                 else (-1 if actual_return < -NOISE_THRESHOLD else 0))

            horizon_stats[h_name]["total"] += 1
            if predicted_direction == actual_direction:
                horizon_stats[h_name]["correct"] += 1

            # Практическую пользу BUY/SELL оцениваем на горизонте 1 месяц —
            # наиболее репрезентативный срок для реального решения о сделке
            if h_name == "1m" and action in ("BUY", "SELL"):
                action_stats[action]["total"] += 1
                if action == "BUY" and actual_return > 0:
                    action_stats[action]["positive_outcome"] += 1
                elif action == "SELL" and actual_return < 0:
                    action_stats[action]["positive_outcome"] += 1

    return {"horizon_stats": horizon_stats, "action_stats": action_stats}


def format_accuracy_report(stats: dict) -> str:
    h_stats = stats["horizon_stats"]
    a_stats = stats["action_stats"]

    total_evaluated = sum(v["total"] for v in h_stats.values())
    if total_evaluated == 0:
        return (
            "Пока нет сигналов, по которым прошло достаточно времени для честной "
            "оценки. Минимум неделя нужна для сигналов на 1 неделю, 3 месяца — для "
            "сигналов на 3 месяца. Продолжайте пользоваться /check — статистика "
            "накопится сама."
        )

    label_map = {"1w": "1 неделя", "2w": "2 недели", "1m": "1 месяц", "3m": "3 месяца"}
    lines = ["📊 *Честная точность прошлых сигналов*", ""]

    for h_name, label in label_map.items():
        s = h_stats[h_name]
        if s["total"] == 0:
            lines.append(f"• {label}: пока нет данных")
            continue
        acc = s["correct"] / s["total"]
        lines.append(f"• {label}: {acc:.0%} верных направлений ({s['correct']}/{s['total']})")

    lines.append("")
    lines.append("🎯 *Практическая эффективность BUY/SELL (горизонт 1 мес):*")
    for action in ("BUY", "SELL"):
        s = a_stats[action]
        if s["total"] == 0:
            lines.append(f"• {action}: пока нет данных")
            continue
        rate = s["positive_outcome"] / s["total"]
        lines.append(f"• {action}: {rate:.0%} оказались прибыльными ({s['positive_outcome']}/{s['total']})")

    lines.append("")
    lines.append(
        "_Случайное угадывание направления дало бы результат около 50%. "
        "Если точность заметно ниже — сигналам этой модели по этим тикерам "
        "пока не стоит доверять реальными деньгами._"
    )

    return "\n".join(lines)
