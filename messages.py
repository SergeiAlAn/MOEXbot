"""Формирование текстов уведомлений."""

from __future__ import annotations

from moex_api import IndexQuote
from utils import format_date, format_number, format_percent, format_signed, format_volume


def _block(quote: IndexQuote, *, change_caption: str | None = None, extras: bool = False) -> str:
    caption = change_caption if change_caption is not None else (quote.caption or "")
    lines = [
        f"<b>{quote.display_name}</b>",
        "━━━━━━━━",
        f"Значение: <b>{format_number(quote.value)}</b>",
        f"Изменение: <b>{format_signed(quote.change)}</b>",
        f"Изменение, %: <b>{format_percent(quote.change_pct)}</b>",
    ]
    if extras:
        lines.append(f"Мин. за день: <b>{format_number(quote.low)}</b>")
        lines.append(f"Макс. за день: <b>{format_number(quote.high)}</b>")
        lines.append(f"Объём торгов: <b>{format_volume(quote.volume)}</b>")
    if caption:
        lines.append(f"<i>{caption}</i>")
    return "\n".join(lines)


def _pair(moex: IndexQuote, moex2: IndexQuote, *, header: str, date_line: str | None = None) -> str:
    """MOEX2 всегда первым, затем MOEX."""
    parts = [header, ""]
    if date_line:
        parts.append(date_line)
        parts.append("")
    parts.append(_block(moex2, extras=True))
    parts.append("")
    parts.append(_block(moex, extras=False))
    return "\n".join(parts)


def format_regular(moex: IndexQuote, moex2: IndexQuote) -> str:
    return _pair(
        moex,
        moex2,
        header="📈 <b>Индексы МосБиржи</b>",
        date_line=f"Дата: {format_date()}\nСессия: <b>{moex2.session_name}</b>",
    )


def format_morning_moex2(moex: IndexQuote, moex2: IndexQuote) -> str:
    return _pair(
        moex,
        moex2,
        header="🌅 <b>Утренняя сессия MOEX2</b>",
        date_line=f"Дата: {format_date()}",
    )


def format_day_session(moex: IndexQuote, moex2: IndexQuote) -> str:
    return _pair(
        moex,
        moex2,
        header="🌇 <b>Итоги дневных торгов</b>",
        date_line=f"Дата: {format_date()}",
    )


def format_midnight(moex: IndexQuote, moex2: IndexQuote) -> str:
    return _pair(
        moex,
        moex2,
        header="🌙 <b>Итоги торгового дня</b>",
        date_line=f"Дата: {format_date()}",
    )


def format_no_trading() -> str:
    return f"📭 <b>Сегодня торгов нет</b>\n\nДата: {format_date()}"


def format_status(moex: IndexQuote, moex2: IndexQuote) -> str:
    return (
        "📱 <b>MOEX Monitor</b>\n"
        "━━━━━━━━━━━━━━\n"
        f"📅 {format_date()} · сессия <b>{moex2.session_name}</b>\n\n"
        f"{_block(moex2, extras=True)}\n\n"
        f"{_block(moex, extras=False)}\n\n"
        f"<i>MOEX2 обновлён: {moex2.update_time or '—'}\n"
        f"MOEX обновлён: {moex.update_time or '—'}</i>"
    )


def format_settings(
    chat_id: int,
    interval: int,
    start: str,
    end: str,
    midnight: str,
    trading_today: bool | None,
    last_trading_day: str | None,
    *,
    notify_morning: bool = True,
    notify_interval: bool = True,
    notify_evening: bool = True,
    notify_midnight: bool = True,
) -> str:
    trading = "да" if trading_today else "нет" if trading_today is False else "ещё не проверялось"

    def mark(v: bool) -> str:
        return "вкл" if v else "выкл"

    return (
        "⚙️ <b>Параметры уведомлений</b>\n\n"
        f"<code>ID {chat_id}</code>\n\n"
        f"⏱ Интервал рассылки: <b>{interval} мин</b>\n"
        f"🌅 Утро ({start}): <b>{mark(notify_morning)}</b>\n"
        f"🔔 Интервальные: <b>{mark(notify_interval)}</b>\n"
        f"🌇 Вечер ({end}): <b>{mark(notify_evening)}</b>\n"
        f"🌙 Полночь ({midnight}): <b>{mark(notify_midnight)}</b>\n\n"
        f"Торговый день: <b>{trading}</b>\n"
        f"Проверка: {last_trading_day or '—'}\n\n"
        "<i>Все параметры меняются кнопками ниже</i>"
    )


