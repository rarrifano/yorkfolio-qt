"""Fixed income valuation helpers (pure): Tesouro Direto prices and indexer accrual.

Series come from the market cache as sorted lists of (iso_date, value):
  BCB:12  CDI, % per business day        BCB:11  Selic, % per business day
  BCB:433 IPCA, % per month ('YYYY-MM-01')
"""

from __future__ import annotations

import bisect
from datetime import date, timedelta

INDEXERS = {"cdi": "% do CDI", "selic": "% da Selic", "ipca": "IPCA +", "pre": "Prefixado"}


def last_on_or_before(seq: list[tuple[str, float]], key: str):
    """Last (date, value) whose date <= key (works for ISO dates and 'YYYY-MM' keys)."""
    i = bisect.bisect_right(seq, (key, float("inf")))
    return seq[i - 1] if i else None


def indexer_label(indexer: str | None, rate: float | None) -> str:
    if not indexer or rate is None:
        return ""
    r = f"{rate:g}".replace(".", ",")
    return {"cdi": f"{r}% do CDI", "selic": f"{r}% da Selic", "ipca": f"IPCA + {r}% a.a.", "pre": f"{r}% a.a. pré"}.get(
        indexer, ""
    )


def _weekdays(start: date, end: date) -> int:
    """Number of weekdays in [start, end)."""
    days = (end - start).days
    if days <= 0:
        return 0
    full, rest = divmod(days, 7)
    return full * 5 + sum((start + timedelta(days=full * 7 + k)).weekday() < 5 for k in range(rest))


def _after_last(rates, start_iso: str) -> str:
    return max(start_iso, (date.fromisoformat(rates[-1][0]) + timedelta(days=1)).isoformat())


def daily_compound(rates, pct: float, start_iso: str, end_iso: str) -> float:
    """Π(1 + rate_d × pct) for business days start <= d < end. Days after the last published rate
    (BCB publishes with a lag) are extrapolated with the last rate, weekdays only."""
    if end_iso <= start_iso or not rates:
        return 1.0
    factor, k = 1.0, pct / 100 / 100
    for _, r in rates[bisect.bisect_left(rates, (start_iso,)) : bisect.bisect_left(rates, (end_iso,))]:
        factor *= 1 + r * k
    tail = _after_last(rates, start_iso)
    if tail < end_iso:
        factor *= (1 + rates[-1][1] * k) ** _weekdays(date.fromisoformat(tail), date.fromisoformat(end_iso))
    return factor


def business_days(calendar, start_iso: str, end_iso: str) -> int:
    """Business days in [start, end) using the CDI dates as calendar (+ weekdays after it ends)."""
    if end_iso <= start_iso:
        return 0
    if not calendar:
        return _weekdays(date.fromisoformat(start_iso), date.fromisoformat(end_iso))
    n = bisect.bisect_left(calendar, (end_iso,)) - bisect.bisect_left(calendar, (start_iso,))
    tail = _after_last(calendar, start_iso)
    if tail < end_iso:
        n += _weekdays(date.fromisoformat(tail), date.fromisoformat(end_iso))
    return n


def ipca_factor(ipca, start_iso: str, end_iso: str) -> float:
    """Monthly IPCA compounded pro rata by calendar days; unpublished months reuse the last value."""
    start, end = date.fromisoformat(start_iso), date.fromisoformat(end_iso)
    by_month = {d[:7]: v for d, v in ipca}
    last = ipca[-1][1] if ipca else 0.0
    factor, d = 1.0, start
    while d < end:
        first = d.replace(day=1)
        nxt = (first + timedelta(days=32)).replace(day=1)
        seg_end = min(end, nxt)
        factor *= (1 + by_month.get(d.strftime("%Y-%m"), last) / 100) ** ((seg_end - d).days / (nxt - first).days)
        d = seg_end
    return factor


def accrual(indexer: str, rate: float, start_iso: str, end_iso: str, series: dict) -> float | None:
    """Growth factor of a post/pre-fixed bond between two dates, or None if data is missing."""
    cdi = series.get("BCB:12", [])
    if indexer == "cdi":
        return daily_compound(cdi, rate, start_iso, end_iso) if cdi else None
    if indexer == "selic":
        selic = series.get("BCB:11", [])
        return daily_compound(selic, rate, start_iso, end_iso) if selic else None
    if indexer == "pre":
        return (1 + rate / 100) ** (business_days(cdi, start_iso, end_iso) / 252)
    if indexer == "ipca":
        ipca = series.get("BCB:433", [])
        if not ipca:
            return None
        return (1 + rate / 100) ** (business_days(cdi, start_iso, end_iso) / 252) * ipca_factor(
            ipca, start_iso, end_iso
        )
    return None
