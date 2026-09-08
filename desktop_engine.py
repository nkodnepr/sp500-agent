"""
Логика настольного приложения, отделённая от Tkinter-интерфейса.

Не зависит от python-telegram-bot и никаких GUI-библиотек — переиспользует
весь тот же аналитический движок, что и Telegram-бот (features.py,
model.py, signal_logic.py, backtest.py, accuracy.py и т.д.), просто без
привязки к чат-интерфейсу. Отделение от GUI сделано специально: эту логику
можно тестировать напрямую (см. tests/test_desktop_engine.py), не запуская
окно — Tkinter-слой (desktop_app.py) лишь отображает то, что здесь посчитано.
"""
import db
import earnings as earnings_module
import fundamentals as fundamentals_module
import market_context as market_context_module
import news_sentiment as news_sentiment_module
import signal_logic as signal_logic_module
import sp500_screener as sp500_screener_module
import sp500_universe as sp500_universe_module
from model import forecast_ticker, HORIZONS
from risk_management import suggest_position_size, RISK_PER_TRADE_PCT

# Десктоп-версия однопользовательская — нет чата/аккаунта, поэтому вместо
# telegram user_id используется фиксированный локальный ID. БД (db.py)
# переиспользуется без изменений — таблицы уже спроектированы с user_id,
# просто здесь он всегда один и тот же.
LOCAL_USER_ID = 1

HORIZON_LABELS = [("1w", "1 неделя"), ("2w", "2 недели"), ("1m", "1 месяц"), ("3m", "3 месяца")]
DIRECTION_ARROW = {1: "▲", -1: "▼", 0: "→"}
ACTION_LABELS = {"BUY": "ПОКУПАТЬ", "SELL": "ПРОДАВАТЬ", "HOLD": "ДЕРЖАТЬ"}


def build_full_analysis(ticker: str, force_retrain: bool = False,
                         portfolio_value: float = 10000.0) -> dict:
    """
    Собирает полный аналитический контекст по тикеру: прогноз, sentiment,
    режим рынка, отчётность, итоговый сигнал с риск-уровнями.

    Идентично по смыслу _build_full_analysis из telegram_bot.py — тот же
    набор шагов, но без зависимости от python-telegram-bot, чтобы desktop
    можно было использовать без установки бот-фреймворка.
    """
    forecast = forecast_ticker(ticker, force_retrain=force_retrain)
    sentiment = news_sentiment_module.get_sentiment_score(ticker)
    market = market_context_module.get_market_regime()
    earnings = earnings_module.check_earnings_within_horizons(ticker, HORIZONS)

    signal = signal_logic_module.generate_signal(forecast, sentiment=sentiment, market=market, earnings=earnings)

    position_size = None
    main_horizon = forecast["horizons"].get("1m")
    if signal["action"] in ("BUY", "SELL") and main_horizon and main_horizon.get("risk_levels"):
        rl = main_horizon["risk_levels"]
        position_size = suggest_position_size(
            forecast["current_price"], rl["stop_loss"], portfolio_value=portfolio_value,
        )
        position_size["risk_pct_label"] = f"{RISK_PER_TRADE_PCT:.0%}"

    fundamentals = fundamentals_module.latest_fundamentals_snapshot(ticker)

    return {
        "forecast": forecast,
        "signal": signal,
        "fundamentals": fundamentals,
        "position_size": position_size,
    }


