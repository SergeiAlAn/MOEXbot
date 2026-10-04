"""Построение графика MOEX2 за последние 24 часа (только торговые интервалы)."""

from __future__ import annotations

import io
import logging
from datetime import date

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from moex_api import Candle
from utils import today_msk

logger = logging.getLogger(__name__)


def build_moex2_chart(
    candles: list[Candle],
    *,
    prev_close: float | None = None,
    title: str = "MOEX2 · изм. к пред. закрытию",
    session_date: date | None = None,
) -> bytes:
    """
    Линейный график изменения к закрытию предыдущих торгов.

    По оси X — торговые точки без пустых интервалов.
    По оси Y — close − prev_close.
    Вертикальная пунктирная линия — начало сегодняшних торгов.
    """
    if not candles:
        raise ValueError("Нет данных свечей для графика")

    if prev_close is None or prev_close == 0:
        raise ValueError(
            "Не передан официальный prev_close для графика MOEX2 "
            "(нельзя подставлять цену первой свечи)"
        )

    session_date = session_date or today_msk()
    xs = list(range(len(candles)))
    deltas = [c.close - prev_close for c in candles]
    labels = [c.begin.strftime("%d.%m %H:%M") for c in candles]

    last = deltas[-1]
    up = last >= 0
    line_color = "#22C55E" if up else "#EF4444"
    fill_color = "#22C55E33" if up else "#EF444433"

    fig, ax = plt.subplots(figsize=(9, 4.8), dpi=140)
    fig.patch.set_facecolor("#0B1220")
    ax.set_facecolor("#0B1220")

    ax.plot(xs, deltas, color=line_color, linewidth=2.0, solid_capstyle="round")
    ax.fill_between(xs, deltas, 0, color=fill_color, linewidth=0)
    # Нулевая линия = официальное закрытие предыдущего торгового дня
    ax.axhline(0, color="#38BDF8", linewidth=1.2, linestyle="--", alpha=0.95)
    ax.text(
        0.99,
        0.02,
        f"пред. закр. {prev_close:,.2f}".replace(",", " "),
        transform=ax.transAxes,
        va="bottom",
        ha="right",
        color="#38BDF8",
        fontsize=8,
    )

    start_idx = next(
        (i for i, c in enumerate(candles) if c.begin.date() == session_date),
        None,
    )

    ax.set_title(title, color="#F8FAFC", fontsize=13, pad=12, fontweight="bold")
    ax.set_ylabel("пункты к пред. закрытию", color="#94A3B8", fontsize=9)
    ax.tick_params(colors="#94A3B8", labelsize=8)
    for spine in ax.spines.values():
        spine.set_color("#1E293B")

    ax.yaxis.grid(True, color="#1E293B", linewidth=0.8)
    ax.xaxis.grid(False)
    ax.set_axisbelow(True)

    tick_count = min(6, len(xs))
    if tick_count == 1:
        tick_pos = [0]
    else:
        step = (len(xs) - 1) / (tick_count - 1)
        tick_pos = sorted({int(round(i * step)) for i in range(tick_count)})
    ax.set_xticks(tick_pos)
    ax.set_xticklabels([labels[i] for i in tick_pos], rotation=15, ha="right")

    pct = (last / prev_close * 100.0) if prev_close else 0.0
    sign = "+" if last >= 0 else ""
    badge = (
        f"{candles[-1].close:,.2f}  {sign}{last:.2f} ({sign}{pct:.2f}%)"
        f"  |  пред.закр. {prev_close:,.2f}"
    ).replace(",", " ")
    ax.text(
        0.01,
        0.97,
        badge,
        transform=ax.transAxes,
        va="top",
        ha="left",
        color=line_color,
        fontsize=9,
        fontweight="bold",
        bbox={
            "boxstyle": "round,pad=0.35",
            "facecolor": "#111827",
            "edgecolor": "#334155",
        },
    )

    if start_idx is not None:
        ax.axvline(
            start_idx,
            color="#FBBF24",
            linewidth=1.2,
            linestyle="--",
            alpha=0.95,
        )

    fig.tight_layout(pad=1.2)

    if start_idx is not None:
        y_top = ax.get_ylim()[1]
        ax.text(
            start_idx + 0.3,
            y_top,
            "старт дня",
            color="#FBBF24",
            fontsize=8,
            va="top",
            ha="left",
        )

    buf = io.BytesIO()
    fig.savefig(buf, format="png", facecolor=fig.get_facecolor())
    plt.close(fig)
    buf.seek(0)
    return buf.read()


async def render_moex2_chart_png() -> bytes | None:
    """Загружает свечи и строит PNG; при ошибке возвращает None."""
    try:
        from moex_api import get_candles_24h, get_official_prev_close

        candles = await get_candles_24h(only_traded=True)
        if not candles:
            logger.warning("Нет торговых свечей MOEX2 за 24ч")
            return None
        prev, prev_day = await get_official_prev_close()
        if prev is None:
            logger.warning("Не удалось получить официальное предыдущее закрытие IMOEX2")
            return None
        title = "MOEX2 · изм. к пред. закрытию"
        if prev_day:
            title = f"MOEX2 · к закрытию {prev_day.strftime('%d.%m.%Y')}"
        return build_moex2_chart(candles, prev_close=prev, title=title)
    except Exception:
        logger.exception("Не удалось построить график MOEX2")
        return None
