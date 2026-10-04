"""Конфигурация бота из переменных окружения."""

from __future__ import annotations

from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
import os

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

MSK = ZoneInfo("Europe/Moscow")

TELEGRAM_TOKEN: str = os.getenv("TELEGRAM_TOKEN", "").strip()
CHAT_ID: str = os.getenv("CHAT_ID", "").strip()

START_NOTIFICATION_TIME: str = os.getenv("START_NOTIFICATION_TIME", "10:00").strip()
END_NOTIFICATION_TIME: str = os.getenv("END_NOTIFICATION_TIME", "19:00").strip()
MIDNIGHT_NOTIFICATION_TIME: str = os.getenv("MIDNIGHT_NOTIFICATION_TIME", "00:00").strip()

DEFAULT_INTERVAL_MINUTES: int = int(os.getenv("DEFAULT_INTERVAL_MINUTES", "60"))
ALLOWED_INTERVALS = (30, 60, 120, 180, 240)

DEFAULT_ALERT_CHECK_MINUTES: int = int(os.getenv("DEFAULT_ALERT_CHECK_MINUTES", "30"))
ALLOWED_ALERT_INTERVALS = (5, 15, 30, 60)

TEST_MODE: bool = os.getenv("TEST_MODE", "false").strip().lower() in {"1", "true", "yes", "on"}

# Тикеры ISS:
# IMOEX  — индекс МосБиржи (основная сессия)
# IMOEX2 — индекс МосБиржи за все сессии (в сообщениях: MOEX2)
MOEX_SECID: str = os.getenv("MOEX_SECID", "IMOEX").strip()
MOEX2_SECID: str = os.getenv("MOEX2_SECID", "IMOEX2").strip()

DB_PATH = BASE_DIR / "data" / "moex_bot.db"
LOG_DIR = BASE_DIR / "logs"
LOG_FILE = LOG_DIR / "bot.log"

MOEX_ISS_BASE = "https://iss.moex.com/iss"
HTTP_TIMEOUT = 20
HTTP_RETRIES = 3
HTTP_RETRY_DELAY = 1.5
