"""
Форматирование сообщений для Telegram.
"""

ACTION_EMOJI = {"BUY": "🟢", "SELL": "🔴", "HOLD": "⚪"}
DIRECTION_ARROW = {1: "↑", -1: "↓", 0: "→"}
HORIZON_LABELS = [("1w", "1 неделя"), ("2w", "2 недели"), ("1m", "1 месяц"), ("3m", "3 месяца")]


def format_signal_message(forecast: dict, signal: dict, fundamentals: dict | None = None,
                           position_size: dict | None = None) -> str:
    ticker = forecast["ticker"]
    price = forecast["current_price"]
    h = forecast["horizons"]

    lines = [f"📊 *{ticker}*  —  текущая цена ${price:.2f}", "", "*Прогноз цены:*"]

    for name, label in HORIZON_LABELS:
        data = h.get(name, {})
        if "error" in data:
            lines.append(f"• {label}: н/д")
            continue
        arrow = DIRECTION_ARROW.get(data["direction"], "→")
        low, high = data["price_range"]
        lines.append(
            f"• {label}: {arrow} ${low:.2f}–${high:.2f} "
            f"({data['expected_return']:+.1%}, увер. {data['confidence']:.0%})"
        )

    # Ключевые факторы решения — берём горизонт 1 месяц как наиболее
    # репрезентативный для практического решения о покупке/продаже.
    # Показывает ПОЧЕМУ модель так считает, а не просто выдаёт цифру.
    main_horizon = h.get("1m")
    if main_horizon and "top_features" in main_horizon:
        feats = main_horizon["top_features"]
        feat_strs = [f"{f['label']} ({f['value']:+.2f})" for f in feats]
        lines.append("")
        lines.append(f"🔍 *Ключевые факторы (1 мес.):* {', '.join(feat_strs)}")

    if fundamentals:
        lines.append("")
        lines.append("📈 *Фундаментал (последний отчёт):*")
        lines.append(f"Рост выручки г/г: {fundamentals['revenue_growth_yoy']:+.1%}")
        lines.append(f"Чистая маржа: {fundamentals['net_margin']:+.1%}")
        lines.append(f"ROE: {fundamentals['roe']:+.1%}")
        lines.append(f"Долг/капитал: {fundamentals['debt_to_equity']:.2f}")

    market = signal.get("market")
    if market and market.get("regime") != "unknown":
        lines.append("")
        regime_emoji = {"bull": "🐂", "bear": "🐻", "sideways": "➡️"}.get(market["regime"], "")
        lines.append(f"{regime_emoji} *Рынок (S&P 500):* {market['label']}")

    sentiment = signal.get("sentiment")
    if sentiment and sentiment.get("num_articles", 0) > 0:
        lines.append("")
        sentiment_emoji = "🟢" if sentiment["score"] > 0.15 else ("🔴" if sentiment["score"] < -0.15 else "⚪")
        lines.append(
            f"{sentiment_emoji} *Новостной фон:* {sentiment['label']} "
            f"({sentiment['num_articles']} новостей)"
        )

    lines.append("")
    emoji = ACTION_EMOJI.get(signal["action"], "⚪")
    lines.append(f"{emoji} *Рекомендация: {signal['action']}*")
    lines.append(f"_{signal['reason']}_")

    # Риск-менеджмент показываем только для реальных сигналов (BUY/SELL),
    # используя уровни горизонта 1 месяц как основной срок удержания позиции
    if signal["action"] in ("BUY", "SELL") and main_horizon and main_horizon.get("risk_levels"):
        rl = main_horizon["risk_levels"]
        lines.append("")
        lines.append("🎯 *Уровни риска (на основе волатильности ATR):*")
        lines.append(f"Стоп-лосс: ${rl['stop_loss']:.2f}")
        lines.append(f"Тейк-профит: ${rl['take_profit']:.2f}")
        if rl.get("risk_reward_ratio"):
            lines.append(f"Риск/прибыль: 1:{rl['risk_reward_ratio']:.1f}")
        if position_size:
            lines.append(
                f"Размер позиции (риск {position_size.get('risk_pct_label', '1%')} капитала): "
                f"~{position_size['shares']:.0f} акц. (${position_size['position_value']:.0f}, "
                f"{position_size['pct_of_portfolio']:.0%} портфеля)"
            )

    earnings_warning = signal.get("earnings_warning")
    if earnings_warning:
        lines.append("")
        lines.append(f"⚠️ *Отчётность:* {earnings_warning}")

    lines.append("")
    lines.append(
        "⚠️ Диапазон цены и уровни риска — статистическая оценка на основе "
        "истории, не гарантия. Не является индивидуальной инвестиционной рекомендацией"
    )

    return "\n".join(lines)


def format_watchlist(tickers: list[str]) -> str:
    if not tickers:
        return "Ваш список пуст. Добавьте акции: `/add AAPL`"
    return "📋 *Ваш список отслеживания:*\n" + "\n".join(f"• {t}" for t in tickers)
