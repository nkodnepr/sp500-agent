"""Тесты для features.py — расчёт технических индикаторов."""
from features import build_features, merge_fundamentals
import pandas as pd


def test_build_features_has_expected_columns(synthetic_ohlcv):
    raw = synthetic_ohlcv()
    feat = build_features(raw)

    expected_cols = {
        "sma_10", "sma_50", "sma_200", "price_to_sma50", "price_to_sma200",
        "rsi_14", "macd_hist", "bb_position", "volatility_20",
        "volume_ratio", "momentum_5", "momentum_20", "momentum_60", "close",
    }
    assert expected_cols.issubset(set(feat.columns))
    assert len(feat) > 0
    # Rolling-окна (SMA200 и т.д.) должны быть полностью посчитаны — dropna()
    # в build_features обязан убрать все NaN
    assert not feat.isna().any().any()


def test_build_features_drops_warmup_period(synthetic_ohlcv):
    raw = synthetic_ohlcv(n=800)
    feat = build_features(raw)
    # Первые ~199 строк недостаточны для SMA200 — должны быть отброшены
    assert len(feat) < len(raw)
    assert len(feat) > 0


def test_merge_fundamentals_point_in_time_correctness(synthetic_ohlcv):
    """
    Критическая проверка: фундаментальные данные не должны быть видны
    ДО даты их реальной публикации (available_date) — иначе это утечка
    будущего в обучение/бэктест.
    """
    raw = synthetic_ohlcv(n=400)
    feat = build_features(raw)

    report_date = feat.index[100]
    fund_df = pd.DataFrame(
        {"revenue_growth_yoy": [0.12], "net_margin": [0.20],
         "roe": [0.18], "debt_to_equity": [0.5]},
        index=pd.DatetimeIndex([report_date], name="available_date"),
    )

    merged = merge_fundamentals(feat, fund_df)

    before = merged.loc[merged.index < report_date]
    after = merged.loc[merged.index >= report_date]

    assert (before["revenue_growth_yoy"] == 0.0).all(), "Утечка данных до даты публикации отчёта"
    assert (after["revenue_growth_yoy"] == 0.12).all()


def test_merge_fundamentals_handles_empty_input(synthetic_ohlcv):
    """Если фундаментальных данных нет вообще — не должно падать, только нули."""
    raw = synthetic_ohlcv()
    feat = build_features(raw)
    merged = merge_fundamentals(feat, pd.DataFrame())
    assert (merged["revenue_growth_yoy"] == 0.0).all()
