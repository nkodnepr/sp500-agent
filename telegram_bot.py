"""
Главный файл бота. Запуск: python telegram_bot.py

Команды:
  /start           - приветствие
  /add AAPL        - добавить тикер в свой список отслеживания
  /remove AAPL     - убрать тикер
  /list            - показать список
  /check AAPL      - разовый анализ тикера (вне расписания)
  /history         - последние отправленные сигналы
  /backtest AAPL   - проверка стратегии на исторических данных (3 года)
  /accuracy        - честная точность прошлых сигналов (сверка с реальной ценой)
  /retrain AAPL    - принудительно переобучить модель прямо сейчас
"""
import logging
from datetime import time as dtime

from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

import db
from config import TELEGRAM_TOKEN, DAILY_ANALYSIS_HOUR, DAILY_ANALYSIS_MINUTE
from data_fetcher import is_valid_ticker
from model import forecast_ticker, HORIZONS
from signal_logic import generate_signal
from formatting import format_signal_message, format_watchlist
from backtest import run_backtest, format_backtest_report
from fundamentals import latest_fundamentals_snapshot
from news_sentiment import get_sentiment_score
from accuracy import evaluate_accuracy, format_accuracy_report
from market_context import get_market_regime
from earnings import check_earnings_within_horizons
from risk_management import suggest_position_size, RISK_PER_TRADE_PCT

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


# ---------- Команды ----------

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "👋 Привет! Я анализирую акции из твоего списка (технический анализ + "
        "фундаментал + новостной фон + сравнение с рынком S&P 500 + риск-менеджмент) "
        "и присылаю рекомендации BUY/SELL с конкретными ценовыми ориентирами.\n\n"
        "Команды:\n"
        "/add AAPL — добавить тикер\n"
        "/remove AAPL — убрать тикер\n"
        "/list — показать список\n"
        "/check AAPL — разовый анализ прямо сейчас\n"
        "/history — последние отправленные сигналы\n"
        "/backtest AAPL — проверка стратегии на истории (3 года)\n"
        "/accuracy — честная точность прошлых сигналов по факту\n"
        "/retrain AAPL — переобучить модель прямо сейчас\n\n"
        "Модели переобучаются автоматически раз в неделю.\n\n"
        "⚠️ Я не покупаю и не продаю акции сам — только анализирую и советую."
    )
    await update.message.reply_text(text)


async def cmd_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Использование: `/add AAPL`", parse_mode="Markdown")
        return
    ticker = context.args[0].upper()

    msg = await update.message.reply_text(f"Проверяю {ticker}...")
    if not is_valid_ticker(ticker):
        await msg.edit_text(f"⚠️ Тикер {ticker} не найден. Проверь написание.")
        return

    added = db.add_ticker(update.effective_user.id, ticker)
    if added:
        await msg.edit_text(f"✅ {ticker} добавлен в список отслеживания")
    else:
        await msg.edit_text(f"{ticker} уже есть в твоём списке")


