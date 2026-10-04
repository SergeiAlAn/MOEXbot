"""Клавиатуры Telegram-интерфейса (Reply + Inline)."""

from __future__ import annotations

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

from config import ALLOWED_ALERT_INTERVALS, ALLOWED_INTERVALS

# Reply menu labels
BTN_QUOTES = "📊 Текущие котировки"
BTN_ALERTS = "🔔 Настройки алертов"
BTN_NOTIFY = "⚙️ Параметры уведомлений"


def main_menu_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=BTN_QUOTES)],
            [KeyboardButton(text=BTN_ALERTS)],
            [KeyboardButton(text=BTN_NOTIFY)],
        ],
        resize_keyboard=True,
        is_persistent=True,
        input_field_placeholder="Выберите раздел меню…",
    )


def quotes_actions_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🔄 Обновить", callback_data="quotes:refresh"),
            ]
        ]
    )


def _on(flag: bool) -> str:
    return "✅" if flag else "⬜️"


def notify_settings_kb(user: dict) -> InlineKeyboardMarkup:
    interval = int(user.get("interval_minutes") or 60)
    rows = [
        [
            InlineKeyboardButton(
                text=f"{_on(bool(user.get('notify_morning', 1)))} Утро 10:00",
                callback_data="notify:toggle:morning",
            ),
            InlineKeyboardButton(
                text=f"{_on(bool(user.get('notify_interval', 1)))} Интервал",
                callback_data="notify:toggle:interval",
            ),
        ],
        [
            InlineKeyboardButton(
                text=f"{_on(bool(user.get('notify_evening', 1)))} Вечер 19:00",
                callback_data="notify:toggle:evening",
            ),
            InlineKeyboardButton(
                text=f"{_on(bool(user.get('notify_midnight', 1)))} Полночь",
                callback_data="notify:toggle:midnight",
            ),
        ],
        [InlineKeyboardButton(text="⏱ Интервал рассылки", callback_data="notify:interval_menu")],
        [
            InlineKeyboardButton(
                text=f"Сейчас: каждые {interval} мин",
                callback_data="noop",
            )
        ],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def notify_interval_kb(current: int) -> InlineKeyboardMarkup:
    row: list[InlineKeyboardButton] = []
    rows: list[list[InlineKeyboardButton]] = []
    for m in ALLOWED_INTERVALS:
        mark = "• " if m == current else ""
        row.append(
            InlineKeyboardButton(
                text=f"{mark}{m}м",
                callback_data=f"notify:set_interval:{m}",
            )
        )
        if len(row) == 3:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton(text="◀️ Назад", callback_data="notify:back")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def alerts_main_kb(
    alerts_map: dict,
    check_minutes: int,
) -> InlineKeyboardMarkup:
    def slot_btn(slot: str, title: str) -> InlineKeyboardButton:
        a = alerts_map.get(slot)
        if a:
            return InlineKeyboardButton(
                text=f"❌ {title}",
                callback_data=f"alert:clear:{slot}",
            )
        return InlineKeyboardButton(text=f"— {title}", callback_data="noop")

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🎯 Уровни ±50", callback_data="alert:menu:level"),
                InlineKeyboardButton(text="📉 Проценты ±0.5%", callback_data="alert:menu:percent"),
            ],
            [
                slot_btn("level_above", "Уровень ↑"),
                slot_btn("level_below", "Уровень ↓"),
            ],
            [
                slot_btn("pct_above", "% ↑"),
                slot_btn("pct_below", "% ↓"),
            ],
            [
                InlineKeyboardButton(
                    text=f"⏱ Проверка: {check_minutes} мин",
                    callback_data="alert:check_menu",
                )
            ],
        ]
    )


def alert_level_values_kb(current: float) -> InlineKeyboardMarkup:
    """
    5 уровней вверх и 5 вниз от ближайших кратных 50.

    Пример при 2120: вверх 2150…2350, вниз 2100…1900.
    """
    import math

    # Ближайший кратный 50 вверх / вниз
    up_first = int(math.ceil(current / 50.0) * 50)
    down_first = int(math.floor(current / 50.0) * 50)

    up_levels = [up_first + 50 * i for i in range(5)]
    down_levels = [down_first - 50 * i for i in range(5)]

    rows: list[list[InlineKeyboardButton]] = [
        [InlineKeyboardButton(text="⬇️ Вниз (шаг 50)", callback_data="noop")],
    ]
    row: list[InlineKeyboardButton] = []
    for level in down_levels:
        row.append(
            InlineKeyboardButton(
                text=f"{level}",
                callback_data=f"alert:set_level:below:{float(level)}",
            )
        )
        if len(row) == 5:
            rows.append(row)
            row = []
    if row:
        rows.append(row)

    rows.append([InlineKeyboardButton(text="⬆️ Вверх (шаг 50)", callback_data="noop")])
    row = []
    for level in up_levels:
        row.append(
            InlineKeyboardButton(
                text=f"{level}",
                callback_data=f"alert:set_level:above:{float(level)}",
            )
        )
        if len(row) == 5:
            rows.append(row)
            row = []
    if row:
        rows.append(row)

    rows.append(
        [
            InlineKeyboardButton(
                text=f"Сейчас {current:.2f}",
                callback_data="noop",
            )
        ]
    )
    rows.append([InlineKeyboardButton(text="◀️ Назад", callback_data="alert:back")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def alert_percent_values_kb(current: float) -> InlineKeyboardMarkup:
    """
    10 кнопок: −2.5…−0.5% и +0.5…+2.5% шагом 0.5% от текущего.
    """
    down = (-2.5, -2.0, -1.5, -1.0, -0.5)
    up = (0.5, 1.0, 1.5, 2.0, 2.5)
    rows: list[list[InlineKeyboardButton]] = [
        [InlineKeyboardButton(text="⬇️ Падение от текущей", callback_data="noop")],
    ]
    row = []
    for p in down:
        row.append(
            InlineKeyboardButton(
                text=f"{p:g}%",
                callback_data=f"alert:set_pct:below:{abs(p)}",
            )
        )
    rows.append(row)
    rows.append([InlineKeyboardButton(text="⬆️ Рост от текущей", callback_data="noop")])
    row = []
    for p in up:
        row.append(
            InlineKeyboardButton(
                text=f"+{p:g}%",
                callback_data=f"alert:set_pct:above:{p}",
            )
        )
    rows.append(row)
    rows.append(
        [
            InlineKeyboardButton(
                text=f"База {current:.2f}",
                callback_data="noop",
            )
        ]
    )
    rows.append([InlineKeyboardButton(text="◀️ Назад", callback_data="alert:back")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def alert_check_interval_kb(current: int) -> InlineKeyboardMarkup:
    row = []
    for m in ALLOWED_ALERT_INTERVALS:
        mark = "• " if m == current else ""
        row.append(
            InlineKeyboardButton(
                text=f"{mark}{m}м",
                callback_data=f"alert:set_check:{m}",
            )
        )
    return InlineKeyboardMarkup(
        inline_keyboard=[
            row,
            [InlineKeyboardButton(text="◀️ Назад", callback_data="alert:back")],
        ]
    )
