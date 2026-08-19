"""
Backtest — проверка стратегии на исторических данных.

Используется walk-forward подход: на каждую точку ребалансировки модель
обучается ТОЛЬКО на данных ДО этой даты (без заглядывания в будущее —
это частая и грубая ошибка при бэктесте, дающая обманчиво хорошие
результаты). Далее симулируется портфель: покупка/продажа по сигналам
BUY/SELL/HOLD, и сравнивается итог со стратегией "купить и держать"
(buy & hold) — главным бенчмарком, который стратегия обязана обыгрывать
с поправкой на риск, иначе она бессмысленна.

Запуск из командной строки:
    python backtest.py AAPL
    python backtest.py AAPL --start 2019-01-01 --capital 10000
"""
import argparse
import warnings

import numpy as np
import pandas as pd

from data_fetcher import fetch_history
from features import build_features, merge_fundamentals
from fundamentals import fetch_fundamentals_timeseries
from model import HORIZONS, FEATURE_COLS, train_horizon_model, make_labels
from signal_logic import generate_signal

warnings.filterwarnings("ignore")

TRADING_DAYS_PER_YEAR = 252


def _forecast_at_index(feat_df: pd.DataFrame, idx_pos: int) -> dict:
    """
    Строит прогноз по всем горизонтам, обучая модели ТОЛЬКО на данных
    до позиции idx_pos (walk-forward, без утечки будущего).
    """
    train_df = feat_df.iloc[:idx_pos]
    current_row = feat_df[FEATURE_COLS].iloc[[idx_pos]]
    current_price = float(feat_df["close"].iloc[idx_pos])

    result = {"current_price": current_price, "horizons": {}}

    for name, days in HORIZONS.items():
        try:
            model, _ = train_horizon_model(train_df, days)
            proba = model.predict_proba(current_row)[0]
            classes = model.classes_
            pred_class = classes[np.argmax(proba)]
            confidence = float(np.max(proba))

            _, future_return = make_labels(train_df, days)
            avg_up = future_return[future_return > 0.02].mean()
            avg_down = future_return[future_return < -0.02].mean()

            if pred_class == 1:
                expected_return = avg_up if not np.isnan(avg_up) else 0.02
            elif pred_class == -1:
                expected_return = avg_down if not np.isnan(avg_down) else -0.02
            else:
                expected_return = 0.0

            result["horizons"][name] = {
                "direction": int(pred_class),
                "confidence": confidence,
                "expected_return": float(expected_return),
            }
        except Exception as e:
            result["horizons"][name] = {"error": str(e)}

    return result


def run_backtest(ticker: str, start_date: str = None, rebalance_days: int = 21,
                  initial_capital: float = 10000.0, min_train_size: int = 300) -> dict:
    """
    Прогоняет стратегию по истории.

    rebalance_days — как часто пересматривать позицию и переобучать модель
                      (21 = примерно раз в месяц). Чаще — точнее, но дольше считается.
    min_train_size — минимум точек данных, нужных для первого обучения модели.

    Возвращает dict с эквити-кривыми стратегии и бенчмарка, а также метриками.
    """
    raw = fetch_history(ticker)
    feat_df = build_features(raw)

    # Фундаментальные метрики присоединяются один раз методом merge_asof,
    # который сам по себе гарантирует point-in-time корректность на
    # КАЖДОЙ дате (используется только то, что available_date <= дата
    # строки) — поэтому здесь нет утечки будущего, несмотря на то что
    # слияние выполняется до начала walk-forward цикла.
    fund_df = fetch_fundamentals_timeseries(ticker)
    feat_df = merge_fundamentals(feat_df, fund_df)

    if start_date:
        feat_df = feat_df[feat_df.index >= pd.Timestamp(start_date, tz=feat_df.index.tz)]

    if len(feat_df) < min_train_size + 50:
        raise ValueError(
            f"Недостаточно данных для бэктеста {ticker}: "
            f"нужно минимум {min_train_size + 50} точек, есть {len(feat_df)}"
        )

    dates = feat_df.index
    close = feat_df["close"]

    # --- Симуляция портфеля стратегии ---
    cash = initial_capital
    shares = 0.0
    in_position = False
    trades = []  # список сделок для отчёта

    strategy_equity = pd.Series(index=dates, dtype=float)
    rebalance_points = list(range(min_train_size, len(feat_df), rebalance_days))

    last_signal_idx = 0
    current_signal = {"action": "HOLD"}

    for i in range(min_train_size, len(feat_df)):
        price_today = close.iloc[i]

        # Переобучаем модель и обновляем сигнал только в точках ребалансировки
        if i in rebalance_points:
            forecast = _forecast_at_index(feat_df, i)
            current_signal = generate_signal(forecast)

            if current_signal["action"] == "BUY" and not in_position:
                shares = cash / price_today
                cash = 0.0
                in_position = True
                trades.append({"date": dates[i], "action": "BUY", "price": price_today})

            elif current_signal["action"] == "SELL" and in_position:
                cash = shares * price_today
                shares = 0.0
                in_position = False
                trades.append({"date": dates[i], "action": "SELL", "price": price_today})
            # HOLD — позиция не меняется

        strategy_equity.iloc[i] = cash + shares * price_today

    strategy_equity = strategy_equity.dropna()

    # --- Бенчмарк: купил в начале периода и держит ---
    bench_start_price = close.iloc[min_train_size]
    bench_shares = initial_capital / bench_start_price
    benchmark_equity = close.iloc[min_train_size:] * bench_shares

    return {
        "ticker": ticker,
        "strategy_equity": strategy_equity,
        "benchmark_equity": benchmark_equity,
        "trades": trades,
        "initial_capital": initial_capital,
    }


