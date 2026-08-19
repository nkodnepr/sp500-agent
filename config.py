"""
Конфигурация проекта.
Все секреты берутся из переменных окружения (.env файл), не хардкодятся в коде.
"""
import os
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")

# Путь к файлу БД (SQLite)
DB_PATH = os.getenv("DB_PATH", "watchlist.db")

# Папка для кэша обученных моделей (см. model_store.py). На Render/облаке
# с постоянным диском укажите путь внутри смонтированного диска
# (например /data/models_cache), иначе кэш будет стираться при передеплое.
MODELS_CACHE_DIR = os.getenv("MODELS_CACHE_DIR", "models_cache")

# Время ежедневного анализа (час, минута) — по времени сервера
DAILY_ANALYSIS_HOUR = int(os.getenv("DAILY_ANALYSIS_HOUR", "9"))
DAILY_ANALYSIS_MINUTE = int(os.getenv("DAILY_ANALYSIS_MINUTE", "30"))

# Минимальная "уверенность" модели, чтобы прислать сигнал (0.0 - 1.0)
CONFIDENCE_THRESHOLD = float(os.getenv("CONFIDENCE_THRESHOLD", "0.6"))

# Минимальный прогнозируемый % движения, чтобы считать сигнал значимым
SIGNAL_THRESHOLD_PCT = float(os.getenv("SIGNAL_THRESHOLD_PCT", "0.03"))  # 3%

# Сколько лет исторических данных загружать для обучения модели
HISTORY_YEARS = int(os.getenv("HISTORY_YEARS", "5"))
