"""Telegram-интерфейс: меню, callback-кнопки, котировки, алерты."""

from __future__ import annotations

import logging

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    Message,
)

import database as db
import messages
import moex_api
from chart import build_moex2_chart
from config import (
    DEFAULT_INTERVAL_MINUTES,
    END_NOTIFICATION_TIME,
    MIDNIGHT_NOTIFICATION_TIME,
    START_NOTIFICATION_TIME,
    TELEGRAM_TOKEN,
)
from keyboards import (
    BTN_ALERTS,
    BTN_NOTIFY,
    BTN_QUOTES,
    alert_check_interval_kb,
    alert_level_values_kb,
    alert_percent_values_kb,
    alerts_main_kb,
    main_menu_kb,
    notify_interval_kb,
    notify_settings_kb,
    quotes_actions_kb,
)

logger = logging.getLogger(__name__)

bot = Bot(token=TELEGRAM_TOKEN)
dp = Dispatcher()


async def send_html(chat_id: int, text: str) -> None:
    await bot.send_message(chat_id=chat_id, text=text, parse_mode="HTML")


async def send_html_with_chart(
    chat_id: int,
    text: str,
    chart_png: bytes | None,
) -> None:
    """Отправка уведомления: при наличии графика — фото с caption, иначе текст."""
    if chart_png:
        await bot.send_photo(
            chat_id=chat_id,
            photo=BufferedInputFile(chart_png, filename="moex2_24h.png"),
            caption=text,
            parse_mode="HTML",
        )
    else:
        await send_html(chat_id, text)


# ─── Технические команды ──────────────────────────────────────────────────


@dp.message(CommandStart())
async def cmd_start(message: Message) -> None:
    await db.upsert_user(message.chat.id, DEFAULT_INTERVAL_MINUTES)
    await message.answer(
        messages.format_welcome(message.chat.id),
        reply_markup=main_menu_kb(),
        parse_mode="HTML",
    )


@dp.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(
        messages.format_help(),
        reply_markup=main_menu_kb(),
        parse_mode="HTML",
    )


# ─── Главное меню (ReplyKeyboard) ──────────────────────────────────────────


@dp.message(F.text == BTN_QUOTES)
async def menu_quotes(message: Message) -> None:
    await db.upsert_user(message.chat.id)
    await _send_quotes(message)


@dp.message(F.text == BTN_ALERTS)
async def menu_alerts(message: Message) -> None:
    await db.upsert_user(message.chat.id)
    await _send_alerts_screen(message)


@dp.message(F.text == BTN_NOTIFY)
async def menu_notify(message: Message) -> None:
    await db.upsert_user(message.chat.id)
    await _send_notify_screen(message)


@dp.message(F.text & ~F.text.startswith("/"))
async def unknown_text(message: Message) -> None:
    await message.answer(
        "Используйте кнопки меню внизу экрана.",
        reply_markup=main_menu_kb(),
    )


# ─── Экраны ────────────────────────────────────────────────────────────────


async def _send_quotes(target: Message) -> None:
    wait = await target.answer("⏳ Загружаю котировки и график…")
    try:
        moex, moex2 = await moex_api.get_both_indices()
        text = messages.format_status(moex, moex2)
        candles = await moex_api.get_candles_24h(only_traded=True)
        prev_close, prev_day = await moex_api.get_official_prev_close()
        title = "MOEX2 · изм. к пред. закрытию"
        if prev_day:
            title = f"MOEX2 · к закрытию {prev_day.strftime('%d.%m.%Y')}"
        png = build_moex2_chart(candles, prev_close=prev_close, title=title)
        photo = BufferedInputFile(png, filename="moex2_24h.png")
        await target.answer_photo(
            photo=photo,
            caption=text,
            parse_mode="HTML",
            reply_markup=quotes_actions_kb(),
        )
    except Exception as exc:
        logger.exception("quotes failed")
        await target.answer(
            f"⚠️ Не удалось загрузить данные:\n<code>{exc}</code>",
            parse_mode="HTML",
            reply_markup=quotes_actions_kb(),
        )
    finally:
        try:
            await wait.delete()
        except Exception:
            pass


async def _send_alerts_screen(message: Message) -> None:
    alerts_map = await db.get_user_alerts_map(message.chat.id)
    settings = await db.get_alert_settings(message.chat.id)
    check = int(settings.get("check_interval_minutes") or 30)
    current = None
    try:
        moex2 = await moex_api.get_moex2()
        current = moex2.value
    except Exception:
        logger.exception("moex2 for alerts screen")
    await message.answer(
        messages.format_alerts_screen(alerts_map, check, current),
        reply_markup=alerts_main_kb(alerts_map, check),
        parse_mode="HTML",
    )


