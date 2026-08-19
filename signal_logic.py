"""
Правила формирования рекомендации BUY / SELL / HOLD
на основе прогнозов модели по всем горизонтам.

Логика намеренно простая и прозрачная (не "чёрный ящик"):
- BUY: краткосрочный и среднесрочный прогноз согласованно положительны,
       уверенность модели выше порога
- SELL: краткосрочный и среднесрочный прогноз согласованно отрицательны
- HOLD: сигналы противоречивы, уверенность низкая, или контекст (новости,
        рынок в целом, приближающаяся отчётность) резко противоречит
        техническому сигналу

Модификаторы (sentiment, режим рынка, отчётность) НЕ формируют сигнал
самостоятельно — только ограничивают уже принятое техническое решение.
Это защищает от покупки/продажи вопреки контексту, который сама модель,
обученная на исторических котировках конкретной акции, не видит.
"""
from config import CONFIDENCE_THRESHOLD, SIGNAL_THRESHOLD_PCT

# Порог |sentiment score|, при превышении которого новости считаются
# достаточно однозначными, чтобы притормозить технический сигнал
SENTIMENT_OVERRIDE_THRESHOLD = 0.3


def generate_signal(forecast: dict, sentiment: dict | None = None,
                     market: dict | None = None, earnings: dict | None = None) -> dict:
    horizons = forecast["horizons"]

    # Пропускаем, если для какого-то горизонта не удалось построить модель
    if any("error" in h for h in horizons.values()):
        return {"action": "HOLD", "reason": "Недостаточно данных для полного анализа",
                "confidence": 0.0, "sentiment": sentiment, "market": market}

    directions = [h["direction"] for h in horizons.values()]
    confidences = [h["confidence"] for h in horizons.values()]
    avg_confidence = sum(confidences) / len(confidences)

    # Согласованность сигналов между горизонтами
    bullish_votes = sum(1 for d in directions if d == 1)
    bearish_votes = sum(1 for d in directions if d == -1)

    max_expected_return = max(h["expected_return"] for h in horizons.values())
    min_expected_return = min(h["expected_return"] for h in horizons.values())

    if (bullish_votes >= 3 and avg_confidence >= CONFIDENCE_THRESHOLD
            and max_expected_return >= SIGNAL_THRESHOLD_PCT):
        action = "BUY"
        reason = f"Согласованный рост на {bullish_votes}/4 горизонтах, ожидаемая доходность до {max_expected_return:.1%}"
    elif (bearish_votes >= 3 and avg_confidence >= CONFIDENCE_THRESHOLD
            and min_expected_return <= -SIGNAL_THRESHOLD_PCT):
        action = "SELL"
        reason = f"Согласованное падение на {bearish_votes}/4 горизонтах, ожидаемое снижение до {min_expected_return:.1%}"
    else:
        action = "HOLD"
        reason = "Сигналы противоречивы или уверенность модели ниже порога"

    # Sentiment как ограничивающий, а не основной фактор
    if sentiment and sentiment.get("num_articles", 0) > 0:
        score = sentiment["score"]
        if action == "BUY" and score < -SENTIMENT_OVERRIDE_THRESHOLD:
            action = "HOLD"
            reason = (f"Технически сигнал на покупку, но новостной фон резко "
                      f"негативный ({sentiment['label']}) — сигнал понижен до HOLD")
        elif action == "SELL" and score > SENTIMENT_OVERRIDE_THRESHOLD:
            action = "HOLD"
            reason = (f"Технически сигнал на продажу, но новостной фон резко "
                      f"позитивный ({sentiment['label']}) — сигнал понижен до HOLD")

    # Режим рынка: покупка против сильного медвежьего рынка требует
    # ЕДИНОГЛАСНОГО согласия всех 4 горизонтов (4/4, не 3/4) — иначе
    # понижаем до HOLD. Идея не в том, что рост акции на падающем рынке
    # невозможен, а в том, что планка доказательств должна быть выше.
    if market and market.get("regime") == "bear" and action == "BUY" and bullish_votes < 4:
        action = "HOLD"
        reason = (f"Технически сигнал на покупку, но рынок в целом в медвежьей "
                  f"фазе ({market['label']}), а согласие модели неполное "
                  f"({bullish_votes}/4) — сигнал понижен до HOLD")
    elif market and market.get("regime") == "bull" and action == "SELL" and bearish_votes < 4:
        action = "HOLD"
        reason = (f"Технически сигнал на продажу, но рынок в целом в бычьей "
                  f"фазе ({market['label']}), а согласие модели неполное "
                  f"({bearish_votes}/4) — сигнал понижен до HOLD")

    # Приближающаяся отчётность — явное предупреждение, не блокировка
    # сигнала (решение остаётся за пользователем), но обязательно видно
    earnings_warning = None
    if earnings and earnings.get("next_earnings_date") and action in ("BUY", "SELL"):
        # Проверяем самый короткий горизонт, относящийся к решению (1 месяц —
        # типичный срок удержания позиции при таком сигнале)
        if earnings.get("within", {}).get("1m"):
            days = earnings.get("days_until")
            earnings_warning = (
                f"Через {days} дн. ожидается публикация отчётности — "
                f"возможен резкий скачок цены вне зависимости от текущего тренда"
            )

    return {
        "action": action,
        "reason": reason,
        "confidence": avg_confidence,
        "sentiment": sentiment,
        "market": market,
        "earnings_warning": earnings_warning,
    }
