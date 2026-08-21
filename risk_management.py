"""
Риск-менеджмент: стоп-лосс, тейк-профит и рекомендуемый размер позиции.

Простая рекомендация "BUY" без цифр риска — это не готовое к использованию
торговое решение, а только половина анализа. Профессиональный подход
всегда отвечает на три вопроса: где выход при ошибке (стоп-лосс), где
цель (тейк-профит), и сколько капитала ставить на эту идею (сайзинг).

Используется ATR (Average True Range) — стандартная мера волатильности
в техническом анализе, отражающая типичный дневной диапазон движения цены.
"""
import numpy as np
import pandas as pd

ATR_PERIOD = 14

# Множители ATR для стоп-лосса и тейк-профита. 2×ATR — распространённый
# консервативный ориентир, дающий модели "пространство для дыхания" без
# срабатывания стопа на обычном шуме.
STOP_LOSS_ATR_MULT = 2.0
TAKE_PROFIT_ATR_MULT = 3.5

# Риск на одну сделку — % капитала, который готовы потерять при срабатывании
# стоп-лосса (классическое эмпирическое правило риск-менеджмента: 1-2%)
RISK_PER_TRADE_PCT = 0.01


def compute_atr(df: pd.DataFrame, period: int = ATR_PERIOD) -> pd.Series:
    """True Range учитывает гэпы (разрывы между закрытием и открытием
    следующего дня), поэтому точнее простого High-Low диапазона."""
    high, low, close = df["High"], df["Low"], df["Close"]
    prev_close = close.shift(1)

    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()
    true_range = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

    return true_range.rolling(period).mean()


def compute_risk_levels(current_price: float, atr: float, direction: int) -> dict | None:
    """
    direction: 1 (BUY) или -1 (SELL/short). Возвращает уровни стоп-лосса,
    тейк-профита и соотношение риск/прибыль. None для HOLD или если ATR
    не удалось посчитать (недостаточно данных).
    """
    if direction == 0 or atr is None or np.isnan(atr) or atr <= 0:
        return None

    if direction == 1:
        stop_loss = current_price - STOP_LOSS_ATR_MULT * atr
        take_profit = current_price + TAKE_PROFIT_ATR_MULT * atr
    else:
        stop_loss = current_price + STOP_LOSS_ATR_MULT * atr
        take_profit = current_price - TAKE_PROFIT_ATR_MULT * atr

    risk = abs(current_price - stop_loss)
    reward = abs(take_profit - current_price)
    risk_reward_ratio = reward / risk if risk > 0 else None

    return {
        "stop_loss": float(max(stop_loss, 0.01)),
        "take_profit": float(max(take_profit, 0.01)),
        "risk_reward_ratio": float(risk_reward_ratio) if risk_reward_ratio else None,
        "atr": float(atr),
    }


def suggest_position_size(current_price: float, stop_loss: float,
                           portfolio_value: float = 10000.0,
                           risk_pct: float = RISK_PER_TRADE_PCT) -> dict:
    """
    Сайзинг по формуле фиксированного риска: сколько капитала готовы
    потерять на сделке (risk_pct от портфеля), делённое на дистанцию до
    стоп-лосса — даёт размер позиции, при котором срабатывание стопа
    ограничивает убыток заданным процентом, а не произвольной суммой.
    """
    risk_per_share = abs(current_price - stop_loss)
    if risk_per_share <= 0:
        return {"shares": 0, "position_value": 0.0, "pct_of_portfolio": 0.0}

    max_risk_amount = portfolio_value * risk_pct
    shares = max_risk_amount / risk_per_share
    position_value = shares * current_price
    pct_of_portfolio = min(position_value / portfolio_value, 1.0)

    return {
        "shares": round(shares, 2),
        "position_value": round(position_value, 2),
        "pct_of_portfolio": float(pct_of_portfolio),
    }