# ---------- Метрики ----------

def compute_metrics(equity: pd.Series) -> dict:
    equity = equity.dropna()
    daily_returns = equity.pct_change().dropna()

    total_return = equity.iloc[-1] / equity.iloc[0] - 1
    n_days = len(equity)
    years = n_days / TRADING_DAYS_PER_YEAR
    cagr = (equity.iloc[-1] / equity.iloc[0]) ** (1 / years) - 1 if years > 0 else np.nan

    sharpe = (
        daily_returns.mean() / daily_returns.std() * np.sqrt(TRADING_DAYS_PER_YEAR)
        if daily_returns.std() > 0 else np.nan
    )

    running_max = equity.cummax()
    drawdown = equity / running_max - 1
    max_drawdown = drawdown.min()

    return {
        "total_return": total_return,
        "cagr": cagr,
        "sharpe": sharpe,
        "max_drawdown": max_drawdown,
    }


def format_backtest_report(result: dict) -> str:
    strat_metrics = compute_metrics(result["strategy_equity"])
    bench_metrics = compute_metrics(result["benchmark_equity"])
    trades = result["trades"]
    wins = sells = 0

    # Оценка win rate: сравниваем цену продажи с ценой предыдущей покупки
    buy_price = None
    for t in trades:
        if t["action"] == "BUY":
            buy_price = t["price"]
        elif t["action"] == "SELL" and buy_price is not None:
            sells += 1
            if t["price"] > buy_price:
                wins += 1
            buy_price = None
    win_rate = wins / sells if sells > 0 else None

    lines = [
        f"=== Backtest: {result['ticker']} ===",
        f"Период: {result['strategy_equity'].index[0].date()} — {result['strategy_equity'].index[-1].date()}",
        f"Начальный капитал: ${result['initial_capital']:,.0f}",
        "",
        f"{'Метрика':<20}{'Стратегия':>15}{'Buy & Hold':>15}",
        f"{'-'*50}",
        f"{'Итог. доходность':<20}{strat_metrics['total_return']:>14.1%} {bench_metrics['total_return']:>14.1%}",
        f"{'CAGR (годовая)':<20}{strat_metrics['cagr']:>14.1%} {bench_metrics['cagr']:>14.1%}",
        f"{'Sharpe ratio':<20}{strat_metrics['sharpe']:>15.2f}{bench_metrics['sharpe']:>15.2f}",
        f"{'Max drawdown':<20}{strat_metrics['max_drawdown']:>14.1%} {bench_metrics['max_drawdown']:>14.1%}",
        "",
        f"Сделок совершено: {len(trades)} (закрытых пар: {sells})",
    ]
    if win_rate is not None:
        lines.append(f"Win rate: {win_rate:.0%}")

    lines.append("")
    if strat_metrics["total_return"] > bench_metrics["total_return"]:
        lines.append("✅ Стратегия обыграла Buy & Hold по итоговой доходности")
    else:
        lines.append("❌ Стратегия НЕ обыграла Buy & Hold — использовать с осторожностью")

    return "\n".join(lines)


# ---------- CLI ----------

def main():
    parser = argparse.ArgumentParser(description="Backtest стратегии по тикеру")
    parser.add_argument("ticker", type=str, help="Тикер акции, например AAPL")
    parser.add_argument("--start", type=str, default=None, help="Дата начала YYYY-MM-DD")
    parser.add_argument("--capital", type=float, default=10000.0, help="Начальный капитал")
    parser.add_argument("--rebalance-days", type=int, default=21, help="Периодичность ребалансировки в торговых днях")
    parser.add_argument("--save-chart", action="store_true", help="Сохранить график эквити в PNG")
    args = parser.parse_args()

    print(f"Загружаю данные и считаю бэктест для {args.ticker}... это может занять минуту-две.")
    result = run_backtest(
        args.ticker,
        start_date=args.start,
        rebalance_days=args.rebalance_days,
        initial_capital=args.capital,
    )
    print()
    print(format_backtest_report(result))

    if args.save_chart:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        plt.figure(figsize=(10, 5))
        plt.plot(result["strategy_equity"], label="Стратегия")
        plt.plot(result["benchmark_equity"], label="Buy & Hold")
        plt.title(f"Backtest: {args.ticker}")
        plt.xlabel("Дата")
        plt.ylabel("Стоимость портфеля, $")
        plt.legend()
        plt.grid(alpha=0.3)
        out_path = f"backtest_{args.ticker}.png"
        plt.savefig(out_path, dpi=120, bbox_inches="tight")
        print(f"\nГрафик сохранён: {out_path}")


if __name__ == "__main__":
    main()
