"""
Собирает автономный исполняемый файл настольного приложения — .exe на
Windows, обычный бинарник на macOS/Linux. Конечному пользователю
Python устанавливать не нужно.

ВАЖНО: PyInstaller НЕ кросс-компилирует. Собирать нужно на той же ОС,
для которой нужен результат — хотите .exe для Windows, запускайте этот
скрипт на Windows (не в WSL/Linux/Mac).

Запуск:
    pip install -r requirements-desktop.txt -r requirements-build.txt
    python build_exe.py              # один файл (портативная версия)
    python build_exe.py --onedir     # папкой (из неё собирается установщик)

Результат:
    без --onedir: dist/StockAgent(.exe) — один файл, копируется и запускается
    с --onedir:   dist/StockAgent/ — папка, внутри StockAgent(.exe)
"""
import argparse
import os
import sys

import PyInstaller.__main__


def _force_utf8_output():
    """
    Windows запускает Python с кодировкой консоли (cp1252 на
    англоязычной системе, cp866 в cmd.exe), и любой print() с кириллицей
    там падает с UnicodeEncodeError — сборка обрывалась на первой же
    строке вывода, ещё до запуска PyInstaller. На GitHub Actions это
    воспроизводится всегда.

    Переключаем поток вывода на UTF-8 с errors="replace": лог сборки в
    Actions читается корректно, а в редкой консоли, которая UTF-8 не
    понимает, в худшем случае будут знаки вопроса вместо букв — но
    сборка не упадёт. Обёрнуто в try/except: в отдельных окружениях
    (перенаправленный или подменённый stdout) reconfigure недоступен, и
    это не повод останавливать сборку.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


_force_utf8_output()

# Пакеты, для которых PyInstaller часто не видит все нужные подмодули
# автоматически: скомпилированные C-расширения sklearn/scipy, ленивые
# импорты pandas. Явно просим собрать всё целиком — это увеличивает
# размер и время сборки, но резко снижает риск ошибки
# "ModuleNotFoundError" при первом запуске готовой программы.
COLLECT_ALL = ["sklearn", "scipy", "pandas"]

# Модули, которые в сборке настольного приложения НЕ нужны.
#
# torch и transformers — опциональный слой FinBERT. Если они установлены
# в окружении сборки, PyInstaller утащит их внутрь и раздует результат
# примерно на 2 ГБ. Без них news_sentiment.py работает штатно: он ловит
# ImportError и переходит на нейтральный sentiment.
#
# matplotlib нужен только CLI-команде `python backtest.py --save-chart`;
# в окне программы графики не рисуются, вкладка "Бэктест" показывает
# текстовый отчёт.
#
# telegram (python-telegram-bot) относится только к telegram_bot.py и в
# настольную версию не входит вовсе.
EXCLUDES = ["torch", "transformers", "matplotlib", "telegram"]


def main():
    parser = argparse.ArgumentParser(description="Сборка настольного приложения")
    parser.add_argument(
        "--onedir", action="store_true",
        help="собрать папкой вместо одного файла. Так собирается версия для "
             "установщика: программа стартует заметно быстрее (не нужно каждый "
             "раз распаковывать себя во временную папку) и реже вызывает ложные "
             "срабатывания антивирусов",
    )
    build_args = parser.parse_args()

    args = [
        "desktop_app.py",
        "--name=StockAgent",
        "--onedir" if build_args.onedir else "--onefile",
        "--windowed",       # без фонового консольного окна
        "--clean",
        "--noconfirm",
    ]

    for pkg in COLLECT_ALL:
        args.append(f"--collect-all={pkg}")
    for module in EXCLUDES:
        args.append(f"--exclude-module={module}")

    # tkinter обычно подхватывается автоматически по факту импорта в
    # desktop_app.py, но на нестандартных сборках Python (pyenv/conda)
    # иногда требуется явное указание
    args.append("--hidden-import=tkinter")

    # Опциональная иконка — положите icon.ico (Windows) рядом со скриптом
    if sys.platform == "win32" and os.path.exists("icon.ico"):
        args.append("--icon=icon.ico")

    print("Запускаю PyInstaller со следующими параметрами:")
    print(" ".join(args))
    print()

    PyInstaller.__main__.run(args)

    exe_name = "StockAgent.exe" if sys.platform == "win32" else "StockAgent"
    result = f"dist/StockAgent/{exe_name}" if build_args.onedir else f"dist/{exe_name}"
    print()
    print(f"Готово: {result}")
    print(
        "\nГде программа хранит данные: список отслеживания (watchlist.db) и "
        "кэш обученных моделей попадают в пользовательскую папку данных "
        "(на Windows — %LOCALAPPDATA%\\StockAgent), а не рядом с программой. "
        "Так они переживают переустановку и не теряются при удалении папки "
        "с программой. Исключение — портативный сценарий: если рядом с "
        "исполняемым файлом уже лежит watchlist.db, программа продолжит "
        "работать с ним."
    )
    if not build_args.onedir:
        print(
            "\nЕсли антивирус блокирует получившийся файл (частая ложная "
            "тревога у однофайловых PyInstaller-сборок) — пересоберите с "
            "флагом --onedir: результат будет папкой вместо одного файла, "
            "но реже триггерит антивирусы."
        )


if __name__ == "__main__":
    main()
