"""SQLite-хранилище настроек пользователя, алертов и антидублей."""

from __future__ import annotations

import aiosqlite
from datetime import date, datetime
from typing import Any

from config import (
    CHAT_ID,
    DB_PATH,
    DEFAULT_ALERT_CHECK_MINUTES,
    DEFAULT_INTERVAL_MINUTES,
)
from utils import ensure_parent, now_msk


async def init_db() -> None:
    ensure_parent(DB_PATH)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                chat_id INTEGER PRIMARY KEY,
                interval_minutes INTEGER NOT NULL,
                notify_morning INTEGER NOT NULL DEFAULT 1,
                notify_interval INTEGER NOT NULL DEFAULT 1,
                notify_evening INTEGER NOT NULL DEFAULT 1,
                notify_midnight INTEGER NOT NULL DEFAULT 1,
                last_trading_day TEXT,
                trading_today INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS alert_settings (
                chat_id INTEGER PRIMARY KEY,
                check_interval_minutes INTEGER NOT NULL DEFAULT 30,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS user_alerts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                slot TEXT NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 1,
                alert_type TEXT NOT NULL,
                direction TEXT NOT NULL,
                target_value REAL NOT NULL,
                baseline_value REAL,
                last_triggered_at TEXT,
                last_checked_at TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(chat_id, slot)
            )
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS sent_notifications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                notif_date TEXT NOT NULL,
                notif_type TEXT NOT NULL,
                notif_key TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(chat_id, notif_date, notif_type, notif_key)
            )
            """
        )
        # Миграции для уже существующих БД
        for col, ddl in [
            ("notify_morning", "INTEGER NOT NULL DEFAULT 1"),
            ("notify_interval", "INTEGER NOT NULL DEFAULT 1"),
            ("notify_evening", "INTEGER NOT NULL DEFAULT 1"),
            ("notify_midnight", "INTEGER NOT NULL DEFAULT 1"),
        ]:
            try:
                await db.execute(f"ALTER TABLE users ADD COLUMN {col} {ddl}")
            except aiosqlite.OperationalError:
                pass
        await db.commit()

        if CHAT_ID:
            await upsert_user(int(CHAT_ID), DEFAULT_INTERVAL_MINUTES)


async def upsert_user(chat_id: int, interval_minutes: int | None = None) -> None:
    interval = interval_minutes if interval_minutes is not None else DEFAULT_INTERVAL_MINUTES
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO users (chat_id, interval_minutes)
            VALUES (?, ?)
            ON CONFLICT(chat_id) DO UPDATE SET
                updated_at = CURRENT_TIMESTAMP
            """,
            (chat_id, interval),
        )
        await db.execute(
            """
            INSERT INTO alert_settings (chat_id, check_interval_minutes)
            VALUES (?, ?)
            ON CONFLICT(chat_id) DO NOTHING
            """,
            (chat_id, DEFAULT_ALERT_CHECK_MINUTES),
        )
        await db.commit()


async def get_user(chat_id: int) -> dict[str, Any] | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM users WHERE chat_id = ?", (chat_id,))
        row = await cur.fetchone()
        return dict(row) if row else None


async def get_all_users() -> list[dict[str, Any]]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM users")
        rows = await cur.fetchall()
        return [dict(r) for r in rows]


async def set_interval(chat_id: int, minutes: int) -> None:
    await upsert_user(chat_id)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            UPDATE users
            SET interval_minutes = ?, updated_at = CURRENT_TIMESTAMP
            WHERE chat_id = ?
            """,
            (minutes, chat_id),
        )
        await db.commit()


async def toggle_notify_flag(chat_id: int, flag: str) -> bool:
    """Переключает notify_* флаг. Возвращает новое значение."""
    allowed = {
        "morning": "notify_morning",
        "interval": "notify_interval",
        "evening": "notify_evening",
        "midnight": "notify_midnight",
    }
    column = allowed[flag]
    await upsert_user(chat_id)
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(f"SELECT {column} FROM users WHERE chat_id = ?", (chat_id,))
        row = await cur.fetchone()
        new_val = 0 if row and row[0] else 1
        await db.execute(
            f"UPDATE users SET {column} = ?, updated_at = CURRENT_TIMESTAMP WHERE chat_id = ?",
            (new_val, chat_id),
        )
        await db.commit()
        return bool(new_val)


async def set_trading_day_state(
    chat_id: int,
    trading_day: date,
    trading_today: bool,
) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            UPDATE users
            SET last_trading_day = ?,
                trading_today = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE chat_id = ?
            """,
            (trading_day.isoformat(), int(trading_today), chat_id),
        )
        await db.commit()


async def is_trading_today(chat_id: int, day: date) -> bool:
    user = await get_user(chat_id)
    if not user:
        return True
    if user.get("last_trading_day") != day.isoformat():
        return True
    return bool(user.get("trading_today", 1))


async def mark_sent(
    chat_id: int,
    notif_date: date,
    notif_type: str,
    notif_key: str = "",
) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        try:
            await db.execute(
                """
                INSERT INTO sent_notifications
                    (chat_id, notif_date, notif_type, notif_key)
                VALUES (?, ?, ?, ?)
                """,
                (chat_id, notif_date.isoformat(), notif_type, notif_key),
            )
            await db.commit()
            return True
        except aiosqlite.IntegrityError:
            return False


