"""
Модуль работы с официальным ISS API Московской биржи.

Все HTTP-запросы к MOEX изолированы здесь.
Документация: https://iss.moex.com/iss/reference/

Тикеры:
- IMOEX  — индекс МосБиржи (только основная сессия)
- IMOEX2 — индекс МосБиржи за все сессии (утро / основная / вечер / выходные),
           в сообщениях отображается как MOEX2
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any

import aiohttp

from config import (
    HTTP_RETRIES,
    HTTP_RETRY_DELAY,
    HTTP_TIMEOUT,
    MOEX2_SECID,
    MOEX_ISS_BASE,
    MOEX_SECID,
    MSK,
)
from utils import now_msk

logger = logging.getLogger(__name__)

# Коды TRADINGSESSION в ISS MOEX
SESSION_MORNING = 0
SESSION_MAIN = 1
SESSION_EVENING = 2
SESSION_DAY_TOTAL = 3
SESSION_WEEKEND = 5

# Сессии, в которых IMOEX (основная) не торгуется «вживую»
OFF_MAIN_SESSIONS = {SESSION_MORNING, SESSION_EVENING, SESSION_WEEKEND}

SESSION_NAMES = {
    SESSION_MORNING: "утренняя",
    SESSION_MAIN: "основная",
    SESSION_EVENING: "вечерняя",
    SESSION_DAY_TOTAL: "итоги дня",
    SESSION_WEEKEND: "выходного дня",
}


@dataclass
class IndexQuote:
    """Котировка индекса на текущий момент."""

    secid: str
    display_name: str
    current: float | None
    open_value: float | None
    last_value: float | None  # закрытие предыдущих торгов (LASTVALUE)
    change: float | None
    change_pct: float | None
    trade_date: date | None
    update_time: str | None
    trading_session: int | None = None
    day_change: float | None = None
    day_change_pct: float | None = None
    high: float | None = None
    low: float | None = None
    volume: float | None = None  # VALTODAY — оборот
    is_live: bool = True
    result_date: date | None = None
    caption: str = ""

    @property
    def value(self) -> float | None:
        for candidate in (self.current, self.last_value, self.open_value):
            if candidate is not None:
                return candidate
        return None

    @property
    def prev_close(self) -> float | None:
        """Закрытие предыдущих торгов."""
        return self.last_value

    @property
    def session_name(self) -> str:
        if self.trading_session is None:
            return "неизвестно"
        return SESSION_NAMES.get(self.trading_session, f"сессия {self.trading_session}")


def _rows_to_dicts(block: dict[str, Any]) -> list[dict[str, Any]]:
    columns = block.get("columns") or []
    data = block.get("data") or []
    return [dict(zip(columns, row)) for row in data]


async def _get_json(path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    """GET к ISS с повторными попытками."""
    url = f"{MOEX_ISS_BASE}{path}"
    query = {"iss.meta": "off", **(params or {})}
    last_error: Exception | None = None

    for attempt in range(1, HTTP_RETRIES + 1):
        try:
            timeout = aiohttp.ClientTimeout(total=HTTP_TIMEOUT)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(url, params=query) as resp:
                    resp.raise_for_status()
                    return await resp.json(content_type=None)
        except Exception as exc:
            last_error = exc
            logger.warning(
                "MOEX API ошибка %s/%s: %s %s",
                attempt,
                HTTP_RETRIES,
                url,
                exc,
            )
            if attempt < HTTP_RETRIES:
                await asyncio.sleep(HTTP_RETRY_DELAY * attempt)

    raise RuntimeError(f"Не удалось получить данные MOEX: {url}") from last_error


def _parse_date(value: Any) -> date | None:
    if not value:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    text = str(value)[:10]
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def _to_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def detect_session_by_clock(now: datetime | None = None) -> int:
    """
    Запасное определение сессии по московскому времени,
    если TRADINGSESSION в ответе ISS отсутствует.
    """
    now = now or now_msk()
    if now.weekday() >= 5:
        return SESSION_WEEKEND

    t = now.timetz().replace(tzinfo=None)
    # Утро: до 10:00; основная: 10:00–19:00; вечер: после 19:00
    if t < time(10, 0):
        return SESSION_MORNING
    if t < time(19, 0):
        return SESSION_MAIN
    return SESSION_EVENING


def is_off_main_session(session: int | None) -> bool:
    """Утро / вечер / выходные — для IMOEX показываем итоги последнего дня."""
    if session is None:
        return False
    return session in OFF_MAIN_SESSIONS


async def get_official_prev_close(
    secid: str | None = None,
    *,
    before: date | None = None,
) -> tuple[float | None, date | None]:
    """
    Официальное закрытие дня, строго предшествующего `before`.

    Важно для IMOEX2: LASTVALUE в marketdata часто = закрытие основной сессии
    IMOEX, а не итог всех сессий.

    `before` — дата торгов, к которой относится текущее значение индекса
    (обычно TRADEDATE). Нельзя подставлять «календарный завтра» после полуночи:
    иначе предыдущим закрытием станет только что закончившийся день
    (например в 00:00 14.07 возьмётся close 13.07 вместо 12.07).
    """
    secid = secid or MOEX2_SECID
    if before is None:
        # Якорь — TRADEDATE инструмента, а не дата по часам сервера
        try:
            raw = await _fetch_raw_quote(secid, secid)
            before = raw.trade_date or now_msk().date()
        except Exception:
            before = now_msk().date()

    frm = before - timedelta(days=14)
    payload = await _get_json(
        f"/engines/stock/markets/index/boards/SNDX/securities/{secid}/candles.json",
        params={
            "from": frm.isoformat(),
            "till": before.isoformat(),
            "interval": 24,
        },
    )
    rows = _rows_to_dicts(payload.get("candles", {}))
    best_close: float | None = None
    best_day: date | None = None
    for row in rows:
        begin = _parse_date(row.get("begin"))
        close = _to_float(row.get("close"))
        if begin is None or close is None:
            continue
        if begin >= before:
            continue
        if best_day is None or begin > best_day:
            best_day = begin
            best_close = close

    if best_close is not None:
        return best_close, best_day

    # Запасной путь: история по сессиям (5=выходные, 2=вечер, 1=основная, 0=утро, 3=итог)
    for session_id in (5, 2, 1, 0, 3):
        try:
            hist = await _get_json(
                f"/history/engines/stock/markets/index/sessions/{session_id}/securities/{secid}.json",
                params={
                    "from": frm.isoformat(),
                    "till": (before - timedelta(days=1)).isoformat(),
                },
            )
        except Exception:
            continue
        for row in _rows_to_dicts(hist.get("history", {})):
            day = _parse_date(row.get("TRADEDATE"))
            close = _to_float(row.get("CLOSE"))
            if day is None or close is None or day >= before:
                continue
            if best_day is None or day > best_day:
                best_day = day
                best_close = close

    return best_close, best_day


def _apply_prev_close(quote: IndexQuote, prev_close: float | None) -> IndexQuote:
    """Пересчитывает изменение относительно официального предыдущего закрытия."""
    if prev_close is None:
        return quote
    quote.last_value = prev_close
    value = quote.value
    if value is None:
        return quote
    change = value - prev_close
    change_pct = (change / prev_close) * 100.0 if prev_close else None
    quote.change = change
    quote.change_pct = change_pct
    quote.day_change = change
    quote.day_change_pct = change_pct
    return quote


async def _fetch_raw_quote(secid: str, display_name: str) -> IndexQuote:
    """Сырые данные marketdata без бизнес-логики сессий."""
    payload = await _get_json(
        f"/engines/stock/markets/index/securities/{secid}.json",
        params={"iss.only": "marketdata,securities"},
    )
    market = _rows_to_dicts(payload.get("marketdata", {}))
    if not market:
        raise RuntimeError(f"Пустой marketdata для {secid}")

    row = market[0]
    open_value = _to_float(row.get("OPENVALUE"))
    current = _to_float(row.get("CURRENTVALUE"))
    # LASTVALUE — не всегда корректное «пред. закрытие» для IMOEX2 (все сессии)
    last_value = _to_float(row.get("LASTVALUE"))

    change = _to_float(row.get("LASTCHANGE"))
    change_pct = _to_float(row.get("LASTCHANGEPRC"))

    value = current if current is not None else last_value
    if change is None and value is not None and last_value not in (None, 0):
        change = value - last_value
    if change_pct is None and change is not None and last_value not in (None, 0):
        change_pct = (change / last_value) * 100.0

    return IndexQuote(
        secid=secid,
        display_name=display_name,
        current=current,
        open_value=open_value,
        last_value=last_value,
        change=change,
        change_pct=change_pct,
        trade_date=_parse_date(row.get("TRADEDATE")),
        update_time=row.get("UPDATETIME") or row.get("TIME"),
        trading_session=_to_int(row.get("TRADINGSESSION")),
        day_change=change,
        day_change_pct=change_pct,
        high=_to_float(row.get("HIGH")),
        low=_to_float(row.get("LOW")),
        volume=_to_float(row.get("VALTODAY")),
        is_live=True,
        result_date=_parse_date(row.get("TRADEDATE")),
        caption="",
    )


def _as_main_session_live(quote: IndexQuote) -> IndexQuote:
    """IMOEX во время основной сессии — к закрытию предыдущих торгов."""
    quote.is_live = True
    quote.result_date = quote.trade_date
    quote.caption = "к закрытию предыдущих торгов"
    return quote


def _as_last_main_day_result(quote: IndexQuote) -> IndexQuote:
    """
    IMOEX вне основной сессии — итоги последнего дня основной сессии.
    Изменение — к закрытию торгов днём раньше.
    """
    if quote.day_change is not None:
        quote.change = quote.day_change
    if quote.day_change_pct is not None:
        quote.change_pct = quote.day_change_pct

    quote.is_live = False
    quote.result_date = quote.trade_date
    date_label = quote.result_date.strftime("%d.%m.%Y") if quote.result_date else "—"
    quote.caption = f"итоги основной сессии на {date_label} · к пред. закрытию"
    return quote


def _as_moex2_live(quote: IndexQuote, session: int | None) -> IndexQuote:
    """IMOEX2 — актуальные данные; изменение к пред. закрытию."""
    quote.is_live = True
    quote.result_date = quote.trade_date
    quote.caption = "к закрытию предыдущих торгов"
    return quote


async def get_index_quote(secid: str, display_name: str) -> IndexQuote:
    """Текущие значения индекса (сырой ответ + базовая подпись)."""
    return await _fetch_raw_quote(secid, display_name)


async def get_moex2() -> IndexQuote:
    """
    MOEX2 (ISS: IMOEX2) — индекс за весь торговый день:
    утренняя, основная, вечерняя и сессия выходного дня.

    Изменение считается к официальному закрытию дня до TRADEDATE
    (не к календарному «сегодня» и не к LASTVALUE marketdata).
    """
    quote = await _fetch_raw_quote(MOEX2_SECID, "MOEX2")
    session = quote.trading_session
    if session is None:
        session = detect_session_by_clock()
        quote.trading_session = session

    # Якорь — дата торгов текущего значения (критично после полуночи)
    ref_day = quote.trade_date or now_msk().date()
    prev_close, prev_day = await get_official_prev_close(MOEX2_SECID, before=ref_day)
    quote = _apply_prev_close(quote, prev_close)
    quote = _as_moex2_live(quote, session)
    if prev_day:
        quote.caption = (
            f"к закрытию предыдущих торгов ({prev_day.strftime('%d.%m.%Y')})"
        )
    return quote


async def get_moex(*, active_session: int | None = None) -> IndexQuote:
    """
    MOEX (ISS: IMOEX) — только основная торговая сессия.

    Во время утренней / вечерней / выходной сессии возвращает
    итоги последнего дня основной сессии с указанием даты.

    Для IMOEX поле LASTVALUE/LASTCHANGE ISS корректно отражает
    закрытие предыдущей основной сессии (в отличие от IMOEX2).
    """
    quote = await _fetch_raw_quote(MOEX_SECID, "MOEX")

    if active_session is None:
        try:
            moex2 = await _fetch_raw_quote(MOEX2_SECID, "MOEX2")
            active_session = moex2.trading_session
        except Exception:
            logger.exception("Не удалось получить сессию из IMOEX2")
            active_session = None

    if active_session is None:
        active_session = detect_session_by_clock()

    quote.trading_session = active_session

    if is_off_main_session(active_session):
        return _as_last_main_day_result(quote)

    return _as_main_session_live(quote)


async def get_both_indices() -> tuple[IndexQuote, IndexQuote]:
    """MOEX2 и MOEX с корректным предыдущим закрытием."""
    moex2 = await get_moex2()
    moex = await get_moex(active_session=moex2.trading_session)
    return moex, moex2


async def is_trading_day(check_date: date | None = None) -> bool:
    """
    Есть ли сегодня торги (включая доп. сессии IMOEX2).

    True, если:
    - TRADEDATE у IMOEX2 == check_date, или
    - активна сессия 0/1/2/5, или
    - будний день без праздничного исключения в timetable.
    """
    day = check_date or now_msk().date()

    try:
        moex2 = await _fetch_raw_quote(MOEX2_SECID, "MOEX2")
        if moex2.trade_date == day:
            return True
        if moex2.trading_session in {
            SESSION_MORNING,
            SESSION_MAIN,
            SESSION_EVENING,
            SESSION_WEEKEND,
        }:
            # Сессия активна, даже если TRADEDATE «переехал»
            if day == now_msk().date():
                return True
    except Exception:
        logger.exception("Не удалось получить IMOEX2 для проверки торгов")

    try:
        quote = await _fetch_raw_quote(MOEX_SECID, "MOEX")
        if quote.trade_date == day:
            return True
    except Exception:
        logger.exception("Не удалось получить TRADEDATE IMOEX")

    try:
        payload = await _get_json("/engines/stock/timetable.json")
        daily = _rows_to_dicts(payload.get("dailytable", {}))
        for row in daily:
            if _parse_date(row.get("date")) == day:
                return bool(row.get("is_work_day"))
    except Exception:
        logger.exception("Не удалось прочитать timetable MOEX")

    if day.isoweekday() >= 6:
        # Выходные: торги возможны (ДСВД), если IMOEX2 в сессии 5
        return False

    return True


async def get_prev_close(secid: str | None = None) -> float | None:
    """Официальное закрытие дня до TRADEDATE текущего значения."""
    secid = secid or MOEX2_SECID
    close, _ = await get_official_prev_close(secid)
    return close


async def get_index_history_close(secid: str, day: date) -> float | None:
    """Закрытие индекса за дату из истории ISS."""
    payload = await _get_json(
        f"/history/engines/stock/markets/index/securities/{secid}.json",
        params={"from": day.isoformat(), "till": day.isoformat()},
    )
    rows = _rows_to_dicts(payload.get("history", {}))
    if not rows:
        return None
    return _to_float(rows[0].get("CLOSE"))


@dataclass
class Candle:
    begin: datetime
    end: datetime
    open: float
    close: float
    high: float
    low: float
    value: float = 0.0  # оборот; 0 = нет торгов в интервале


async def get_candles_24h(
    secid: str | None = None,
    *,
    interval_minutes: int = 10,
    only_traded: bool = True,
) -> list[Candle]:
    """
    Свечи индекса за последние ~24 часа.

    only_traded=True — исключает интервалы без оборота (торгов не было).
    """
    secid = secid or MOEX2_SECID
    now = now_msk()
    frm = (now - timedelta(hours=30)).date()
    till = now.date()

    payload = await _get_json(
        f"/engines/stock/markets/index/boards/SNDX/securities/{secid}/candles.json",
        params={
            "from": frm.isoformat(),
            "till": till.isoformat(),
            "interval": interval_minutes,
        },
    )
    rows = _rows_to_dicts(payload.get("candles", {}))
    candles: list[Candle] = []
    cutoff = now - timedelta(hours=24)

    for row in rows:
        begin_raw = row.get("begin")
        if not begin_raw:
            continue
        begin = datetime.fromisoformat(str(begin_raw)).replace(tzinfo=MSK)
        if begin < cutoff:
            continue
        end_raw = row.get("end") or begin_raw
        end = datetime.fromisoformat(str(end_raw)).replace(tzinfo=MSK)
        turnover = _to_float(row.get("value")) or 0.0
        if only_traded and turnover <= 0:
            continue
        candles.append(
            Candle(
                begin=begin,
                end=end,
                open=float(row["open"]),
                close=float(row["close"]),
                high=float(row["high"]),
                low=float(row["low"]),
                value=turnover,
            )
        )
    return candles