def format_welcome(chat_id: int) -> str:
    return (
        "📱 <b>MOEX Monitor</b>\n"
        "━━━━━━━━━━━━━━\n"
        "Личный терминал индексов МосБиржи\n\n"
        f"Аккаунт: <code>{chat_id}</code>\n\n"
        "Выберите раздел в меню внизу:\n"
        "📊 котировки и график\n"
        "🔔 алерты по MOEX2\n"
        "⚙️ расписание уведомлений"
    )


def format_help() -> str:
    return (
        "ℹ️ <b>Справка</b>\n\n"
        "Интерфейс полностью на кнопках.\n"
        "Технические команды: /start, /help\n\n"
        "<b>MOEX</b> — основная сессия\n"
        "<b>MOEX2</b> — все сессии (утро/день/вечер/выходные)"
    )


def format_alerts_screen(
    alerts_map: dict,
    check_minutes: int,
    current_moex2: float | None = None,
) -> str:
    lines = [
        "🔔 <b>Алерты MOEX2</b>",
        "━━━━━━━━━━━━━━",
        "До <b>4</b> одновременно: уровень ↑/↓ и % ↑/↓",
        f"Проверка каждые: <b>{check_minutes} мин</b>",
    ]
    if current_moex2 is not None:
        lines.append(f"Сейчас MOEX2: <b>{format_number(current_moex2)}</b>")

    lines.append("")
    slot_titles = {
        "level_above": "🎯 Уровень вверх",
        "level_below": "🎯 Уровень вниз",
        "pct_above": "📉 % вверх",
        "pct_below": "📉 % вниз",
    }
    active = 0
    for slot, title in slot_titles.items():
        a = alerts_map.get(slot)
        if not a:
            lines.append(f"{title}: <i>не задан</i>")
            continue
        active += 1
        if a["alert_type"] == "level":
            lines.append(
                f"{title}: <b>{format_number(float(a['target_value']))}</b>"
            )
        else:
            base = a.get("baseline_value")
            base_s = format_number(float(base)) if base is not None else "—"
            lines.append(
                f"{title}: <b>{format_percent(float(a['target_value']))}</b> "
                f"от базы {base_s}"
            )

    lines.append(f"\nАктивно: <b>{active}/4</b>")
    lines.append(
        "<i>Кнопки «Уровни» / «Проценты» — задать цель.\n"
        "❌ на слоте — удалить алерт.</i>"
    )
    return "\n".join(lines)


def format_alert_triggered(
    *,
    alert_type: str,
    value: float,
    target: float,
    direction: str,
    baseline: float | None = None,
    slot: str | None = None,
) -> str:
    dir_label = "вверх ↑" if direction == "above" else "вниз ↓"
    slot_line = f"Слот: <code>{slot}</code>\n" if slot else ""
    if alert_type == "level":
        return (
            "🚨 <b>Алерт MOEX2 · уровень</b>\n\n"
            f"{slot_line}"
            f"Направление: <b>{dir_label}</b>\n"
            f"Значение: <b>{format_number(value)}</b>\n"
            f"Цель: <b>{format_number(target)}</b>\n"
            "Условие выполнено."
        )
    change_pct = (
        ((value - (baseline or value)) / (baseline or value) * 100.0) if baseline else 0.0
    )
    return (
        "🚨 <b>Алерт MOEX2 · %</b>\n\n"
        f"{slot_line}"
        f"Направление: <b>{dir_label}</b>\n"
        f"Значение: <b>{format_number(value)}</b>\n"
        f"База: <b>{format_number(baseline)}</b>\n"
        f"Изменение: <b>{format_percent(change_pct)}</b>\n"
        f"Порог: <b>{format_percent(target)}</b>"
    )