async def _edit_alerts_screen(callback: CallbackQuery) -> None:
    alerts_map = await db.get_user_alerts_map(callback.from_user.id)
    settings = await db.get_alert_settings(callback.from_user.id)
    check = int(settings.get("check_interval_minutes") or 30)
    current = None
    try:
        moex2 = await moex_api.get_moex2()
        current = moex2.value
    except Exception:
        pass
    await callback.message.edit_text(
        messages.format_alerts_screen(alerts_map, check, current),
        reply_markup=alerts_main_kb(alerts_map, check),
        parse_mode="HTML",
    )


async def _send_notify_screen(message: Message) -> None:
    user = await db.get_user(message.chat.id)
    assert user is not None
    trading = None
    last_day = user.get("last_trading_day")
    if last_day:
        trading = bool(user.get("trading_today"))
    await message.answer(
        messages.format_settings(
            chat_id=message.chat.id,
            interval=int(user["interval_minutes"]),
            start=START_NOTIFICATION_TIME,
            end=END_NOTIFICATION_TIME,
            midnight=MIDNIGHT_NOTIFICATION_TIME,
            trading_today=trading,
            last_trading_day=last_day,
            notify_morning=bool(user.get("notify_morning", 1)),
            notify_interval=bool(user.get("notify_interval", 1)),
            notify_evening=bool(user.get("notify_evening", 1)),
            notify_midnight=bool(user.get("notify_midnight", 1)),
        ),
        reply_markup=notify_settings_kb(user),
        parse_mode="HTML",
    )


async def _edit_notify_screen(callback: CallbackQuery) -> None:
    user = await db.get_user(callback.from_user.id)
    assert user is not None
    trading = None
    last_day = user.get("last_trading_day")
    if last_day:
        trading = bool(user.get("trading_today"))
    await callback.message.edit_text(
        messages.format_settings(
            chat_id=callback.from_user.id,
            interval=int(user["interval_minutes"]),
            start=START_NOTIFICATION_TIME,
            end=END_NOTIFICATION_TIME,
            midnight=MIDNIGHT_NOTIFICATION_TIME,
            trading_today=trading,
            last_trading_day=last_day,
            notify_morning=bool(user.get("notify_morning", 1)),
            notify_interval=bool(user.get("notify_interval", 1)),
            notify_evening=bool(user.get("notify_evening", 1)),
            notify_midnight=bool(user.get("notify_midnight", 1)),
        ),
        reply_markup=notify_settings_kb(user),
        parse_mode="HTML",
    )


# ─── Callbacks: котировки ──────────────────────────────────────────────────


@dp.callback_query(F.data == "noop")
async def cb_noop(callback: CallbackQuery) -> None:
    await callback.answer()


@dp.callback_query(F.data == "quotes:refresh")
async def cb_quotes_refresh(callback: CallbackQuery) -> None:
    await callback.answer("Обновляю…")
    # Новое сообщение с актуальными данными (фото нельзя надёжно «перерисовать» caption+image)
    await _send_quotes(callback.message)


# ─── Callbacks: уведомления ────────────────────────────────────────────────


@dp.callback_query(F.data.startswith("notify:toggle:"))
async def cb_notify_toggle(callback: CallbackQuery) -> None:
    flag = callback.data.split(":")[-1]
    await db.toggle_notify_flag(callback.from_user.id, flag)
    await _edit_notify_screen(callback)
    await callback.answer("Сохранено")


@dp.callback_query(F.data == "notify:interval_menu")
async def cb_notify_interval_menu(callback: CallbackQuery) -> None:
    user = await db.get_user(callback.from_user.id)
    current = int(user["interval_minutes"]) if user else DEFAULT_INTERVAL_MINUTES
    await callback.message.edit_text(
        "⏱ <b>Интервал промежуточных уведомлений</b>\n\nВыберите значение:",
        reply_markup=notify_interval_kb(current),
        parse_mode="HTML",
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("notify:set_interval:"))
async def cb_notify_set_interval(callback: CallbackQuery) -> None:
    minutes = int(callback.data.split(":")[-1])
    await db.set_interval(callback.from_user.id, minutes)
    from scheduler import reschedule_interval_jobs

    await reschedule_interval_jobs()
    await _edit_notify_screen(callback)
    await callback.answer(f"Интервал: {minutes} мин")


