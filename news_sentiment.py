"""
Анализ настроений в новостях (FinBERT).

FinBERT — версия BERT, дообученная на финансовых текстах для классификации
тональности (Positive/Negative/Neutral). Используется здесь как ЖИВОЙ
(real-time) модификатор итогового сигнала, а НЕ как признак для обучения
модели по историческим данным.

Почему не признак для обучения: бесплатных источников с историческим
архивом новостей за несколько лет с точной привязкой по датам не
существует (в отличие от котировок и отчётности). yfinance отдаёт только
последние ~10-20 новостей без глубокой истории. Вставлять sentiment как
обучающий признак в этих условиях означало бы либо утечку данных
(используя сегодняшние новости как признак для прошлых дат), либо
обучение почти всегда на нулевом значении — оба варианта хуже, чем
честно использовать sentiment только как поправку к сигналу здесь и
сейчас, о чём модель "не знает", но что явно показывается пользователю.

Модель грузится лениво (при первом реальном вызове), т.к. первая загрузка
FinBERT — это скачивание ~400 МБ весов, а сам modуль импортируется на
старте бота.
"""
import logging

logger = logging.getLogger(__name__)

_pipeline = None
_load_failed = False


def _get_pipeline():
    """Ленивая загрузка FinBERT. Если transformers/torch не установлены
    или модель не удалось скачать — sentiment-анализ тихо отключается,
    а не роняет весь бот."""
    global _pipeline, _load_failed
    if _pipeline is not None or _load_failed:
        return _pipeline
    try:
        from transformers import pipeline
        logger.info("Загружаю FinBERT (первый раз может занять пару минут)...")
        _pipeline = pipeline("sentiment-analysis", model="ProsusAI/finbert")
        logger.info("FinBERT загружен")
    except Exception as e:
        logger.warning(
            "FinBERT недоступен (%s). Sentiment-анализ отключён, "
            "используется нейтральное значение по умолчанию.", e
        )
        _load_failed = True
        _pipeline = None
    return _pipeline


def fetch_recent_headlines(ticker: str, max_items: int = 10) -> list[str]:
    """Последние заголовки новостей по тикеру через yfinance."""
    import yfinance as yf
    try:
        news = yf.Ticker(ticker).news or []
    except Exception:
        return []

    headlines = []
    for item in news[:max_items]:
        # структура ответа yfinance периодически меняется между версиями
        title = item.get("title") or item.get("content", {}).get("title")
        if title:
            headlines.append(title)
    return headlines


def get_sentiment_score(ticker: str) -> dict:
    """
    Агрегированная оценка настроений по последним новостям.

    score: от -1 (крайне негативный фон) до +1 (крайне позитивный)
    label: человекочитаемая метка на русском
    num_articles: сколько новостей учтено

    Если новостей нет или FinBERT недоступен — возвращает нейтральный
    результат (score=0.0), а не бросает исключение: вызывающий код
    (сигнальная логика) не должен падать из-за отсутствия sentiment.
    """
    headlines = fetch_recent_headlines(ticker)
    if not headlines:
        return {"score": 0.0, "label": "Нет свежих новостей", "num_articles": 0}

    pipe = _get_pipeline()
    if pipe is None:
        return {"score": 0.0, "label": "Sentiment-анализ недоступен", "num_articles": len(headlines)}

    try:
        results = pipe(headlines)
    except Exception as e:
        logger.warning("Ошибка инференса FinBERT: %s", e)
        return {"score": 0.0, "label": "Ошибка анализа", "num_articles": len(headlines)}

    # Каждый результат: {'label': 'positive'/'negative'/'neutral', 'score': 0..1}
    total = 0.0
    for r in results:
        label = r["label"].lower()
        conf = r["score"]
        if label == "positive":
            total += conf
        elif label == "negative":
            total -= conf
        # neutral не вносит вклад в сумму

    score = total / len(results)

    if score > 0.15:
        label_ru = "Позитивный"
    elif score < -0.15:
        label_ru = "Негативный"
    else:
        label_ru = "Нейтральный"

    return {"score": float(score), "label": label_ru, "num_articles": len(headlines)}
