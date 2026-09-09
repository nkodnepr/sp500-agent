#!/bin/bash
# ============================================================
#  Stock Agent — запуск настольного приложения (macOS / Linux)
#
#  На macOS достаточно дважды кликнуть по этому файлу в Finder.
#  На Linux запустите его из терминала: bash run_macos.command
#
#  Первый запуск создаёт виртуальное окружение и ставит
#  зависимости (несколько минут, нужен интернет). Последующие
#  запуски — сразу.
#
#  Windows-аналог этого файла — run_windows.bat
# ============================================================
set -u
cd "$(dirname "$0")" || exit 1
echo "Рабочая папка: $(pwd)"
echo

VENV_DIR="venv"

if [ ! -f "desktop_app.py" ]; then
    echo "[ОШИБКА] desktop_app.py не найден рядом с этим файлом."
    echo "Скрипт должен лежать в той же папке, что и файлы проекта."
    read -r -p "Нажмите Enter, чтобы закрыть..."
    exit 1
fi

# --- Ищем Python 3 ---
# Сначала пробуем ровно ту версию, что закреплена в runtime.txt (её же
# используют CI и Render), и только потом — любой доступный python3.
# Иначе на машине с более новым системным Python окружение создалось бы
# на непроверенной версии, где для зафиксированных pandas/numpy может
# не быть готовых wheels.
PINNED_MM=""
if [ -f "runtime.txt" ]; then
    PINNED_MM=$(sed -n 's/^python-\([0-9]*\.[0-9]*\).*/\1/p' runtime.txt)
fi

PYTHON_CMD=""
for candidate in ${PINNED_MM:+"python$PINNED_MM"} python3 python; do
    if command -v "$candidate" >/dev/null 2>&1; then
        PYTHON_CMD="$candidate"
        break
    fi
done

if [ -z "$PYTHON_CMD" ]; then
    echo "[ОШИБКА] Python 3 не найден."
    echo "Установите его с https://www.python.org/downloads/ (macOS)"
    echo "или через пакетный менеджер системы (Linux), затем запустите файл снова."
    read -r -p "Нажмите Enter, чтобы закрыть..."
    exit 1
fi
echo "Python: $PYTHON_CMD ($($PYTHON_CMD --version 2>&1))"
echo

# --- Создаём окружение при первом запуске ---
if [ ! -x "$VENV_DIR/bin/python" ]; then
    ACTUAL_MM=$("$PYTHON_CMD" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
    if [ -n "$PINNED_MM" ] && [ "$ACTUAL_MM" != "$PINNED_MM" ]; then
        echo "[ВНИМАНИЕ] Проект проверен на Python $PINNED_MM, а найден только $ACTUAL_MM."
        echo "Продолжаю, но если установка зависимостей упадёт — поставьте Python $PINNED_MM."
        echo
    fi
    echo "Первый запуск — создаю виртуальное окружение..."
    if ! "$PYTHON_CMD" -m venv "$VENV_DIR"; then
        echo "[ОШИБКА] Не удалось создать виртуальное окружение."
        read -r -p "Нажмите Enter, чтобы закрыть..."
        exit 1
    fi
fi

VENV_PY="$VENV_DIR/bin/python"

# --- Ставим зависимости, если их действительно нет ---
# Проверяем реальным импортом, а не файлом-маркером: если прошлая
# установка оборвалась на середине, маркер всё равно утверждал бы, что всё
# на месте, и программа падала бы при запуске. Проверка импортом
# самозалечивающаяся — она увидит нехватку и доустановит.
if ! "$VENV_PY" -c "import numpy, pandas, sklearn, yfinance" >/dev/null 2>&1; then
    echo "Устанавливаю зависимости — это может занять несколько минут..."
    echo
    "$VENV_PY" -m pip install --upgrade pip
    if ! "$VENV_PY" -m pip install -r requirements-desktop.txt; then
        echo
        echo "[ОШИБКА] Не удалось установить зависимости."
        echo "Проверьте интернет-соединение и запустите файл снова."
        read -r -p "Нажмите Enter, чтобы закрыть..."
        exit 1
    fi
    echo "Зависимости установлены."
    echo
fi

# --- Проверяем tkinter: он не ставится через pip ---
if ! "$VENV_PY" -c "import tkinter" >/dev/null 2>&1; then
    echo "[ОШИБКА] Модуль tkinter недоступен — без него окно не откроется."
    echo "Он входит в стандартную библиотеку, но в некоторых сборках Python"
    echo "поставляется отдельным системным пакетом:"
    echo
    PY_MM=$("$VENV_PY" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
    echo "  macOS + Homebrew:  brew install python-tk@$PY_MM"
    echo "  Ubuntu/Debian:     sudo apt install python3-tk"
    echo "  Fedora:            sudo dnf install python3-tkinter"
    echo "  Arch:              sudo pacman -S tk"
    echo
    echo "(либо установите Python с python.org — там tkinter уже включён)"
    read -r -p "Нажмите Enter, чтобы закрыть..."
    exit 1
fi

echo "Запускаю Stock Agent..."
echo
if ! "$VENV_PY" desktop_app.py; then
    echo
    echo "[ОШИБКА] Программа завершилась с ошибкой — подробности выше."
    read -r -p "Нажмите Enter, чтобы закрыть..."
fi
