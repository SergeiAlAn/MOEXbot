"""Вспомогательные функции: время, форматирование, логирование."""

from __future__ import annotations

import logging
from datetime import date, datetime, time
from logging.handlers import RotatingFileHandler
from pathlib import Path

from config import LOG_DIR, LOG_FILE, MSK


def setup_logging() -> None:
    """Настраивает логирование в консоль и logs/bot.log."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger()
    if root.handlers:
        return

    root.setLevel(logging.INFO)
    fmt = logging.Formatter(
        "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    console = logging.StreamHandler()
    console.setFormatter(fmt)
    root.addHandler(console)

    file_handler = RotatingFileHandler(
        LOG_FILE,
        maxBytes=2_000_000,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setFormatter(fmt)
    root.addHandler(file_handler)


def now_msk() -> datetime:
    """Текущее время в Europe/Moscow (timezone-aware)."""
    return datetime.now(MSK)


def today_msk() -> date:
    return now_msk().date()


def parse_hhmm(value: str) -> time:
    hour, minute = value.strip().split(":")
    return time(hour=int(hour), minute=int(minute), tzinfo=MSK)


def format_date(d: date | datetime | None = None) -> str:
    if d is None:
        d = today_msk()
    if isinstance(d, datetime):
        d = d.astimezone(MSK).date()
    return d.strftime("%d.%m.%Y")


def format_number(value: float | None, digits: int = 2) -> str:
    if value is None:
        return "—"
    return f"{value:,.{digits}f}".replace(",", " ")


def format_volume(value: float | None) -> str:
    """Оборот в удобочитаемом виде (млрд / млн)."""
    if value is None:
        return "—"
    abs_v = abs(value)
    if abs_v >= 1_000_000_000:
        return f"{value / 1_000_000_000:.2f} млрд ₽"
    if abs_v >= 1_000_000:
        return f"{value / 1_000_000:.1f} млн ₽"
    return format_number(value, 0)


def format_signed(value: float | None, digits: int = 2) -> str:
    if value is None:
        return "—"
    sign = "+" if value > 0 else ""
    return f"{sign}{value:.{digits}f}"


def format_percent(value: float | None, digits: int = 2) -> str:
    if value is None:
        return "—"
    sign = "+" if value > 0 else ""
    return f"{sign}{value:.{digits}f}%"


def ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
