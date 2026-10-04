"""Расписание уведомлений и проверка алертов (APScheduler, Europe/Moscow)."""

from __future__ import annotations

import logging
from datetime import date, timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger

import database as db
import messages
import moex_api
from chart import render_moex2_chart_png
from config import (
    END_NOTIFICATION_TIME,
    MIDNIGHT_NOTIFICATION_TIME,
    MSK,
    START_NOTIFICATION_TIME,
    TEST_MODE,
)
from telegram_bot import send_html, send_html_with_chart
from utils import now_msk, parse_hhmm

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler(timezone=MSK)


async def _recipients() -> list[dict]:
    users = await db.get_all_users()
    if not users:
        logger.warning("Нет зарегистрированных пользователей")
    return users


async def _safe_send(
    chat_id: int,
    text: str,
    *,
    notif_type: str,
    notif_key: str = "",
    day: date | None = None,
    chart_png: bytes | None = None,
) -> bool:
    """Отправляет сообщение один раз (антидубль). Опционально с графиком."""
    day = day or now_msk().date()
    if not await db.mark_sent(chat_id, day, notif_type, notif_key):
        logger.info("Пропуск дубля %s/%s для %s", notif_type, notif_key, chat_id)
        return False
    try:
        if chart_png is not None:
            await send_html_with_chart(chat_id, text, chart_png)
        else:
            await send_html(chat_id, text)
        return True
    except Exception:
        logger.exception("Ошибка отправки в chat_id=%s", chat_id)
        return False


def _user_wants(user: dict, kind: str) -> bool:
    return bool(user.get(f"notify_{kind}", 1))


async def job_morning() -> None:
    today = now_msk().date()
    logger.info("Утренняя задача %s", today)

    try:
        trading = await moex_api.is_trading_day(today)
    except Exception:
        logger.exception("Не удалось определить торговый день")
        trading = True

    chart_png = await render_moex2_chart_png() if trading else None

    for user in await _recipients():
        chat_id = user["chat_id"]
        await db.set_trading_day_state(chat_id, today, trading)

        if not trading:
            if _user_wants(user, "morning"):
                await _safe_send(
                    chat_id,
                    messages.format_no_trading(),
                    notif_type="no_trading",
                    day=today,
                )
            continue

        if not _user_wants(user, "morning"):
            continue

        try:
            moex, moex2 = await moex_api.get_both_indices()
            text = messages.format_morning_moex2(moex, moex2)
        except Exception as exc:
            text = f"⚠️ Ошибка получения утренних данных:\n<code>{exc}</code>"

        await _safe_send(
            chat_id,
            text,
            notif_type="morning",
            day=today,
            chart_png=chart_png,
        )


async def job_interval() -> None:
    """Промежуточные котировки с графиком MOEX2."""
    now = now_msk()
    today = now.date()
    start = parse_hhmm(START_NOTIFICATION_TIME)
    end = parse_hhmm(END_NOTIFICATION_TIME)
    current_t = now.timetz().replace(tzinfo=MSK)

    if not (start < current_t < end):
        logger.info("Интервальная задача вне окна — пропуск")
        return

    minutes_now = now.hour * 60 + now.minute
    quotes = None
    chart_png: bytes | None = None
    chart_loaded = False

    for user in await _recipients():
        chat_id = user["chat_id"]
        if not _user_wants(user, "interval"):
            continue
        if not await db.is_trading_today(chat_id, today):
            continue

        interval = int(user["interval_minutes"])
        if minutes_now % interval != 0:
            continue

        slot_key = f"{now.hour:02d}:{now.minute:02d}"
        if slot_key in {START_NOTIFICATION_TIME, END_NOTIFICATION_TIME}:
            continue

        if quotes is None:
            try:
                quotes = await moex_api.get_both_indices()
            except Exception as exc:
                text = f"⚠️ Ошибка получения котировок:\n<code>{exc}</code>"
                await _safe_send(
                    chat_id,
                    text,
                    notif_type="interval",
                    notif_key=slot_key,
                    day=today,
                )
                continue

        if not chart_loaded:
            chart_png = await render_moex2_chart_png()
            chart_loaded = True

        moex, moex2 = quotes
        text = messages.format_regular(moex, moex2)
        await _safe_send(
            chat_id,
            text,
            notif_type="interval",
            notif_key=slot_key,
            day=today,
            chart_png=chart_png,
        )


async def job_evening() -> None:
    today = now_msk().date()
    chart_png = await render_moex2_chart_png()
    for user in await _recipients():
        chat_id = user["chat_id"]
        if not _user_wants(user, "evening"):
            continue
        if not await db.is_trading_today(chat_id, today):
            continue
        try:
            moex, moex2 = await moex_api.get_both_indices()
            text = messages.format_day_session(moex, moex2)
        except Exception as exc:
            text = f"⚠️ Ошибка итогов дня:\n<code>{exc}</code>"
        await _safe_send(
            chat_id,
            text,
            notif_type="evening",
            day=today,
            chart_png=chart_png,
        )


