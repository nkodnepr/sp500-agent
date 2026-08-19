"""
Фундаментальные данные компании: рост выручки, маржа, рентабельность
капитала (ROE), долговая нагрузка.

КЛЮЧЕВОЙ МОМЕНТ: чтобы не допустить утечки будущего в бэктесте, каждая
метрика привязывается не к дате окончания отчётного периода, а к
available_date — дате, когда отчётность РЕАЛЬНО стала публично доступна
(дата окончания периода + задержка публикации ~90 дней, типичная для
10-K/10-Q). Без этого модель на бэктесте "видела" бы квартальные
результаты за месяц-два до их реальной публикации — это классическая
и грубая ошибка, дающая обманчиво хорошие результаты.

Источник — годовая отчётность через yfinance (доступно бесплатно на
глубину ~4 лет; для более длинной истории нужен платный источник вроде
SEC EDGAR API с полным архивом).
"""
import pandas as pd
import yfinance as yf

REPORTING_LAG_DAYS = 90

FUNDAMENTAL_COLS = ["revenue_growth_yoy", "net_margin", "roe", "debt_to_equity"]


def _find_row(df: pd.DataFrame, candidates: list[str]):
    """
    Ищет строку в отчётности по одному из нескольких возможных названий —
    yfinance периодически меняет нейминг полей между версиями библиотеки.
    """
    if df is None or df.empty:
        return None
    normalized = {str(idx).lower().replace(" ", ""): idx for idx in df.index}
    for name in candidates:
        key = name.lower().replace(" ", "")
        if key in normalized:
            return df.loc[normalized[key]]
    return None


def fetch_fundamentals_timeseries(ticker: str) -> pd.DataFrame:
    """
    Возвращает DataFrame, индексированный по available_date, с колонками
    FUNDAMENTAL_COLS. Может быть пустым, если данные недоступны — это
    штатная ситуация (например, для некоторых тикеров нет полной
    отчётности через бесплатный источник), обрабатывается на уровне
    merge_fundamentals в features.py.
    """
    try:
        tkr = yf.Ticker(ticker)
        financials = tkr.financials
        balance = tkr.balance_sheet
    except Exception:
        return pd.DataFrame()

    revenue = _find_row(financials, ["Total Revenue", "TotalRevenue", "Revenue"])
    net_income = _find_row(financials, ["Net Income", "NetIncome", "Net Income Common Stockholders"])
    equity = _find_row(balance, ["Stockholders Equity", "StockholdersEquity",
                                  "Total Stockholder Equity", "Common Stock Equity"])
    total_debt = _find_row(balance, ["Total Debt", "TotalDebt"])

    if revenue is None or net_income is None:
        return pd.DataFrame()

    dates = sorted(d for d in revenue.index if not pd.isna(revenue.get(d)))
    rows = []

    for i, date in enumerate(dates):
        rev = revenue.get(date)
        if pd.isna(rev) or rev == 0:
            continue

        ni = net_income.get(date)
        eq = equity.get(date) if equity is not None else None
        debt = total_debt.get(date) if total_debt is not None else None

        prev_rev = revenue.get(dates[i - 1]) if i > 0 else None
        if prev_rev not in (None, 0) and not pd.isna(prev_rev):
            revenue_growth_yoy = rev / prev_rev - 1
        else:
            revenue_growth_yoy = 0.0

        net_margin = float(ni / rev) if ni is not None and not pd.isna(ni) else 0.0

        if eq not in (None, 0) and not pd.isna(eq) and ni is not None and not pd.isna(ni):
            roe = float(ni / eq)
        else:
            roe = 0.0

        if eq not in (None, 0) and not pd.isna(eq) and debt is not None and not pd.isna(debt):
            debt_to_equity = float(debt / eq)
        else:
            debt_to_equity = 0.0

        available_date = pd.Timestamp(date) + pd.Timedelta(days=REPORTING_LAG_DAYS)
        rows.append({
            "available_date": available_date,
            "revenue_growth_yoy": float(revenue_growth_yoy),
            "net_margin": net_margin,
            "roe": roe,
            "debt_to_equity": debt_to_equity,
        })

    if not rows:
        return pd.DataFrame()

    return pd.DataFrame(rows).sort_values("available_date").set_index("available_date")


def latest_fundamentals_snapshot(ticker: str) -> dict | None:
    """Последние известные фундаментальные метрики — для отображения пользователю."""
    df = fetch_fundamentals_timeseries(ticker)
    if df.empty:
        return None
    return df.iloc[-1].to_dict()
