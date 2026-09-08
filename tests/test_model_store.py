"""Тесты для model_store.py — кэширование обученных моделей на диск."""
import json
from datetime import timedelta
from pathlib import Path

import numpy as np
import pytest
from sklearn.ensemble import RandomForestClassifier

from timeutils import utc_now
import model_store


def _fake_models():
    models = {}
    for h in ["1w", "2w", "1m", "3m"]:
        X = np.random.rand(50, 3)
        y = np.random.choice([-1, 0, 1], 50)
        models[h] = RandomForestClassifier(n_estimators=5).fit(X, y)
    return models


def test_save_and_load_models_roundtrip():
    models = _fake_models()
    model_store.save_models("PYTESTA", models, {"1w": 0.6})

    loaded, meta = model_store.load_models("PYTESTA")
    assert loaded is not None
    assert set(loaded.keys()) == {"1w", "2w", "1m", "3m"}
    assert meta["holdout_accuracies"] == {"1w": 0.6}


def test_stale_cache_returns_none():
    models = _fake_models()
    model_store.save_models("PYTESTB", models, {})

    # Искусственно состариваем метаданные за пределы MAX_MODEL_AGE_DAYS
    meta_path = Path("models_cache") / "PYTESTB" / "meta.json"
    meta = json.loads(meta_path.read_text())
    old_date = utc_now() - timedelta(days=model_store.MAX_MODEL_AGE_DAYS + 1)
    meta["trained_at"] = old_date.isoformat()
    meta_path.write_text(json.dumps(meta))

    loaded, meta_reloaded = model_store.load_models("PYTESTB")
    assert loaded is None


def test_missing_cache_returns_none():
    loaded, meta = model_store.load_models("NEVERTRND")
    assert loaded is None
    assert meta is None


def test_cache_age_days_reports_fresh_cache():
    models = _fake_models()
    model_store.save_models("PYTESTC", models, {})
    age = model_store.cache_age_days("PYTESTC")
    assert age is not None
    assert age < 0.01  # только что сохранили — возраст почти 0


def test_legacy_naive_timestamp_is_read_as_utc():
    """
    Кэш, записанный прошлой версией кода, хранит trained_at без указания
    зоны (naive UTC). После перехода на timezone-aware время такие файлы
    обязаны читаться по-прежнему — иначе обновление кода незаметно
    обнулило бы весь накопленный кэш моделей.
    """
    models = _fake_models()
    model_store.save_models("PYTESTLEG", models, {})

    meta_path = Path("models_cache") / "PYTESTLEG" / "meta.json"
    meta = json.loads(meta_path.read_text())
    naive = (utc_now() - timedelta(days=2)).replace(tzinfo=None)
    meta["trained_at"] = naive.isoformat()
    meta_path.write_text(json.dumps(meta))

    loaded, meta_reloaded = model_store.load_models("PYTESTLEG")
    assert loaded is not None, "старый naive-кэш должен читаться, а не отбраковываться"
    assert model_store.cache_age_days("PYTESTLEG") == pytest.approx(2.0, abs=0.01)


def test_unreadable_model_file_triggers_retrain():
    """
    Кэш может пройти проверку целостности и всё равно не прочитаться —
    например, после обновления scikit-learn формат pickle несовместим.
    Это должно приводить к переобучению, а не к падению приложения.
    """
    model_store.save_models("PYTESTBAD", _fake_models(), {})
    d = Path("models_cache") / "PYTESTBAD"

    # Мусор вместо модели И пересчитанная под него подпись — так
    # имитируется "целый, но нечитаемый" файл кэша.
    (d / "1w.joblib").write_bytes(b"not a model at all")
    key = model_store._get_or_create_integrity_key()
    meta = json.loads((d / "meta.json").read_text())
    meta["checksums"]["1w"] = model_store._compute_hmac((d / "1w.joblib").read_bytes(), key)
    (d / "meta.json").write_text(json.dumps(meta))

    loaded, _ = model_store.load_models("PYTESTBAD")
    assert loaded is None, "нечитаемый кэш должен приводить к переобучению, а не к исключению"