async def job_midnight() -> None:
    finished_day = (now_msk() - timedelta(minutes=1)).date()
    chart_png = await render_moex2_chart_png()
    for user in await _recipients():
        chat_id = user["chat_id"]
        if not _user_wants(user, "midnight"):
            continue
        user_row = await db.get_user(chat_id)
        if (
            user_row
            and user_row.get("last_trading_day") == finished_day.isoformat()
            and not user_row.get("trading_today")
        ):
            continue
        try:
            moex, moex2 = await moex_api.get_both_indices()
            text = messages.format_midnight(moex, moex2)
        except Exception as exc:
            text = f"⚠️ Ошибка ночных итогов:\n<code>{exc}</code>"
        await _safe_send(
            chat_id,
            text,
            notif_type="midnight",
            day=finished_day,
            chart_png=chart_png,
        )


def _alert_condition_met(alert: dict, value: float) -> bool:
    a_type = alert.get("alert_type")
    target = alert.get("target_value")
    direction = alert.get("direction") or "above"
    if target is None or value is None:
        return False

    if a_type == "level":
        if direction == "above":
            return value >= float(target)
        if direction == "below":
            return value <= float(target)
        return False

    if a_type == "percent":
        baseline = alert.get("baseline_value")
        if not baseline:
            return False
        change_pct = (value - float(baseline)) / float(baseline) * 100.0
        thr = float(target)
        if direction == "above":
            return change_pct >= thr
        if direction == "below":
            return change_pct <= -thr
    return False


async def job_alerts() -> None:
    """Проверка до 4 алертов на пользователя (уровень ↑/↓ и % ↑/↓)."""
    alerts = await db.get_all_enabled_alerts()
    if not alerts:
        return

    due = [a for a in alerts if db.alert_due(a)]
    if not due:
        return

    try:
        moex2 = await moex_api.get_moex2()
        value = float(moex2.value or 0)
    except Exception:
        logger.exception("Алерты: не удалось получить MOEX2")
        return

    for alert in due:
        alert_id = int(alert["id"])
        chat_id = int(alert["chat_id"])
        triggered = _alert_condition_met(alert, value)
        await db.mark_alert_checked(alert_id, triggered=triggered)
        if not triggered:
            continue

        text = messages.format_alert_triggered(
            alert_type=str(alert.get("alert_type")),
            value=value,
            target=float(alert["target_value"]),
            direction=str(alert.get("direction")),
            baseline=(
                float(alert["baseline_value"])
                if alert.get("baseline_value") is not None
                else None
            ),
            slot=str(alert.get("slot") or ""),
        )
        try:
            await send_html(chat_id, text)
        except Exception:
            logger.exception("Не удалось отправить алерт chat_id=%s", chat_id)
        # Отключаем только сработавший слот
        await db.disable_alert_by_id(alert_id)
        logger.info(
            "Алерт id=%s slot=%s сработал для %s, value=%s",
            alert_id,
            alert.get("slot"),
            chat_id,
            value,
        )


def _cron_hhmm(hhmm: str) -> CronTrigger:
    t = parse_hhmm(hhmm)
    return CronTrigger(hour=t.hour, minute=t.minute, timezone=MSK)


async def reschedule_interval_jobs() -> None:
    if scheduler.get_job("interval_tick"):
        scheduler.remove_job("interval_tick")

    start = parse_hhmm(START_NOTIFICATION_TIME)
    end = parse_hhmm(END_NOTIFICATION_TIME)
    hour_expr = (
        f"{start.hour}-{end.hour}"
        if start.hour <= end.hour
        else f"{start.hour}-23,0-{end.hour}"
    )

    scheduler.add_job(
        job_interval,
        CronTrigger(minute="0,30", hour=hour_expr, timezone=MSK),
        id="interval_tick",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    logger.info("Интервальная задача: проверка каждые 30 минут")


def setup_scheduler() -> AsyncIOScheduler:
    scheduler.add_job(
        job_morning,
        _cron_hhmm(START_NOTIFICATION_TIME),
        id="morning",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        job_evening,
        _cron_hhmm(END_NOTIFICATION_TIME),
        id="evening",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        job_midnight,
        _cron_hhmm(MIDNIGHT_NOTIFICATION_TIME),
        id="midnight",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        job_alerts,
        CronTrigger(minute="*", timezone=MSK),
        id="alerts_tick",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    return scheduler


async def run_test_jobs() -> None:
    logger.info("TEST_MODE: запуск демонстрационных задач")
    await job_morning()
    await job_interval()
    await job_evening()
    await job_alerts()
    logger.info("TEST_MODE: готово")


async def schedule_test_burst() -> None:
    if not TEST_MODE:
        return
    run_at = now_msk() + timedelta(seconds=3)
    scheduler.add_job(
        run_test_jobs,
        DateTrigger(run_date=run_at, timezone=MSK),
        id="test_burst",
        replace_existing=True,
    )
