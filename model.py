"""
Модели прогноза по горизонтам: 1 неделя, 2 недели, 1 месяц, 3 месяца.

Подход: для каждого горизонта обучается отдельная модель классификации
(вырастет / упадёт / без изменений) на исторических данных. Используется
RandomForest — устойчив к переобучению на небольших выборках и даёт
вероятности (используются как "уверенность").

ВАЖНО: это baseline-модель для старта. Она НЕ гарантирует точность
предсказаний. Перед реальным использованием обязательно нужен backtest
(см. backtest.py) и сравнение с простым бенчмарком (buy&hold).
"""
import numpy as np
import pandas as pd
from datetime import datetime
from sklearn.ensemble import RandomForestClassifier

from features import build_features, merge_fundamentals
from data_fetcher import fetch_history
from fundamentals import fetch_fundamentals_timeseries, FUNDAMENTAL_COLS
from market_context import add_relative_strength, RELATIVE_STRENGTH_WINDOWS
from risk_management import compute_atr, compute_risk_levels
import model_store

# Горизонты в торговых днях
HORIZONS = {
    "1w": 5,
    "2w": 10,
    "1m": 21,
    "3m": 63,
}

TECHNICAL_COLS = [
    "price_to_sma50", "price_to_sma200", "rsi_14", "macd_hist",
    "bb_position", "volatility_20", "volume_ratio",
    "momentum_5", "momentum_20", "momentum_60",
]

MARKET_COLS = list(RELATIVE_STRENGTH_WINDOWS.keys())  # relative_strength_20/60

# Технические + рыночные + фундаментальные признаки. Фундаментал особенно
# важен для более длинных горизонтов (1-3 месяца), где технический анализ
# один по себе менее надёжен. Рыночные признаки (relative strength) отделяют
# собственную силу акции от общерыночного движения.
FEATURE_COLS = TECHNICAL_COLS + MARKET_COLS + FUNDAMENTAL_COLS

# Человекочитаемые названия признаков — для объяснения, НА ОСНОВЕ ЧЕГО
# модель приняла решение (иначе прогноз выглядит как "чёрный ящик")
FEATURE_LABELS = {
    "price_to_sma50": "цена относительно 50-дневной средней",
    "price_to_sma200": "цена относительно 200-дневной средней",
    "rsi_14": "RSI (индекс относительной силы)",
    "macd_hist": "MACD-гистограмма (сила тренда)",
    "bb_position": "положение в полосах Боллинджера",
    "volatility_20": "волатильность (20 дней)",
    "volume_ratio": "объём торгов к среднему",
    "momentum_5": "моментум за 5 дней",
    "momentum_20": "моментум за 20 дней",
    "momentum_60": "моментум за 60 дней",
    "revenue_growth_yoy": "рост выручки год к году",
    "net_margin": "чистая маржа",
    "roe": "рентабельность капитала (ROE)",
    "debt_to_equity": "долг к капиталу",
    "relative_strength_20": "сила против рынка (20 дней)",
    "relative_strength_60": "сила против рынка (60 дней)",
}

# Порог для классификации "рост" (в долях, 0.02 = 2%)
UP_THRESHOLD = 0.02
DOWN_THRESHOLD = -0.02


def make_labels(feat_df: pd.DataFrame, horizon_days: int) -> pd.Series:
    """
    Создаёт метки класса на основе будущей доходности через horizon_days:
    1 = рост > UP_THRESHOLD, -1 = падение < DOWN_THRESHOLD, 0 = нейтрально
    """
    future_price = feat_df["close"].shift(-horizon_days)
    future_return = future_price / feat_df["close"] - 1

    labels = pd.Series(0, index=feat_df.index)
    labels[future_return > UP_THRESHOLD] = 1
    labels[future_return < DOWN_THRESHOLD] = -1
    return labels, future_return


def train_horizon_model(feat_df: pd.DataFrame, horizon_days: int):
    """Обучает модель для одного горизонта. Возвращает (модель, точность на holdout)."""
    labels, future_return = make_labels(feat_df, horizon_days)

    X = feat_df[FEATURE_COLS].iloc[:-horizon_days]
    y = labels.iloc[:-horizon_days]

    if len(X) < 100:
        raise ValueError("Недостаточно данных для обучения модели")

    # Простой временной сплит (без перемешивания!) — последние 20% как holdout
    split_idx = int(len(X) * 0.8)
    X_train, X_test = X.iloc[:split_idx], X.iloc[split_idx:]
    y_train, y_test = y.iloc[:split_idx], y.iloc[split_idx:]

    model = RandomForestClassifier(
        n_estimators=200,
        max_depth=6,
        min_samples_leaf=10,
        random_state=42,
        class_weight="balanced",
    )
    model.fit(X_train, y_train)
    holdout_accuracy = model.score(X_test, y_test) if len(X_test) > 0 else None

    return model, holdout_accuracy


def _top_features(model, feature_row: pd.DataFrame, top_n: int = 3) -> list[dict]:
    """
    Возвращает top_n признаков, на которые модель опирается сильнее всего
    (feature_importances_ у RandomForest), вместе с их текущим значением.
    Это превращает прогноз из "чёрного ящика" в объяснимый: пользователь
    видит, ПОЧЕМУ модель считает так, а не просто верит цифре.
    """
    importances = model.feature_importances_
    values = feature_row.iloc[0]

    pairs = sorted(zip(FEATURE_COLS, importances), key=lambda x: -x[1])[:top_n]
    return [
        {
            "feature": name,
            "label": FEATURE_LABELS.get(name, name),
            "value": float(values[name]),
            "importance": float(imp),
        }
        for name, imp in pairs
    ]