@dp.callback_query(F.data == "notify:back")
async def cb_notify_back(callback: CallbackQuery) -> None:
    await _edit_notify_screen(callback)
    await callback.answer()


# ─── Callbacks: алерты ─────────────────────────────────────────────────────


@dp.callback_query(F.data == "alert:back")
async def cb_alert_back(callback: CallbackQuery) -> None:
    await _edit_alerts_screen(callback)
    await callback.answer()


@dp.callback_query(F.data == "alert:menu:level")
async def cb_alert_menu_level(callback: CallbackQuery) -> None:
    try:
        moex2 = await moex_api.get_moex2()
        current = float(moex2.value or 0)
    except Exception as exc:
        await callback.answer(f"Ошибка MOEX: {exc}", show_alert=True)
        return
    await callback.message.edit_text(
        "🎯 <b>Алерт по уровню</b>\n\n"
        f"Сейчас MOEX2: <b>{current:.2f}</b>\n"
        "Выберите цель шагом <b>±50</b> пунктов.\n"
        "Можно задать <b>два</b> алерта: вверх и вниз.",
        reply_markup=alert_level_values_kb(current),
        parse_mode="HTML",
    )
    await callback.answer()


@dp.callback_query(F.data == "alert:menu:percent")
async def cb_alert_menu_percent(callback: CallbackQuery) -> None:
    try:
        moex2 = await moex_api.get_moex2()
        current = float(moex2.value or 0)
    except Exception as exc:
        await callback.answer(f"Ошибка MOEX: {exc}", show_alert=True)
        return
    await callback.message.edit_text(
        "📉 <b>Алерт по %</b>\n\n"
        f"База (сейчас): <b>{current:.2f}</b>\n"
        "Выберите порог шагом <b>±0.5%</b>.\n"
        "Можно задать <b>два</b> алерта: рост и падение.",
        reply_markup=alert_percent_values_kb(current),
        parse_mode="HTML",
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("alert:set_level:"))
async def cb_alert_set_level(callback: CallbackQuery) -> None:
    # alert:set_level:{above|below}:{level}
    parts = callback.data.split(":")
    direction = parts[2]
    level = float(parts[3])
    slot = "level_above" if direction == "above" else "level_below"
    await db.upsert_alert_slot(
        callback.from_user.id,
        slot=slot,
        alert_type="level",
        direction=direction,
        target_value=level,
        baseline_value=None,
    )
    await _edit_alerts_screen(callback)
    await callback.answer(f"Уровень {direction}: {level:.2f}")


@dp.callback_query(F.data.startswith("alert:set_pct:"))
async def cb_alert_set_pct(callback: CallbackQuery) -> None:
    # alert:set_pct:{above|below}:{pct}
    parts = callback.data.split(":")
    direction = parts[2]
    pct = float(parts[3])
    slot = "pct_above" if direction == "above" else "pct_below"
    try:
        moex2 = await moex_api.get_moex2()
        baseline = float(moex2.value or 0)
    except Exception as exc:
        await callback.answer(f"Ошибка MOEX: {exc}", show_alert=True)
        return
    await db.upsert_alert_slot(
        callback.from_user.id,
        slot=slot,
        alert_type="percent",
        direction=direction,
        target_value=pct,
        baseline_value=baseline,
    )
    await _edit_alerts_screen(callback)
    await callback.answer(f"% {direction}: {pct:g}%")


@dp.callback_query(F.data.startswith("alert:clear:"))
async def cb_alert_clear(callback: CallbackQuery) -> None:
    slot = callback.data.split(":")[-1]
    await db.clear_alert_slot(callback.from_user.id, slot)
    await _edit_alerts_screen(callback)
    await callback.answer("Алерт удалён")


@dp.callback_query(F.data == "alert:check_menu")
async def cb_alert_check_menu(callback: CallbackQuery) -> None:
    settings = await db.get_alert_settings(callback.from_user.id)
    current = int(settings.get("check_interval_minutes") or 30)
    await callback.message.edit_text(
        "⏱ <b>Частота проверки MOEX2</b>\n\n"
        "Как часто сверять все активные алерты:",
        reply_markup=alert_check_interval_kb(current),
        parse_mode="HTML",
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("alert:set_check:"))
async def cb_alert_set_check(callback: CallbackQuery) -> None:
    minutes = int(callback.data.split(":")[-1])
    await db.set_alert_check_interval(callback.from_user.id, minutes)
    await _edit_alerts_screen(callback)
    await callback.answer(f"Проверка каждые {minutes} мин")
