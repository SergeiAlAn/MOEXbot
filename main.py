"""Точка входа: инициализация БД, планировщика и Telegram-бота."""

from __future__ import annotations

import asyncio
import logging
import sys

import database as db
from config import TELEGRAM_TOKEN, TEST_MODE
from scheduler import reschedule_interval_jobs, schedule_test_burst, setup_scheduler, scheduler
from telegram_bot import bot, dp
from utils import setup_logging

logger = logging.getLogger(__name__)


async def main() -> None:
    setup_logging()

    if not TELEGRAM_TOKEN:
        raise SystemExit(
            "Не задан TELEGRAM_TOKEN. Укажите его в файле MOEX_bot/.env"
        )

    await db.init_db()

    setup_scheduler()
    await reschedule_interval_jobs()
    await schedule_test_burst()
    scheduler.start()
    logger.info("Планировщик запущен (TEST_MODE=%s)", TEST_MODE)

    # aiogram 3 polling
    await dp.start_polling(bot)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logging.getLogger(__name__).info("Остановка бота")
        sys.exit(0)
