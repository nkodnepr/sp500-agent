"""
Точка входа собранной программы (StockAgent.exe).

ЗАЧЕМ ОТДЕЛЬНЫЙ ФАЙЛ: сборка делается с флагом --windowed, то есть без
консольного окна. Если программа падает на старте — не загрузилась
библиотека, недоступна папка данных, повреждён файл — пользователь не
видит РОВНО НИЧЕГО: двойной клик, и тишина. Отладить такое по переписке
невозможно, а именно так выглядит жалоба "не запускается".

Здесь запуск обёрнут в перехват любых ошибок: текст пишется в лог-файл
рядом с данными программы и показывается окном, которое можно
сфотографировать и переслать. Импорт desktop_app тоже находится внутри
try — ошибки импорта иначе не поймать, а у собранных программ это самый
частый класс сбоев (например, конфликт версий numpy даёт
"DLL load failed while importing _multiarray_umath" именно на импорте).

Файл сознательно НЕ импортирует ничего из проекта на верхнем уровне и не
зависит от сторонних пакетов: он должен сработать даже тогда, когда
сломано всё остальное.
"""
import os
import sys
import traceback
from datetime import datetime
from pathlib import Path

LOG_NAME = "startup-error.log"


def _data_dir() -> Path:
    """
    Повторяет логику config._default_data_dir, но без импорта config:
    именно config может оказаться тем, что не загрузилось.
    """
    if sys.platform == "win32":
        base = os.getenv("LOCALAPPDATA") or Path.home() / "AppData" / "Local"
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = os.getenv("XDG_DATA_HOME") or Path.home() / ".local" / "share"
    return Path(base) / "StockAgent"


def _write_log(details: str):
    """Сохраняет полный текст ошибки. Возвращает путь к файлу или None."""
    try:
        directory = _data_dir()
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / LOG_NAME
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        path.write_text(f"Stock Agent — ошибка запуска\n{stamp}\n\n{details}", encoding="utf-8")
        return path
    except Exception:
        # Не смогли записать лог (нет прав, диск полон) — это не повод
        # промолчать: окно с ошибкой пользователь всё равно увидит.
        return None


def _build_message(details: str, log_path) -> str:
    lines = [line for line in details.strip().splitlines() if line.strip()]
    summary = lines[-1] if lines else "Неизвестная ошибка"

    message = f"Не удалось запустить Stock Agent.\n\n{summary}\n\n"
    if log_path is not None:
        message += f"Подробности сохранены в файл:\n{log_path}\n\n"
    message += "Пришлите этот текст (или файл) тому, кто передал вам программу."
    return message


def _show_error(message: str) -> None:
    """
    Показывает ошибку окном. Три попытки подряд, потому что сломаться
    может и сам механизм показа.
    """
    try:
        import tkinter as tk
        from tkinter import messagebox

        root = tk.Tk()
        root.withdraw()
        messagebox.showerror("Stock Agent — ошибка запуска", message)
        root.destroy()
        return
    except Exception:
        pass

    if sys.platform == "win32":
        # Системное окно Windows — на случай, если не работает как раз tkinter
        try:
            import ctypes

            ctypes.windll.user32.MessageBoxW(None, message, "Stock Agent — ошибка запуска", 0x10)
            return
        except Exception:
            pass

    # Последняя попытка: консоль. В сборке с --windowed её обычно нет,
    # но при запуске из терминала текст будет виден.
    print(message, file=sys.stderr)


def main() -> int:
    try:
        from desktop_app import main as run_app

        run_app()
        return 0
    except SystemExit:
        raise
    except BaseException:
        details = traceback.format_exc()
        _show_error(_build_message(details, _write_log(details)))
        return 1


if __name__ == "__main__":
    sys.exit(main())