def render_analysis_segments(analysis: dict) -> list[tuple[str, str]]:
    """
    Превращает результат build_full_analysis в список (текст, тег) —
    без обращения к Tkinter. GUI-слой вставляет эти сегменты в Text-виджет,
    раскрашивая по тегу через tag_configure. Доступные теги:
    header, subheader, normal, buy, sell, hold, warning, muted.
    """
    forecast = analysis["forecast"]
    signal = analysis["signal"]
    fundamentals = analysis["fundamentals"]
    position_size = analysis["position_size"]

    ticker = forecast["ticker"]
    price = forecast["current_price"]
    h = forecast["horizons"]

    seg: list[tuple[str, str]] = []
    seg.append((f"{ticker}\n", "header"))
    seg.append((f"Текущая цена: ${price:.2f}\n", "normal"))

    cache_note = "модели взяты из кэша" if forecast.get("models_from_cache") else "модели обучены только что"
    seg.append((f"({cache_note})\n\n", "muted"))

    seg.append(("ПРОГНОЗ ЦЕНЫ\n", "subheader"))
    for name, label in HORIZON_LABELS:
        data = h.get(name, {})
        if "error" in data:
            seg.append((f"  {label}: нет данных\n", "muted"))
            continue
        arrow = DIRECTION_ARROW.get(data["direction"], "→")
        low, high = data["price_range"]
        seg.append((
            f"  {label}: {arrow} ${low:.2f}-${high:.2f}  "
            f"({data['expected_return']:+.1%}, увер. {data['confidence']:.0%})\n",
            "normal",
        ))
    seg.append(("\n", "normal"))

    main_horizon = h.get("1m")
    if main_horizon and "top_features" in main_horizon:
        seg.append(("КЛЮЧЕВЫЕ ФАКТОРЫ (1 мес.)\n", "subheader"))
        for f in main_horizon["top_features"]:
            seg.append((f"  {f['label']}: {f['value']:+.2f}\n", "normal"))
        seg.append(("\n", "normal"))

    if fundamentals:
        seg.append(("ФУНДАМЕНТАЛ (последний отчёт)\n", "subheader"))
        seg.append((f"  Рост выручки г/г: {fundamentals['revenue_growth_yoy']:+.1%}\n", "normal"))
        seg.append((f"  Чистая маржа: {fundamentals['net_margin']:+.1%}\n", "normal"))
        seg.append((f"  ROE: {fundamentals['roe']:+.1%}\n", "normal"))
        seg.append((f"  Долг/капитал: {fundamentals['debt_to_equity']:.2f}\n\n", "normal"))

    market = signal.get("market")
    if market and market.get("regime") != "unknown":
        seg.append((f"РЫНОК (S&P 500): {market['label']}\n\n", "subheader"))

    sentiment = signal.get("sentiment")
    if sentiment and sentiment.get("num_articles", 0) > 0:
        seg.append((f"НОВОСТНОЙ ФОН: {sentiment['label']} ({sentiment['num_articles']} новостей)\n\n", "subheader"))

    action = signal["action"]
    action_tag = {"BUY": "buy", "SELL": "sell", "HOLD": "hold"}.get(action, "normal")
    seg.append((f"РЕКОМЕНДАЦИЯ: {ACTION_LABELS.get(action, action)}\n", action_tag))
    seg.append((f"{signal['reason']}\n\n", "muted"))

    if action in ("BUY", "SELL") and main_horizon and main_horizon.get("risk_levels"):
        rl = main_horizon["risk_levels"]
        seg.append(("УРОВНИ РИСКА (на основе волатильности ATR)\n", "subheader"))
        seg.append((f"  Стоп-лосс: ${rl['stop_loss']:.2f}\n", "normal"))
        seg.append((f"  Тейк-профит: ${rl['take_profit']:.2f}\n", "normal"))
        if rl.get("risk_reward_ratio"):
            seg.append((f"  Риск/прибыль: 1:{rl['risk_reward_ratio']:.1f}\n", "normal"))
        if position_size:
            seg.append((
                f"  Размер позиции (риск {position_size['risk_pct_label']} капитала): "
                f"~{position_size['shares']:.0f} акц. (${position_size['position_value']:.0f}, "
                f"{position_size['pct_of_portfolio']:.0%} портфеля)\n\n",
                "normal",
            ))

    earnings_warning = signal.get("earnings_warning")
    if earnings_warning:
        seg.append((f"ОТЧЁТНОСТЬ: {earnings_warning}\n\n", "warning"))

    seg.append((
        "Диапазон цены и уровни риска — статистическая оценка на основе "
        "истории, не гарантия. Не является индивидуальной инвестиционной "
        "рекомендацией.\n",
        "muted",
    ))

    return seg