# ─── Алерты (до 4 слотов на пользователя) ─────────────────────────────────
# slot: level_above | level_below | pct_above | pct_below

ALERT_SLOTS = ("level_above", "level_below", "pct_above", "pct_below")


async def get_alert_settings(chat_id: int) -> dict[str, Any]:
    await upsert_user(chat_id)
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT * FROM alert_settings WHERE chat_id = ?",
            (chat_id,),
        )
        row = await cur.fetchone()
        if row:
            return dict(row)
        return {
            "chat_id": chat_id,
            "check_interval_minutes": DEFAULT_ALERT_CHECK_MINUTES,
        }


async def get_user_alerts(chat_id: int) -> list[dict[str, Any]]:
    await upsert_user(chat_id)
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            """
            SELECT * FROM user_alerts
            WHERE chat_id = ? AND enabled = 1
            ORDER BY slot
            """,
            (chat_id,),
        )
        rows = await cur.fetchall()
        return [dict(r) for r in rows]


async def get_user_alerts_map(chat_id: int) -> dict[str, dict[str, Any]]:
    """Все активные алерты пользователя: slot → запись."""
    alerts = await get_user_alerts(chat_id)
    return {a["slot"]: a for a in alerts}


async def get_all_enabled_alerts() -> list[dict[str, Any]]:
    """Все включённые алерты + интервал проверки из alert_settings."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            """
            SELECT a.*,
                   COALESCE(s.check_interval_minutes, ?) AS check_interval_minutes
            FROM user_alerts a
            LEFT JOIN alert_settings s ON s.chat_id = a.chat_id
            WHERE a.enabled = 1
            """,
            (DEFAULT_ALERT_CHECK_MINUTES,),
        )
        rows = await cur.fetchall()
        return [dict(r) for r in rows]


async def upsert_alert_slot(
    chat_id: int,
    *,
    slot: str,
    alert_type: str,
    direction: str,
    target_value: float,
    baseline_value: float | None = None,
) -> None:
    """Создаёт или заменяет алерт в слоте (вверх/вниз × уровень/%)."""
    if slot not in ALERT_SLOTS:
        raise ValueError(f"Неизвестный слот алерта: {slot}")
    await upsert_user(chat_id)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO user_alerts (
                chat_id, slot, enabled, alert_type, direction,
                target_value, baseline_value, last_triggered_at, last_checked_at,
                updated_at
            ) VALUES (?, ?, 1, ?, ?, ?, ?, NULL, NULL, CURRENT_TIMESTAMP)
            ON CONFLICT(chat_id, slot) DO UPDATE SET
                enabled = 1,
                alert_type = excluded.alert_type,
                direction = excluded.direction,
                target_value = excluded.target_value,
                baseline_value = excluded.baseline_value,
                last_triggered_at = NULL,
                last_checked_at = NULL,
                updated_at = CURRENT_TIMESTAMP
            """,
            (chat_id, slot, alert_type, direction, target_value, baseline_value),
        )
        await db.commit()


async def clear_alert_slot(chat_id: int, slot: str) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "DELETE FROM user_alerts WHERE chat_id = ? AND slot = ?",
            (chat_id, slot),
        )
        await db.commit()


async def disable_alert_by_id(alert_id: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            UPDATE user_alerts
            SET enabled = 0, last_triggered_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (alert_id,),
        )
        await db.commit()


async def set_alert_check_interval(chat_id: int, minutes: int) -> None:
    await upsert_user(chat_id)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO alert_settings (chat_id, check_interval_minutes)
            VALUES (?, ?)
            ON CONFLICT(chat_id) DO UPDATE SET
                check_interval_minutes = excluded.check_interval_minutes,
                updated_at = CURRENT_TIMESTAMP
            """,
            (chat_id, minutes),
        )
        await db.commit()


async def mark_alert_checked(alert_id: int, triggered: bool = False) -> None:
    now = now_msk().isoformat(timespec="seconds")
    async with aiosqlite.connect(DB_PATH) as db:
        if triggered:
            await db.execute(
                """
                UPDATE user_alerts
                SET last_checked_at = ?, last_triggered_at = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (now, now, alert_id),
            )
        else:
            await db.execute(
                """
                UPDATE user_alerts
                SET last_checked_at = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (now, alert_id),
            )
        await db.commit()


def alert_due(alert: dict[str, Any]) -> bool:
    """Пора ли проверять алерт по интервалу пользователя."""
    last = alert.get("last_checked_at")
    interval = int(alert.get("check_interval_minutes") or DEFAULT_ALERT_CHECK_MINUTES)
    if not last:
        return True
    try:
        last_dt = datetime.fromisoformat(last)
        if last_dt.tzinfo is None:
            from config import MSK

            last_dt = last_dt.replace(tzinfo=MSK)
        return (now_msk() - last_dt).total_seconds() >= interval * 60
    except ValueError:
        return True
