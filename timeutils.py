"""
Единая работа со временем: весь проект хранит и сравнивает моменты
времени в UTC.

ЗАЧЕМ ОТДЕЛЬНЫЙ МОДУЛЬ: `datetime.utcnow()` объявлен устаревшим и будет
удалён из Python, но прямая замена на `datetime.now(timezone.utc)` сама
по себе ломает сравнения. SQLite пишет `created_at` через
`CURRENT_TIMESTAMP` как naive-строку без смещения ("2026-09-08 14:03:02",
время в UTC), а вычитать naive-дату из timezone-aware "сейчас" нельзя —
Python бросает TypeError. Та же проблема с кэшем моделей: метки
`trained_at`, записанные прошлой версией кода, лежат на диске в
naive-формате, и после обновления их всё равно нужно уметь читать.

Поэтому здесь два примитива:
  utc_now()   — момент "сейчас" как timezone-aware UTC;
  parse_utc() — разбор метки времени, при котором naive-значение
                трактуется как UTC (именно в UTC его и записывали
                и SQLite, и прошлые версии model_store).

Так сравнения всегда идут между aware-датами, а старые данные на диске
и в БД продолжают читаться без миграции их формата.
"""
from datetime import datetime, timezone


def utc_now() -> datetime:
    """Текущий момент в UTC (timezone-aware)."""
    return datetime.now(timezone.utc)


def parse_utc(value: str | datetime) -> datetime:
    """
    Приводит метку времени к timezone-aware UTC.

    Принимает как ISO-строку (в том числе формат SQLite
    "YYYY-MM-DD HH:MM:SS"), так и готовый datetime. Значение без
    указанной зоны считается записанным в UTC — это соответствует
    тому, как время пишут db.py (CURRENT_TIMESTAMP) и model_store.py.
    """
    dt = value if isinstance(value, datetime) else datetime.fromisoformat(value)
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
