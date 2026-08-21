"""
Персистентность обученных моделей.

Без кэширования RandomForest переобучался бы заново при КАЖДОМ вызове
прогноза — то есть при каждом /check и при каждом ежедневном прогоне по
всем тикерам всех пользователей. Это расточительно и не нужно: рыночные
закономерности не меняются настолько быстро, чтобы требовать
переобучения каждый день.

Здесь модели обучаются раз в неделю (см. weekly_retrain_job в
telegram_bot.py) и сохраняются на диск. В течение недели прогнозы
используют уже готовые модели — это быстро и не грузит CPU впустую.
"""
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path

import joblib

logger = logging.getLogger(__name__)

from config import MODELS_CACHE_DIR

MODELS_DIR = Path(MODELS_CACHE_DIR)
MAX_MODEL_AGE_DAYS = 7


def _ticker_dir(ticker: str) -> Path:
    d = MODELS_DIR / ticker.upper()
    d.mkdir(parents=True, exist_ok=True)
    return d


def save_models(ticker: str, models: dict, holdout_accuracies: dict):
    """models: {horizon_name: обученная sklearn-модель}"""
    d = _ticker_dir(ticker)
    for horizon, model in models.items():
        joblib.dump(model, d / f"{horizon}.joblib")

    meta = {
        "trained_at": datetime.utcnow().isoformat(),
        "holdout_accuracies": holdout_accuracies,
    }
    (d / "meta.json").write_text(json.dumps(meta))
    logger.info("Модели для %s сохранены в кэш", ticker)


def load_models(ticker: str):
    """
    Возвращает (models, meta), если есть свежий (< MAX_MODEL_AGE_DAYS дней)
    кэш моделей на диске. Иначе (None, None) — сигнал вызывающему коду,
    что нужно переобучение "на лету".
    """
    d = _ticker_dir(ticker)
    meta_path = d / "meta.json"
    if not meta_path.exists():
        return None, None

    try:
        meta = json.loads(meta_path.read_text())
        trained_at = datetime.fromisoformat(meta["trained_at"])
    except Exception:
        return None, None

    if datetime.utcnow() - trained_at > timedelta(days=MAX_MODEL_AGE_DAYS):
        return None, None

    from model import HORIZONS  # локальный импорт — избегаем циклического импорта

    models = {}
    for horizon in HORIZONS:
        path = d / f"{horizon}.joblib"
        if not path.exists():
            return None, None
        models[horizon] = joblib.load(path)

    return models, meta


def cache_age_days(ticker: str) -> float | None:
    """Сколько дней назад обучалась модель. None — если кэша нет вообще."""
    _, meta = load_models(ticker)
    if meta is None:
        return None
    trained_at = datetime.fromisoformat(meta["trained_at"])
    return (datetime.utcnow() - trained_at).total_seconds() / 86400
