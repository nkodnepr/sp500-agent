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

--- О БЕЗОПАСНОСТИ ХРАНЕНИЯ МОДЕЛЕЙ ---

joblib.load() (как и pickle, на котором он основан) исполняет код при
десериализации — это общеизвестный класс уязвимостей (CWE-502). Если бы
кто-то подменил файл в models_cache/ на специально сформированный
вредоносный .joblib, load_models() выполнил бы его код при следующей
загрузке кэша.

Полностью уйти от pickle-based форматов для sklearn-моделей без
серьёзной переработки нельзя (это стандартный формат сериализации
scikit-learn) — но здесь добавлена проверка целостности: у каждого
файла есть HMAC-подпись, вычисленная с локальным секретным ключом,
который создаётся один раз при первом запуске и никогда никуда не
передаётся. Если файл или его подпись не совпадают — кэш считается
недействительным и модель переобучается заново, а не загружается вслепую.

Это НЕ защищает от атакующего, у которого уже есть полный доступ к
файловой системе (он может прочитать и ключ, и пересчитать подпись
самостоятельно) — но защищает от куда более вероятных сценариев: кэш
случайно попал в общую/синхронизируемую папку, скопирован с чужого
компьютера, подменён процессом с ограниченными правами. Поэтому:

  НИКОГДА не копируйте папку models_cache/ с чужого компьютера или
  из непроверенного источника — переносите её только вместе с .env
  и остальными файлами СВОЕЙ собственной установки.
"""
import hashlib
import hmac
import json
import logging
import secrets
from datetime import timedelta
from pathlib import Path

import joblib

from config import MODELS_CACHE_DIR
from ticker_validation import sanitize_ticker
from timeutils import utc_now, parse_utc

logger = logging.getLogger(__name__)

MODELS_DIR = Path(MODELS_CACHE_DIR)
MAX_MODEL_AGE_DAYS = 7

_KEY_FILE = MODELS_DIR / ".integrity_key"


def _get_or_create_integrity_key() -> bytes:
    """
    Локальный секретный ключ для HMAC-подписи файлов кэша. Создаётся один
    раз при первом сохранении модели и переиспользуется дальше. Не имеет
    смысла копировать/синхронизировать этот файл вместе с кэшем на другой
    компьютер — тогда подпись перестаёт быть секретом и теряет смысл
    (см. пояснение о модели угроз в начале файла).
    """
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    if _KEY_FILE.exists():
        return _KEY_FILE.read_bytes()

    key = secrets.token_bytes(32)
    _KEY_FILE.write_bytes(key)
    try:
        os_chmod_owner_only(_KEY_FILE)
    except Exception:
        pass  # не критично (например, недоступно на некоторых ФС Windows) — не блокируем работу
    return key


def os_chmod_owner_only(path: Path):
    """На POSIX-системах (Linux/macOS) ограничивает права на файл ключа
    только владельцем. На Windows chmod не имеет такого эффекта — это
    не проблема, а особенность платформы, поэтому вызов обёрнут в try/except."""
    import os
    os.chmod(path, 0o600)


def _compute_hmac(data: bytes, key: bytes) -> str:
    return hmac.new(key, data, hashlib.sha256).hexdigest()


def _ticker_dir(ticker: str) -> Path:
    # sanitize_ticker — не дублирующая, а САМОСТОЯТЕЛЬНАЯ проверка: этот
    # модуль не должен полагаться на то, что вызывающий код (бот, GUI,
    # другой скрипт) уже провалидировал строку где-то выше по цепочке.
    # Без этой проверки здесь было бы место для path traversal (CWE-22) —
    # ticker вроде "..\\..\\AppData\\Roaming\\Startup\\x" мог бы вывести
    # запись файлов за пределы папки кэша.
    safe_ticker = sanitize_ticker(ticker)
    d = MODELS_DIR / safe_ticker
    d.mkdir(parents=True, exist_ok=True)
    return d


def save_models(ticker: str, models: dict, holdout_accuracies: dict):
    """models: {horizon_name: обученная sklearn-модель}"""
    d = _ticker_dir(ticker)
    key = _get_or_create_integrity_key()
    checksums = {}

    for horizon, model in models.items():
        path = d / f"{horizon}.joblib"
        joblib.dump(model, path)
        checksums[horizon] = _compute_hmac(path.read_bytes(), key)

    meta = {
        "trained_at": utc_now().isoformat(),
        "holdout_accuracies": holdout_accuracies,
        "checksums": checksums,
    }
    (d / "meta.json").write_text(json.dumps(meta))
    logger.info("Модели для %s сохранены в кэш", ticker)


def load_models(ticker: str):
    """
    Возвращает (models, meta), если есть свежий (< MAX_MODEL_AGE_DAYS дней)
    и ЦЕЛЫЙ (проверенный по HMAC) кэш моделей на диске. Иначе (None, None)
    — сигнал вызывающему коду, что нужно переобучение "на лету". Это же
    происходит, если контрольная сумма файла не совпала с сохранённой —
    несовпадение трактуется как потенциальная подмена, а не как повод
    попытаться всё равно загрузить файл.
    """
    d = _ticker_dir(ticker)
    meta_path = d / "meta.json"
    if not meta_path.exists():
        return None, None

    try:
        meta = json.loads(meta_path.read_text())
        trained_at = parse_utc(meta["trained_at"])
    except Exception:
        return None, None

    if utc_now() - trained_at > timedelta(days=MAX_MODEL_AGE_DAYS):
        return None, None

    from model import HORIZONS  # локальный импорт — избегаем циклического импорта

    checksums = meta.get("checksums", {})
    key = _get_or_create_integrity_key()

    models = {}
    for horizon in HORIZONS:
        path = d / f"{horizon}.joblib"
        if not path.exists():
            return None, None

        expected = checksums.get(horizon)
        if expected is None:
            # Кэш сохранён до появления проверки целостности (старая
            # версия) — не считаем это подменой, но и не доверяем слепо:
            # безопаснее переобучить, чем один раз пропустить проверку.
            logger.warning("Кэш для %s/%s без контрольной суммы — переобучаю", ticker, horizon)
            return None, None

        actual = _compute_hmac(path.read_bytes(), key)
        if not hmac.compare_digest(actual, expected):
            logger.warning(
                "Контрольная сумма файла %s не совпала с ожидаемой — возможна "
                "подмена или повреждение файла. Кэш для %s игнорируется, "
                "модель будет переобучена.", path, ticker,
            )
            return None, None

        try:
            models[horizon] = joblib.load(path)
        except Exception as e:
            # Файл прошёл проверку целостности, но всё равно не читается.
            # Самый вероятный случай — кэш записан ДРУГОЙ версией
            # scikit-learn: после обновления зависимостей формат pickle
            # может стать несовместимым. Раньше это уронило бы вызов
            # прогноза целиком (а на сервере с постоянным диском — при
            # каждом запуске, пока кэш не удалят вручную). Переобучить
            # модель дороже по времени, но полностью безопасно.
            logger.warning(
                "Не удалось загрузить модель из кэша %s (%s) — вероятно, файл "
                "записан другой версией scikit-learn. Модель будет переобучена.",
                path, e,
            )
            return None, None

    return models, meta


def cache_age_days(ticker: str) -> float | None:
    """Сколько дней назад обучалась модель. None — если кэша нет вообще."""
    _, meta = load_models(ticker)
    if meta is None:
        return None
    trained_at = parse_utc(meta["trained_at"])
    return (utc_now() - trained_at).total_seconds() / 86400
