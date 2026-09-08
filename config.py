"""
Конфигурация проекта.
Все секреты берутся из переменных окружения (.env файл), не хардкодятся в коде.
"""
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


APP_NAME = "StockAgent"


def _user_data_dir() -> Path:
    """
    Стандартная пользовательская папка данных для текущей ОС. Именно
    сюда попадают БД и кэш моделей у УСТАНОВЛЕННОЙ версии программы.
    """
    if sys.platform == "win32":
        base = os.getenv("LOCALAPPDATA") or Path.home() / "AppData" / "Local"
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = os.getenv("XDG_DATA_HOME") or Path.home() / ".local" / "share"
    return Path(base) / APP_NAME


def _default_data_dir() -> Path:
    """
    Куда по умолчанию класть БД и кэш моделей, если пути не заданы явно
    через переменные окружения.

    В режиме разработки (обычный `python desktop_app.py`) — папка
    проекта, как и раньше.

    В собранном виде (PyInstaller выставляет sys.frozen=True) класть
    файлы внутрь sys._MEIPASS нельзя ни в коем случае: это временная
    папка распаковки, она стирается при выходе, и программа забывала бы
    всё после каждого закрытия. Остаются два варианта:

    1. Рядом с исполняемым файлом — так работала портативная сборка.
       Если данные там уже есть, продолжаем писать туда же: иначе
       обновление программы выглядело бы для пользователя как потеря
       списка отслеживания и всех обученных моделей.
    2. В пользовательской папке данных — вариант по умолчанию для новых
       запусков. Установленная копия лежит в каталоге программ, который
       может быть недоступен для записи, а при удалении программы
       стирается целиком вместе со всем содержимым. Данные пользователя
       там держать нельзя.
    """
    if not getattr(sys, "frozen", False):
        return Path(__file__).resolve().parent

    exe_dir = Path(sys.executable).resolve().parent
    if (exe_dir / "watchlist.db").exists() or (exe_dir / "models_cache").is_dir():
        return exe_dir

    data_dir = _user_data_dir()
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir


_DATA_DIR = _default_data_dir()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")

# Список Telegram user_id, которым разрешено пользоваться ботом —
# через запятую, например "123456789,987654321". Свой user_id можно
# узнать, написав боту @userinfobot в Telegram.
#
# Если оставить пустым — бот отвечает ЛЮБОМУ пользователю Telegram,
# который его найдёт (по имени или случайно). Это не утечка чужих
# данных (у каждого свой изолированный watchlist в БД), но позволяет
# посторонним расходовать вычислительные ресурсы бота (обучение
# моделей, /backtest) — а на платных тарифах хостинга это ещё и
# реальные деньги. Настоятельно рекомендуется задать этот список для
# личного бота.
_raw_allowed_ids = os.getenv("ALLOWED_TELEGRAM_USER_IDS", "")
ALLOWED_TELEGRAM_USER_IDS = {
    int(uid.strip()) for uid in _raw_allowed_ids.split(",") if uid.strip().lstrip("-").isdigit()
}

# Путь к файлу БД (SQLite)
DB_PATH = os.getenv("DB_PATH", str(_DATA_DIR / "watchlist.db"))

# Папка для кэша обученных моделей (см. model_store.py). На Render/облаке
# с постоянным диском укажите путь внутри смонтированного диска
# (например /data/models_cache), иначе кэш будет стираться при передеплое.
MODELS_CACHE_DIR = os.getenv("MODELS_CACHE_DIR", str(_DATA_DIR / "models_cache"))

# Время ежедневного анализа (час, минута) — по времени сервера
DAILY_ANALYSIS_HOUR = int(os.getenv("DAILY_ANALYSIS_HOUR", "9"))
DAILY_ANALYSIS_MINUTE = int(os.getenv("DAILY_ANALYSIS_MINUTE", "30"))

# Минимальная "уверенность" модели, чтобы прислать сигнал (0.0 - 1.0)
CONFIDENCE_THRESHOLD = float(os.getenv("CONFIDENCE_THRESHOLD", "0.6"))

# Минимальный прогнозируемый % движения, чтобы считать сигнал значимым
SIGNAL_THRESHOLD_PCT = float(os.getenv("SIGNAL_THRESHOLD_PCT", "0.03"))  # 3%

# Сколько лет исторических данных загружать для обучения модели
HISTORY_YEARS = int(os.getenv("HISTORY_YEARS", "5"))