async def cmd_remove(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Использование: `/remove AAPL`", parse_mode="Markdown")
        return
    ticker = context.args[0].upper()
    removed = db.remove_ticker(update.effective_user.id, ticker)
    if removed:
        await update.message.reply_text(f"❌ {ticker} удалён из списка")
    else:
        await update.message.reply_text(f"{ticker} не найден в твоём списке")


async def cmd_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tickers = db.get_watchlist(update.effective_user.id)
    await update.message.reply_text(format_watchlist(tickers), parse_mode="Markdown")


def _build_full_analysis(ticker: str, force_retrain: bool = False, portfolio_value: float = 10000.0):
    """
    Собирает полный аналитический контекст по тикеру: технико-фундаментальный
    прогноз, sentiment, режим рынка, отчётность и итоговый сигнал с
    риск-уровнями. Общая логика для /check и ежедневного анализа —
    чтобы не дублировать сборку контекста в двух местах.
    """
    forecast = forecast_ticker(ticker, force_retrain=force_retrain)
    sentiment = get_sentiment_score(ticker)
    market = get_market_regime()
    earnings = check_earnings_within_horizons(ticker, HORIZONS)

    signal = generate_signal(forecast, sentiment=sentiment, market=market, earnings=earnings)

    position_size = None
    main_horizon = forecast["horizons"].get("1m")
    if signal["action"] in ("BUY", "SELL") and main_horizon and main_horizon.get("risk_levels"):
        rl = main_horizon["risk_levels"]
        position_size = suggest_position_size(
            forecast["current_price"], rl["stop_loss"], portfolio_value=portfolio_value,
        )
        position_size["risk_pct_label"] = f"{RISK_PER_TRADE_PCT:.0%}"

    fundamentals = latest_fundamentals_snapshot(ticker)

    return forecast, signal, fundamentals, position_size


async def cmd_check(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Использование: `/check AAPL`", parse_mode="Markdown")
        return
    ticker = context.args[0].upper()

    msg = await update.message.reply_text(f"⏳ Анализирую {ticker}, это может занять до минуты...")
    try:
        forecast, signal, fundamentals, position_size = _build_full_analysis(ticker)
        text = format_signal_message(forecast, signal, fundamentals, position_size)
        await msg.edit_text(text, parse_mode="Markdown")

        db.log_signal(
            update.effective_user.id, ticker, signal["action"],
            forecast["current_price"],
            {k: v.get("expected_return") for k, v in forecast["horizons"].items() if "error" not in v},
            signal["confidence"],
        )
    except Exception as e:
        logger.exception("Ошибка анализа %s", ticker)
        await msg.edit_text(f"⚠️ Не удалось проанализировать {ticker}: {e}")


async def cmd_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    rows = db.get_signal_history(update.effective_user.id, limit=10)
    if not rows:
        await update.message.reply_text("История сигналов пока пуста")
        return
    lines = ["📜 *Последние сигналы:*", ""]
    for r in rows:
        lines.append(
            f"{r['created_at'][:16]} — {r['ticker']} — *{r['action']}* "
            f"(цена ${r['price_at_signal']:.2f}, увер. {r['confidence']:.0%})"
        )
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def cmd_backtest(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Использование: `/backtest AAPL`", parse_mode="Markdown")
        return
    ticker = context.args[0].upper()

    msg = await update.message.reply_text(
        f"⏳ Считаю бэктест для {ticker} за последние ~3 года. "
        f"Это переобучение модели много раз подряд — может занять пару минут."
    )
    try:
        # 3 года и ежемесячная ребалансировка — компромисс между скоростью и качеством
        result = run_backtest(ticker, rebalance_days=21)
        report = format_backtest_report(result)
        await msg.edit_text(f"```\n{report}\n```", parse_mode="Markdown")
    except Exception as e:
        logger.exception("Ошибка бэктеста %s", ticker)
        await msg.edit_text(f"⚠️ Не удалось посчитать бэктест для {ticker}: {e}")


async def cmd_accuracy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = await update.message.reply_text("⏳ Сверяю прошлые сигналы с реальными ценами...")
    try:
        rows = db.get_all_signals(update.effective_user.id)
        if not rows:
            await msg.edit_text(
                "История сигналов пока пуста — нечего оценивать. Она "
                "накапливается автоматически по мере /check и ежедневного анализа."
            )
            return
        stats = evaluate_accuracy(rows)
        report = format_accuracy_report(stats)
        await msg.edit_text(report, parse_mode="Markdown")
    except Exception as e:
        logger.exception("Ошибка оценки точности")
        await msg.edit_text(f"⚠️ Не удалось посчитать точность: {e}")


async def cmd_retrain(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Использование: `/retrain AAPL`", parse_mode="Markdown")
        return
    ticker = context.args[0].upper()

    msg = await update.message.reply_text(f"⏳ Переобучаю модель для {ticker}...")
    try:
        forecast_ticker(ticker, force_retrain=True)
        await msg.edit_text(f"✅ Модель для {ticker} переобучена и обновлена в кэше на 7 дней")
    except Exception as e:
        logger.exception("Ошибка переобучения %s", ticker)
        await msg.edit_text(f"⚠️ Не удалось переобучить модель для {ticker}: {e}")


# ---------- Ежедневный анализ (планировщик) ----------

async def daily_analysis_job(context: ContextTypes.DEFAULT_TYPE):
    logger.info("Запуск ежедневного анализа по всем пользователям")
    for user_id in db.get_all_users():
        tickers = db.get_watchlist(user_id)
        for ticker in tickers:
            try:
                # Использует кэш моделей (обновляется раз в неделю отдельным
                # job'ом) — ежедневный прогон быстрый, не требует переобучения
                forecast, signal, fundamentals, position_size = _build_full_analysis(ticker)

                # Присылаем уведомление только по значимым сигналам,
                # чтобы не спамить пользователя каждый день по каждой акции
                if signal["action"] in ("BUY", "SELL"):
                    text = format_signal_message(forecast, signal, fundamentals, position_size)
                    await context.bot.send_message(chat_id=user_id, text=text, parse_mode="Markdown")

                    db.log_signal(
                        user_id, ticker, signal["action"],
                        forecast["current_price"],
                        {k: v.get("expected_return") for k, v in forecast["horizons"].items() if "error" not in v},
                        signal["confidence"],
                    )
            except Exception:
                logger.exception("Ошибка ежедневного анализа %s для user %s", ticker, user_id)


# ---------- Еженедельное переобучение (планировщик) ----------

async def weekly_retrain_job(context: ContextTypes.DEFAULT_TYPE):
    """
    Раз в неделю переобучает модели для всех тикеров, которые есть хотя бы
    у одного пользователя в watchlist, и обновляет кэш (model_store.py).
    Ежедневный анализ и /check в течение недели используют этот кэш —
    быстро, без повторного обучения RandomForest на каждый вызов.
    """
    logger.info("Запуск еженедельного переобучения моделей")
    tickers = set()
    for user_id in db.get_all_users():
        tickers.update(db.get_watchlist(user_id))

    for ticker in tickers:
        try:
            forecast_ticker(ticker, force_retrain=True)
            logger.info("Модель для %s переобучена", ticker)
        except Exception:
            logger.exception("Ошибка еженедельного переобучения %s", ticker)


# ---------- Запуск ----------

def main():
    if not TELEGRAM_TOKEN:
        raise RuntimeError("TELEGRAM_TOKEN не задан. Проверь .env файл")

    db.init_db()

    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("add", cmd_add))
    app.add_handler(CommandHandler("remove", cmd_remove))
    app.add_handler(CommandHandler("list", cmd_list))
    app.add_handler(CommandHandler("check", cmd_check))
    app.add_handler(CommandHandler("history", cmd_history))
    app.add_handler(CommandHandler("backtest", cmd_backtest))
    app.add_handler(CommandHandler("accuracy", cmd_accuracy))
    app.add_handler(CommandHandler("retrain", cmd_retrain))

    # Ежедневный запуск анализа в заданное время (время сервера!)
    app.job_queue.run_daily(
        daily_analysis_job,
        time=dtime(hour=DAILY_ANALYSIS_HOUR, minute=DAILY_ANALYSIS_MINUTE),
        name="daily_analysis",
    )

    # Еженедельное переобучение моделей — воскресенье, 03:00 (время сервера).
    # days: 0=понедельник ... 6=воскресенье (согласно python-telegram-bot JobQueue)
    app.job_queue.run_daily(
        weekly_retrain_job,
        time=dtime(hour=3, minute=0),
        days=(6,),
        name="weekly_retrain",
    )

    logger.info("Бот запущен")
    app.run_polling()


if __name__ == "__main__":
    main()
