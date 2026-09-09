"""
Настольное приложение (Tkinter) — тот же аналитический агент, что и
Telegram-бот, но без бота: локальное окно, запускается напрямую.

Запуск: python desktop_app.py

Вся аналитическая логика (сбор данных, модели, сигналы, риск-менеджмент)
не дублируется — переиспользуется через desktop_engine.py, который не
зависит от Tkinter и отдельно протестирован (tests/test_desktop_engine.py).
Этот файл отвечает только за отображение и взаимодействие с пользователем.

Долгие операции (анализ, скан списка, переобучение, бэктест) выполняются
в фоновом потоке — Tkinter не потокобезопасен для прямого обновления
виджетов из другого потока, поэтому результат передаётся через
очередь (queue.Queue) и забирается в главном потоке через after().
"""
import queue
import sys
import threading
import traceback
import tkinter as tk
from tkinter import ttk, messagebox

import db
import desktop_engine as engine
from data_fetcher import is_valid_ticker
from accuracy import evaluate_accuracy, format_accuracy_report
from backtest import run_backtest, format_backtest_report

# Семейства шрифтов подбираются под платформу. Segoe UI и Consolas
# существуют только на Windows, а Tkinter при отсутствии запрошенного
# семейства молча подставляет своё — из-за этого на macOS и Linux
# колонки прогноза цены, рассчитанные на монопропорциональный шрифт,
# теряли выравнивание, и понять причину по внешнему виду было нельзя.
if sys.platform == "darwin":
    UI_FONT, MONO_FONT = "Helvetica Neue", "Menlo"
elif sys.platform.startswith("win"):
    UI_FONT, MONO_FONT = "Segoe UI", "Consolas"
else:
    UI_FONT, MONO_FONT = "DejaVu Sans", "DejaVu Sans Mono"

# Цвета задаются двумя палитрами. Значения, подобранные под белый фон
# (тёмно-синий подзаголовок, серый приглушённый текст, бледно-розовая
# подсветка ошибок), на тёмном фоне почти сливаются с ним и читаются
# плохо — а тему пользователь выбирает в системе, приложение её не
# контролирует. Тема определяется по фактической яркости фона окна, а не
# по названию ОС: так учитывается системная настройка на macOS, Windows
# и в Linux-окружениях одинаково.
LIGHT_PALETTE = {
    "accent": "#2c5f8a", "muted": "#777777", "info": "#555555",
    "buy": "#1a8a3c", "sell": "#c0392b", "hold": "#888888",
    "warning": "#d68910", "error_bg": "#fdecea",
}

DARK_PALETTE = {
    "accent": "#6fb3e0", "muted": "#9a9a9a", "info": "#a0a0a0",
    "buy": "#4cd07d", "sell": "#ff6b5b", "hold": "#aaaaaa",
    "warning": "#f0b840", "error_bg": "#4a2320",
}


def is_dark_background(widget) -> bool:
    """
    Тёмная ли тема — по яркости фактического фона виджета. winfo_rgb
    разворачивает и символические имена цветов ОС (на macOS фон приходит
    как "systemWindowBackgroundColor"), поэтому проверка работает на всех
    платформах. Если цвет по какой-то причине не разобрать — считаем тему
    светлой: это прежнее поведение приложения.
    """
    try:
        r, g, b = widget.winfo_rgb(widget.cget("background"))
    except Exception:
        return False
    return (0.299 * r + 0.587 * g + 0.114 * b) / 65535 < 0.5


def build_tag_styles(palette: dict) -> dict:
    """Стили текстовых тегов для выбранной палитры (см. _write_segments)."""
    return {
        "header": {"font": (UI_FONT, 16, "bold"), "spacing3": 8},
        "subheader": {"font": (UI_FONT, 11, "bold"), "foreground": palette["accent"], "spacing1": 6},
        "normal": {"font": (MONO_FONT, 10)},
        "muted": {"font": (UI_FONT, 9, "italic"), "foreground": palette["muted"]},
        "buy": {"font": (UI_FONT, 13, "bold"), "foreground": palette["buy"]},
        "sell": {"font": (UI_FONT, 13, "bold"), "foreground": palette["sell"]},
        "hold": {"font": (UI_FONT, 13, "bold"), "foreground": palette["hold"]},
        "warning": {"font": (UI_FONT, 10, "bold"), "foreground": palette["warning"]},
    }


class StockAgentApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Stock Agent — аналитический помощник по акциям США")
        self.geometry("1100x720")
        self.minsize(820, 560)

        self.work_queue: queue.Queue = queue.Queue()
        self._busy = False

        # Палитру нужно выбрать ДО построения виджетов — цвета тегов и
        # таблиц задаются в момент их создания.
        self.palette = DARK_PALETTE if is_dark_background(self) else LIGHT_PALETTE
        self.tag_styles = build_tag_styles(self.palette)

        db.init_db()

        self._build_menu()
        self._build_layout()
        self._refresh_watchlist()
        self.after(100, self._poll_queue)

    def report_callback_exception(self, exc_type, exc_value, exc_traceback):
        """
        Единая обработка непредвиденных ошибок в обработчиках Tkinter.

        По умолчанию Tkinter печатает такие ошибки в консоль — но у
        собранной программы (--windowed) консоли нет, и для пользователя
        сбой выглядит как "кнопка ничего не делает", без единого следа.
        Показываем окно с текстом, который можно переслать, и дублируем
        подробности в тот же лог-файл, что и ошибки запуска.
        """
        details = "".join(traceback.format_exception(exc_type, exc_value, exc_traceback))
        print(details, file=sys.stderr)

        log_path = None
        try:
            from app_entry import _write_log

            log_path = _write_log(details)
        except Exception:
            pass

        summary = str(exc_value) or exc_type.__name__
        message = f"Непредвиденная ошибка:\n\n{summary}"
        if log_path is not None:
            message += f"\n\nПодробности записаны в файл:\n{log_path}"
        messagebox.showerror("Ошибка", message)

    # ---------- Построение интерфейса ----------

    def _build_menu(self):
        menubar = tk.Menu(self)
        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="Выход", command=self.destroy)
        menubar.add_cascade(label="Файл", menu=file_menu)

        help_menu = tk.Menu(menubar, tearoff=0)
        help_menu.add_command(label="О программе", command=self._show_about)
        menubar.add_cascade(label="Справка", menu=help_menu)
        self.config(menu=menubar)

    def _build_layout(self):
        root = ttk.Frame(self)
        root.pack(fill="both", expand=True, padx=8, pady=8)

        # --- Левая панель: watchlist ---
        left = ttk.Frame(root, width=240)
        left.pack(side="left", fill="y", padx=(0, 8))
        left.pack_propagate(False)

        ttk.Label(left, text="Список отслеживания", font=(UI_FONT, 11, "bold")).pack(anchor="w", pady=(0, 4))

        self.watchlist_box = tk.Listbox(left, exportselection=False)
        self.watchlist_box.pack(fill="both", expand=True)
        self.watchlist_box.bind("<Double-Button-1>", lambda e: self._run_analysis())

        add_row = ttk.Frame(left)
        add_row.pack(fill="x", pady=(6, 0))
        # Кнопка упаковывается ПЕРВОЙ (side="right"), иначе поле ввода с
        # expand=True забирает всю ширину панели (она фиксированная, 240 px)
        # и кнопке остаётся несколько пикселей — надпись обрезается. Так
        # кнопка сохраняет свою естественную ширину, а поле занимает остаток.
        ttk.Button(add_row, text="Добавить", command=self._add_ticker).pack(side="right", padx=(4, 0))
        self.ticker_entry = ttk.Entry(add_row)
        self.ticker_entry.pack(side="left", fill="x", expand=True)
        self.ticker_entry.bind("<Return>", lambda e: self._add_ticker())

        ttk.Button(left, text="Удалить выбранный", command=self._remove_ticker).pack(fill="x", pady=(6, 0))
        ttk.Separator(left).pack(fill="x", pady=8)
        ttk.Button(left, text="Анализ выбранного", command=self._run_analysis).pack(fill="x", pady=2)
        ttk.Button(left, text="Сканировать весь список", command=self._run_scan).pack(fill="x", pady=2)
        ttk.Button(left, text="Переобучить все модели", command=self._run_retrain_all).pack(fill="x", pady=2)
        ttk.Separator(left).pack(fill="x", pady=8)
        ttk.Button(left, text="Скрининг S&P 500 →", command=lambda: self.notebook.select(self.sp500_tab_index)).pack(fill="x", pady=2)

        # --- Правая панель: вкладки ---
        right = ttk.Frame(root)
        right.pack(side="left", fill="both", expand=True)

        self.notebook = ttk.Notebook(right)
        self.notebook.pack(fill="both", expand=True)

        self._build_analysis_tab()
        self._build_scan_tab()
        self._build_sp500_tab()
        self._build_backtest_tab()
        self._build_accuracy_tab()

        # --- Строка статуса ---
        status_row = ttk.Frame(self)
        status_row.pack(fill="x", side="bottom", padx=8, pady=(0, 6))
        self.status_var = tk.StringVar(value="Готов")
        ttk.Label(status_row, textvariable=self.status_var).pack(side="left")
        self.progress = ttk.Progressbar(status_row, mode="indeterminate", length=180)
        self.progress.pack(side="right")

    def _build_analysis_tab(self):
        tab = ttk.Frame(self.notebook)
        self.notebook.add(tab, text="Анализ")

        self.analysis_text = tk.Text(tab, wrap="word", padx=10, pady=10, state="disabled")
        self.analysis_text.pack(fill="both", expand=True)
        for tag, style in self.tag_styles.items():
            self.analysis_text.tag_configure(tag, **style)

        self._write_placeholder(
            self.analysis_text,
            "Выберите тикер слева и нажмите «Анализ выбранного»\n"
            "(или дважды кликните по тикеру в списке)."
        )

    def _build_scan_tab(self):
        tab = ttk.Frame(self.notebook)
        self.notebook.add(tab, text="Скан списка")

        columns = ("ticker", "action", "confidence", "price", "reason")
        self.scan_tree = ttk.Treeview(tab, columns=columns, show="headings")
        headers = {"ticker": "Тикер", "action": "Сигнал", "confidence": "Увер.",
                   "price": "Цена", "reason": "Причина"}
        widths = {"ticker": 80, "action": 80, "confidence": 70, "price": 90, "reason": 400}
        for col in columns:
            self.scan_tree.heading(col, text=headers[col])
            self.scan_tree.column(col, width=widths[col], anchor="w")
        self.scan_tree.pack(fill="both", expand=True, padx=8, pady=8)

        self.scan_tree.tag_configure("buy", foreground=self.palette["buy"])
        self.scan_tree.tag_configure("sell", foreground=self.palette["sell"])
        self.scan_tree.tag_configure("hold", foreground=self.palette["hold"])
        self.scan_tree.tag_configure("error", foreground=self.palette["sell"],
                                      background=self.palette["error_bg"])

    def _build_sp500_tab(self):
        tab = ttk.Frame(self.notebook)
        self.sp500_tab_index = len(self.notebook.tabs())
        self.notebook.add(tab, text="S&P 500")

        info = (
            "Полный анализ (с обучением модели) для всех ~500 компаний занял бы часы, "
            "поэтому скрининг идёт в два этапа: сначала быстрый технический отбор по всему "
            "индексу (обычно несколько минут), затем полный анализ с прогнозом и риск-уровнями "
            "только для top-N самых бычьих и top-N самых медвежьих кандидатов."
        )
        ttk.Label(tab, text=info, wraplength=760, justify="left", foreground=self.palette["info"]).pack(
            fill="x", padx=8, pady=(8, 4))

        controls = ttk.Frame(tab)
        controls.pack(fill="x", padx=8, pady=4)

        ttk.Label(controls, text="Кандидатов в шорт-лист (с каждой стороны):").pack(side="left")
        self.sp500_topn_var = tk.StringVar(value="10")
        ttk.Spinbox(controls, from_=1, to=50, width=4, textvariable=self.sp500_topn_var).pack(
            side="left", padx=(4, 12))

        self.sp500_deepdive_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(controls, text="Провести полный анализ шорт-листа",
                         variable=self.sp500_deepdive_var).pack(side="left", padx=(0, 12))

        ttk.Button(controls, text="Запустить скрининг S&P 500", command=self._run_sp500_scan).pack(side="left")

        self.sp500_warning_var = tk.StringVar(value="")
        ttk.Label(tab, textvariable=self.sp500_warning_var, foreground=self.palette["warning"]).pack(
            fill="x", padx=8, pady=(0, 4))

        paned = ttk.PanedWindow(tab, orient="vertical")
        paned.pack(fill="both", expand=True, padx=8, pady=(4, 8))

        screen_frame = ttk.Labelframe(paned, text="Быстрый технический скрининг (топ 20 / анти-топ 20)")
        paned.add(screen_frame, weight=1)
        screen_columns = ("ticker", "score", "price")
        self.sp500_screen_tree = ttk.Treeview(screen_frame, columns=screen_columns, show="headings", height=8)
        screen_headers = {"ticker": "Тикер", "score": "Тех. скор", "price": "Цена"}
        for col in screen_columns:
            self.sp500_screen_tree.heading(col, text=screen_headers[col])
            self.sp500_screen_tree.column(col, width=120, anchor="w")
        self.sp500_screen_tree.pack(fill="both", expand=True, padx=6, pady=6)
        self.sp500_screen_tree.tag_configure("buy", foreground=self.palette["buy"])
        self.sp500_screen_tree.tag_configure("sell", foreground=self.palette["sell"])

        deep_frame = ttk.Labelframe(paned, text="Полный анализ шорт-листа")
        paned.add(deep_frame, weight=1)
        deep_columns = ("ticker", "action", "confidence", "price", "reason")
        self.sp500_deep_tree = ttk.Treeview(deep_frame, columns=deep_columns, show="headings", height=8)
        deep_headers = {"ticker": "Тикер", "action": "Сигнал", "confidence": "Увер.",
                         "price": "Цена", "reason": "Причина"}
        deep_widths = {"ticker": 80, "action": 80, "confidence": 70, "price": 90, "reason": 380}
        for col in deep_columns:
            self.sp500_deep_tree.heading(col, text=deep_headers[col])
            self.sp500_deep_tree.column(col, width=deep_widths[col], anchor="w")
        self.sp500_deep_tree.pack(fill="both", expand=True, padx=6, pady=6)
        self.sp500_deep_tree.tag_configure("buy", foreground=self.palette["buy"])
        self.sp500_deep_tree.tag_configure("sell", foreground=self.palette["sell"])
        self.sp500_deep_tree.tag_configure("hold", foreground=self.palette["hold"])
        self.sp500_deep_tree.tag_configure("error", foreground=self.palette["sell"],
                                            background=self.palette["error_bg"])

    def _build_backtest_tab(self):
        tab = ttk.Frame(self.notebook)
        self.notebook.add(tab, text="Бэктест")

        controls = ttk.Frame(tab)
        controls.pack(fill="x", padx=8, pady=8)
        ttk.Label(controls, text="Тикер:").pack(side="left")
        self.backtest_ticker_entry = ttk.Entry(controls, width=12)
        self.backtest_ticker_entry.pack(side="left", padx=(4, 12))
        ttk.Button(controls, text="Запустить бэктест", command=self._run_backtest).pack(side="left")

        self.backtest_text = tk.Text(tab, wrap="word", padx=10, pady=10,
                                      font=(MONO_FONT, 10), state="disabled")
        self.backtest_text.pack(fill="both", expand=True, padx=8, pady=(0, 8))

    def _build_accuracy_tab(self):
        tab = ttk.Frame(self.notebook)
        self.notebook.add(tab, text="Честная точность")

        ttk.Button(tab, text="Обновить оценку точности", command=self._run_accuracy).pack(
            anchor="w", padx=8, pady=8)

        self.accuracy_text = tk.Text(tab, wrap="word", padx=10, pady=10,
                                      font=(MONO_FONT, 10), state="disabled")
        self.accuracy_text.pack(fill="both", expand=True, padx=8, pady=(0, 8))

    # ---------- Вспомогательные методы отображения ----------

    def _write_placeholder(self, widget: tk.Text, message: str):
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("end", message, "muted")
        widget.configure(state="disabled")

    def _write_segments(self, widget: tk.Text, segments: list[tuple[str, str]]):
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        for text, tag in segments:
            widget.insert("end", text, tag)
        widget.configure(state="disabled")

    def _write_plain(self, widget: tk.Text, text: str):
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("end", text)
        widget.configure(state="disabled")

    def _show_about(self):
        messagebox.showinfo(
            "О программе",
            "Stock Agent — аналитический помощник по акциям США.\n\n"
            "Анализирует котировки, фундаментал, новостной фон и рыночный "
            "контекст, даёт рекомендации BUY/SELL/HOLD с ценовыми "
            "ориентирами и уровнями риска.\n\n"
            "Модели переобучаются автоматически при устаревании кэша "
            "(> 7 дней) — это и есть самообучение агента.\n\n"
            "Не является индивидуальной инвестиционной рекомендацией."
        )

    # ---------- Watchlist ----------

    def _refresh_watchlist(self):
        self.watchlist_box.delete(0, "end")
        for ticker in db.get_watchlist(engine.LOCAL_USER_ID):
            self.watchlist_box.insert("end", ticker)

    def _selected_ticker(self) -> str | None:
        sel = self.watchlist_box.curselection()
        if not sel:
            return None
        return self.watchlist_box.get(sel[0])

    def _add_ticker(self):
        ticker = self.ticker_entry.get().strip().upper()
        if not ticker:
            return
        self._set_busy(f"Проверяю {ticker}...")
        self._run_in_background(
            task=lambda: self._add_ticker_task(ticker),
            on_done=self._on_add_ticker_done,
        )

    def _add_ticker_task(self, ticker: str) -> dict:
        if not is_valid_ticker(ticker):
            return {"ok": False, "ticker": ticker, "message": f"Тикер {ticker} не найден"}
        added = db.add_ticker(engine.LOCAL_USER_ID, ticker)
        if not added:
            return {"ok": False, "ticker": ticker, "message": f"{ticker} уже в списке"}
        return {"ok": True, "ticker": ticker, "message": f"{ticker} добавлен"}

    def _on_add_ticker_done(self, result, error):
        self._set_idle()
        if error:
            messagebox.showerror("Ошибка", str(error))
            return
        if result["ok"]:
            self.ticker_entry.delete(0, "end")
            self._refresh_watchlist()
        else:
            messagebox.showwarning("Не удалось добавить", result["message"])

    def _remove_ticker(self):
        ticker = self._selected_ticker()
        if not ticker:
            messagebox.showinfo("Выберите тикер", "Сначала выберите тикер в списке слева")
            return
        if messagebox.askyesno("Подтверждение", f"Удалить {ticker} из списка отслеживания?"):
            db.remove_ticker(engine.LOCAL_USER_ID, ticker)
            self._refresh_watchlist()

    # ---------- Анализ одного тикера ----------

    def _run_analysis(self):
        ticker = self._selected_ticker()
        if not ticker:
            messagebox.showinfo("Выберите тикер", "Сначала выберите тикер в списке слева")
            return
        self.notebook.select(0)
        self._write_placeholder(self.analysis_text, f"Анализирую {ticker}, это может занять до минуты...")
        self._set_busy(f"Анализирую {ticker}...")
        self._run_in_background(
            task=lambda: engine.build_full_analysis(ticker),
            on_done=self._on_analysis_done,
        )

    def _on_analysis_done(self, result, error):
        self._set_idle()
        if error:
            self._write_placeholder(self.analysis_text, f"Ошибка анализа: {error}")
            return
        segments = engine.render_analysis_segments(result)
        self._write_segments(self.analysis_text, segments)

    # ---------- Скан всего списка ----------

    def _run_scan(self):
        if not db.get_watchlist(engine.LOCAL_USER_ID):
            messagebox.showinfo("Список пуст", "Сначала добавьте хотя бы один тикер")
            return
        self.notebook.select(1)
        self.scan_tree.delete(*self.scan_tree.get_children())
        self._set_busy("Сканирую список...")

        def progress_cb(i, total, ticker):
            self.work_queue.put(("progress", f"Сканирую {ticker} ({i + 1}/{total})..."))

        self._run_in_background(
            task=lambda: engine.scan_watchlist(progress_callback=progress_cb),
            on_done=self._on_scan_done,
        )

    def _on_scan_done(self, results, error):
        self._set_idle()
        if error:
            messagebox.showerror("Ошибка сканирования", str(error))
            return
        for r in results:
            if r.get("error"):
                self.scan_tree.insert("", "end", values=(r["ticker"], "ОШИБКА", "", "", r["error"]), tags=("error",))
                continue
            tag = {"BUY": "buy", "SELL": "sell", "HOLD": "hold"}.get(r["action"], "")
            self.scan_tree.insert("", "end", values=(
                r["ticker"], r["action"], f"{r['confidence']:.0%}",
                f"${r['price']:.2f}", r["reason"],
            ), tags=(tag,))

    # ---------- Скрининг S&P 500 ----------

    def _run_sp500_scan(self):
        try:
            top_n = int(self.sp500_topn_var.get())
            if top_n < 1:
                raise ValueError
        except ValueError:
            messagebox.showerror("Некорректное значение", "Число кандидатов должно быть положительным целым")
            return

        deep_dive = self.sp500_deepdive_var.get()

        self.sp500_screen_tree.delete(*self.sp500_screen_tree.get_children())
        self.sp500_deep_tree.delete(*self.sp500_deep_tree.get_children())
        self.sp500_warning_var.set("")
        self._set_busy("Загружаю список S&P 500...")

        def progress_cb(i, total, ticker):
            self.work_queue.put(("progress", f"{ticker} ({i + 1}/{total})"))

        self._run_in_background(
            task=lambda: engine.scan_sp500(top_n=top_n, deep_dive=deep_dive, progress_callback=progress_cb),
            on_done=self._on_sp500_scan_done,
        )

    def _on_sp500_scan_done(self, result, error):
        self._set_idle()
        if error:
            messagebox.showerror("Ошибка скрининга S&P 500", str(error))
            return

        if result["used_fallback_tickers"]:
            self.sp500_warning_var.set(
                f"⚠ Не удалось загрузить актуальный список S&P 500 (нет соединения или "
                f"источник недоступен) — использован сокращённый резервный список из "
                f"{result['universe_size']} крупнейших компаний, это НЕ полный индекс."
            )
        else:
            self.sp500_warning_var.set(
                f"Загружено {result['universe_size']} тикеров индекса, "
                f"успешно проанализировано технически: {result['screened_size']}"
            )

        screened = result["screened"]
        top_display = screened[:20]
        bottom_display = screened[-20:] if len(screened) > 20 else []
        for r in top_display:
            self.sp500_screen_tree.insert("", "end", values=(
                r["ticker"], f"{r['score']:+.2f}", f"${r['price']:.2f}",
            ), tags=("buy",))
        for r in bottom_display:
            self.sp500_screen_tree.insert("", "end", values=(
                r["ticker"], f"{r['score']:+.2f}", f"${r['price']:.2f}",
            ), tags=("sell",))

        if result["shortlist_analysis"] is None:
            return

        for r in result["shortlist_analysis"]:
            if r.get("error"):
                self.sp500_deep_tree.insert("", "end", values=(r["ticker"], "ОШИБКА", "", "", r["error"]), tags=("error",))
                continue
            tag = {"BUY": "buy", "SELL": "sell", "HOLD": "hold"}.get(r["action"], "")
            self.sp500_deep_tree.insert("", "end", values=(
                r["ticker"], r["action"], f"{r['confidence']:.0%}",
                f"${r['price']:.2f}", r["reason"],
            ), tags=(tag,))

    # ---------- Переобучение всех моделей ----------

    def _run_retrain_all(self):
        if not db.get_watchlist(engine.LOCAL_USER_ID):
            messagebox.showinfo("Список пуст", "Сначала добавьте хотя бы один тикер")
            return
        if not messagebox.askyesno(
            "Переобучение",
            "Переобучить модели для всех тикеров списка сейчас?\n"
            "Обычно это происходит автоматически раз в неделю, при устаревании кэша."
        ):
            return
        self._set_busy("Переобучаю модели...")

        def progress_cb(i, total, ticker):
            self.work_queue.put(("progress", f"Переобучаю {ticker} ({i + 1}/{total})..."))

        self._run_in_background(
            task=lambda: engine.retrain_all(progress_callback=progress_cb),
            on_done=self._on_retrain_done,
        )

    def _on_retrain_done(self, results, error):
        self._set_idle()
        if error:
            messagebox.showerror("Ошибка переобучения", str(error))
            return
        failed = [r for r in results if not r[1]]
        if failed:
            details = "\n".join(f"{t}: {msg}" for t, _, msg in failed)
            messagebox.showwarning("Переобучение завершено с ошибками", details)
        else:
            messagebox.showinfo("Готово", f"Переобучено моделей: {len(results)}")

    # ---------- Бэктест ----------

    def _run_backtest(self):
        ticker = self.backtest_ticker_entry.get().strip().upper()
        if not ticker:
            messagebox.showinfo("Введите тикер", "Укажите тикер для бэктеста")
            return
        self._write_plain(self.backtest_text,
                           f"Считаю бэктест для {ticker} за ~3 года — это переобучение "
                           f"модели много раз подряд, может занять пару минут...")
        self._set_busy(f"Бэктест {ticker}...")
        self._run_in_background(
            task=lambda: format_backtest_report(run_backtest(ticker, rebalance_days=21)),
            on_done=self._on_backtest_done,
        )

    def _on_backtest_done(self, result, error):
        self._set_idle()
        if error:
            self._write_plain(self.backtest_text, f"Ошибка: {error}")
            return
        self._write_plain(self.backtest_text, result)

    # ---------- Честная точность ----------

    def _run_accuracy(self):
        self._write_plain(self.accuracy_text, "Сверяю прошлые сигналы с реальными ценами...")
        self._set_busy("Считаю точность...")
        self._run_in_background(
            task=lambda: format_accuracy_report(evaluate_accuracy(db.get_all_signals(engine.LOCAL_USER_ID))),
            on_done=self._on_accuracy_done,
        )

    def _on_accuracy_done(self, result, error):
        self._set_idle()
        if error:
            self._write_plain(self.accuracy_text, f"Ошибка: {error}")
            return
        self._write_plain(self.accuracy_text, result)

    # ---------- Инфраструктура фоновых задач ----------

    def _set_busy(self, message: str):
        self._busy = True
        self.status_var.set(message)
        self.progress.start(12)

    def _set_idle(self):
        self._busy = False
        self.status_var.set("Готов")
        self.progress.stop()

    def _run_in_background(self, task, on_done):
        """
        Запускает task() в отдельном потоке и кладёт результат в очередь.
        Tkinter-виджеты нельзя трогать из фонового потока напрямую — поэтому
        on_done вызывается позже, в главном потоке, через _poll_queue.
        """
        def worker():
            try:
                result = task()
                self.work_queue.put(("done", (result, None, on_done)))
            except Exception as e:
                self.work_queue.put(("done", (None, e, on_done)))

        threading.Thread(target=worker, daemon=True).start()

    def _poll_queue(self):
        try:
            while True:
                kind, payload = self.work_queue.get_nowait()
                if kind == "progress":
                    self.status_var.set(payload)
                elif kind == "done":
                    result, error, on_done = payload
                    on_done(result, error)
        except queue.Empty:
            pass
        self.after(100, self._poll_queue)


def main():
    app = StockAgentApp()
    app.mainloop()


if __name__ == "__main__":
    main()