def _price_target_range(current_price: float, expected_return: float, class_returns: pd.Series) -> tuple[float, float]:
    """
    Диапазон целевой цены на основе исторического разброса (std) исходов
    для данного класса — а не единственная точечная цифра, которая создаёт
    ложное ощущение точности. Если исторических примеров мало, используется
    консервативный запасной разброс.
    """
    if len(class_returns) >= 5:
        std_return = float(class_returns.std())
    else:
        std_return = abs(expected_return) * 0.5 if expected_return != 0 else 0.03

    if np.isnan(std_return) or std_return == 0:
        std_return = max(abs(expected_return) * 0.5, 0.01)

    low = current_price * (1 + expected_return - std_return)
    high = current_price * (1 + expected_return + std_return)
    return max(low, 0.01), high


def forecast_ticker(ticker: str, force_retrain: bool = False) -> dict:
    """
    Полный прогноз по тикеру на всех горизонтах.
    Возвращает словарь с прогнозируемым классом, вероятностью (уверенностью)
    и ожидаемой доходностью (оценка) для каждого горизонта.

    По умолчанию использует кэшированные модели (обновляются раз в неделю,
    см. model_store.py) — это быстро. force_retrain=True принудительно
    обучает заново и обновляет кэш (используется еженедельным job'ом и
    командой /retrain).
    """
    raw = fetch_history(ticker)
    feat_df = build_features(raw)

    feat_df = add_relative_strength(feat_df)

    fund_df = fetch_fundamentals_timeseries(ticker)
    feat_df = merge_fundamentals(feat_df, fund_df)

    current_price = float(feat_df["close"].iloc[-1])
    latest_features = feat_df[FEATURE_COLS].iloc[[-1]]

    # ATR для риск-менеджмента (стоп-лосс/тейк-профит) — считается один раз
    # на сырых OHLC данных, не зависит от горизонта
    atr_series = compute_atr(raw)
    current_atr = float(atr_series.iloc[-1]) if not atr_series.empty and not np.isnan(atr_series.iloc[-1]) else None

    results = {"ticker": ticker, "current_price": current_price, "horizons": {}}

    models, meta = (None, None) if force_retrain else model_store.load_models(ticker)

    if models is None:
        # Кэша нет или он устарел (> 7 дней) — обучаем заново по всем горизонтам
        trained_models = {}
        holdout_accuracies = {}
        for name, days in HORIZONS.items():
            try:
                m, acc = train_horizon_model(feat_df, days)
                trained_models[name] = m
                holdout_accuracies[name] = acc
            except Exception as e:
                results["horizons"][name] = {"error": str(e)}
        if trained_models:
            model_store.save_models(ticker, trained_models, holdout_accuracies)
        models = trained_models
        results["models_trained_at"] = datetime.utcnow().isoformat()
        results["models_from_cache"] = False
    else:
        results["models_trained_at"] = meta["trained_at"]
        results["models_from_cache"] = True

    for name, days in HORIZONS.items():
        if name in results["horizons"]:
            continue  # уже записана ошибка обучения выше
        try:
            m = models[name]
            proba = m.predict_proba(latest_features)[0]
            classes = m.classes_  # например [-1, 0, 1]

            pred_class = classes[np.argmax(proba)]
            confidence = float(np.max(proba))

            # Историческая доходность (среднее и разброс) для оценки
            # величины движения и построения диапазона целевой цены
            _, future_return = make_labels(feat_df, days)
            up_returns = future_return[future_return > UP_THRESHOLD]
            down_returns = future_return[future_return < DOWN_THRESHOLD]
            neutral_returns = future_return[(future_return >= DOWN_THRESHOLD) & (future_return <= UP_THRESHOLD)]

            if pred_class == 1:
                expected_return = float(up_returns.mean()) if not up_returns.empty and not np.isnan(up_returns.mean()) else UP_THRESHOLD
                class_returns = up_returns
            elif pred_class == -1:
                expected_return = float(down_returns.mean()) if not down_returns.empty and not np.isnan(down_returns.mean()) else DOWN_THRESHOLD
                class_returns = down_returns
            else:
                expected_return = float(neutral_returns.mean()) if not neutral_returns.empty and not np.isnan(neutral_returns.mean()) else 0.0
                class_returns = neutral_returns

            price_low, price_high = _price_target_range(current_price, expected_return, class_returns)
            target_price = current_price * (1 + expected_return)

            risk_levels = compute_risk_levels(current_price, current_atr, int(pred_class))

            results["horizons"][name] = {
                "direction": int(pred_class),  # 1=рост, -1=падение, 0=нейтрально
                "confidence": confidence,
                "expected_return": expected_return,
                "target_price": target_price,
                "price_range": (price_low, price_high),
                "top_features": _top_features(m, latest_features, top_n=3),
                "risk_levels": risk_levels,  # None для HOLD/нейтральных горизонтов
            }
        except Exception as e:
            results["horizons"][name] = {"error": str(e)}

    return results
