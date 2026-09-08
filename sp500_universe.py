"""
Список компаний, входящих в индекс S&P 500.

Основной источник — таблица на Wikipedia (обновляется сообществом при
каждом изменении состава индекса; стандартная практика для таких задач
в открытых Python-проектах, не требует платного API). Если Wikipedia
недоступна или изменила формат страницы — используется небольшой
резервный список крупнейших компаний. Он ЗАВЕДОМО НЕПОЛНЫЙ (около 50 из
500) и может быть устаревшим на момент использования — это явно
показывается пользователю в интерфейсе, а не маскируется под полный список.
"""
import logging

logger = logging.getLogger(__name__)

WIKIPEDIA_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"

# Резервный список НА КРАЙНИЙ СЛУЧАЙ — используется только если получить
# актуальный список не удалось (сеть, изменившийся формат страницы).
# Не полный (~50 крупнейших компаний по капитализации) и может быть
# устаревшим — это ограничение всегда сообщается в UI, когда включается.
FALLBACK_TICKERS = [
    "AAPL", "MSFT", "NVDA", "GOOGL", "GOOG", "AMZN", "META", "BRK-B", "TSLA",
    "LLY", "AVGO", "JPM", "V", "UNH", "XOM", "MA", "COST", "HD", "PG", "JNJ",
    "NFLX", "WMT", "BAC", "CRM", "ABBV", "MRK", "CVX", "KO", "ORCL", "PEP",
    "ADBE", "AMD", "TMO", "MCD", "CSCO", "ACN", "LIN", "ABT", "WFC", "DHR",
    "TXN", "PM", "IBM", "GE", "CAT", "VZ", "INTU", "NOW", "AXP", "QCOM",
]


def fetch_sp500_tickers() -> tuple[list[str], bool]:
    """
    Возвращает (список_тикеров, использован_ли_резервный_список).

    Второй элемент — сигнал для интерфейса: если True, список неполный
    и потенциально устаревший, это нужно явно показать пользователю,
    а не тихо подсунуть 50 тикеров вместо обещанных 500.
    """
    try:
        import pandas as pd
        tables = pd.read_html(WIKIPEDIA_URL)
        df = tables[0]
        # yfinance использует дефис вместо точки в тикерах классов акций
        # (например BRK.B на Wikipedia -> BRK-B для yfinance)
        tickers = (
            df["Symbol"].astype(str).str.strip().str.upper()
            .str.replace(".", "-", regex=False).tolist()
        )
        tickers = [t for t in tickers if t and t != "NAN"]

        if len(tickers) < 400:
            # Таблица должна содержать порядка 500 строк — если сильно
            # меньше, формат страницы, вероятно, изменился
            raise ValueError(f"Получено подозрительно мало тикеров: {len(tickers)}")

        return tickers, False
    except Exception as e:
        logger.warning(
            "Не удалось загрузить актуальный список S&P 500 (%s). "
            "Используется резервный список из %d крупнейших компаний.",
            e, len(FALLBACK_TICKERS),
        )
        return list(FALLBACK_TICKERS), True