def scan_watchlist(progress_callback=None) -> list[dict]:
    """
    Прогоняет весь локальный watchlist и возвращает результат по каждому
    тикеру — аналог daily_analysis_job из telegram_bot.py, но вызывается
    вручную по кнопке, а не по расписанию (десктоп-приложение не обязано
    работать постоянно в фоне). Значимые сигналы (BUY/SELL) логируются в
    БД — они и формируют историю для честной оценки точности (/accuracy).

    progress_callback(index, total, ticker) — опционально, для обновления
    прогресс-бара в GUI во время долгого скана.
    """
    results = []
    tickers = db.get_watchlist(LOCAL_USER_ID)

    for i, ticker in enumerate(tickers):
        if progress_callback:
            progress_callback(i, len(tickers), ticker)
        try:
            analysis = build_full_analysis(ticker)
            forecast = analysis["forecast"]
            signal = analysis["signal"]

            results.append({
                "ticker": ticker,
                "price": forecast["current_price"],
                "action": signal["action"],
                "confidence": signal["confidence"],
                "reason": signal["reason"],
                "error": None,
            })

            if signal["action"] in ("BUY", "SELL"):
                db.log_signal(
                    LOCAL_USER_ID, ticker, signal["action"], forecast["current_price"],
                    {k: v.get("expected_return") for k, v in forecast["horizons"].items() if "error" not in v},
                    signal["confidence"],
                )
        except Exception as e:
            results.append({"ticker": ticker, "error": str(e)})

    return results


def retrain_all(progress_callback=None) -> list[tuple[str, bool, str]]:
    """
    Принудительно переобучает модели для всех тикеров watchlist — то же
    самое, что weekly_retrain_job у бота, но по требованию пользователя
    (кнопка "Обучить заново" в GUI), а не по расписанию. Это и есть
    "самообучение": каждый раз, когда пользователь запускает это (или
    когда истекает недельный кэш при обычном анализе), модель дообучается
    на самых свежих данных.
    """
    results = []
    tickers = db.get_watchlist(LOCAL_USER_ID)

    for i, ticker in enumerate(tickers):
        if progress_callback:
            progress_callback(i, len(tickers), ticker)
        try:
            forecast_ticker(ticker, force_retrain=True)
            results.append((ticker, True, ""))
        except Exception as e:
            results.append((ticker, False, str(e)))

    return results


def scan_sp500(top_n: int = 10, deep_dive: bool = True, progress_callback=None) -> dict:
    """
    Двухэтапный скрининг всего индекса S&P 500 (~500 компаний):

    1. Быстрый технический скрининг (sp500_screener.screen_universe) —
       без обучения модели, занимает минуты, не часы
    2. Если deep_dive=True — полный анализ (build_full_analysis, тот же,
       что для watchlist) для top_n самых бычьих + top_n самых медвежьих
       кандидатов по итогам этапа 1. Значимые сигналы (BUY/SELL)
       логируются в БД — попадают в общую историю для честной оценки
       точности наравне с сигналами из watchlist.

    Возвращает {"screened": [...], "shortlist_analysis": [...] | None,
                "used_fallback_tickers": bool}.

    used_fallback_tickers=True означает, что актуальный список S&P 500
    загрузить не удалось (см. sp500_universe.py) и использован неполный
    резервный список — это обязательно нужно показать пользователю в UI,
    а не выдавать частичные результаты за полный охват индекса.
    """
    tickers, used_fallback = sp500_universe_module.fetch_sp500_tickers()

    screened = sp500_screener_module.screen_universe(tickers, progress_callback=progress_callback)

    result = {
        "screened": screened,
        "shortlist_analysis": None,
        "used_fallback_tickers": used_fallback,
        "universe_size": len(tickers),
        "screened_size": len(screened),
    }

    if not deep_dive or not screened:
        return result

    shortlist = sp500_screener_module.shortlist_candidates(screened, top_n=top_n)
    deep_results = []

    for i, ticker in enumerate(shortlist):
        if progress_callback:
            progress_callback(i, len(shortlist), f"Глубокий анализ {ticker}...")
        try:
            analysis = build_full_analysis(ticker)
            forecast = analysis["forecast"]
            signal = analysis["signal"]

            deep_results.append({
                "ticker": ticker,
                "price": forecast["current_price"],
                "action": signal["action"],
                "confidence": signal["confidence"],
                "reason": signal["reason"],
                "error": None,
            })

            if signal["action"] in ("BUY", "SELL"):
                db.log_signal(
                    LOCAL_USER_ID, ticker, signal["action"], forecast["current_price"],
                    {k: v.get("expected_return") for k, v in forecast["horizons"].items() if "error" not in v},
                    signal["confidence"],
                )
        except Exception as e:
            deep_results.append({"ticker": ticker, "error": str(e)})

    result["shortlist_analysis"] = deep_results
    return result
