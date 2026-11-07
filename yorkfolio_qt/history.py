# SPDX-FileCopyrightText: 2026 rarrifano
# SPDX-License-Identifier: MIT

"""Monthly history (pure): patrimônio by class, invested cost, returns and benchmarks."""

from __future__ import annotations

import bisect
import calendar
import math
from collections import defaultdict
from datetime import date

from .assets import IBOV_SYMBOL, default_class
from . import native
from .engine import EPS, _position


def month_ends(first: date, today: date) -> list[date]:
    """Last day of every month from `first` up to the previous month, then `today`."""
    out, y, m = [], first.year, first.month
    while (y, m) < (today.year, today.month):
        out.append(date(y, m, calendar.monthrange(y, m)[1]))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    out.append(today)
    return out


def _prev_month(month: str) -> str:
    y, m = int(month[:4]), int(month[5:7])
    return f"{y - 1}-12" if m == 1 else f"{y}-{m - 1:02d}"


def build_history(events: list[dict], final, settings: dict, valuer, today: date) -> dict:
    """One point per month end. Returns use Modified Dietz with exact flow dates; months without
    exposure get `ret=None` (benchmarks are only compounded over the same months on the client)."""
    if not events:
        return {"points": []}
    types = {code: p.asset_type for code, p in final.positions.items()}

    def class_of(code):
        return settings.get(code, {}).get("class") or default_class(types.get(code, "outro"))

    cdi = valuer.series.get("BCB:12", [])
    ibov = dict(valuer.series.get(f"Y:{IBOV_SYMBOL}", []))
    ends = month_ends(date.fromisoformat(events[0]["date"]), today)
    book, i, seen_flows, prev_value, points = native.NativeBook(), 0, 0, 0.0, []

    for k, end in enumerate(ends):
        iso, month, start = end.isoformat(), end.isoformat()[:7], end.replace(day=1)
        j = i
        while j < len(events) and events[j]["date"] <= iso:
            j += 1
        book.apply_all(events[i:j])
        i = j
        snap = book.state(full=False, from_flow=seen_flows, open_only=True)
        flows, seen_flows = snap["flows"], seen_flows + len(snap["flows"])
        positions = {c: _position(p) for c, p in snap["positions"].items()}

        value = cost = 0.0
        classes = defaultdict(float)
        for code, p in positions.items():
            if p.qty <= EPS:
                continue
            p.asset_type = types.get(code, p.asset_type)
            s = settings.get(code, {})
            v = valuer.current(p, s)["value"] if k == len(ends) - 1 else valuer.at(p, iso, month)
            value += v
            cost += p.cost
            classes[class_of(code)] += v

        span = (end - start).days + 1
        net = sum(a for _, a in flows)
        money_in = sum(a for _, a in flows if a > 0)
        weighted = sum(a * (end - date.fromisoformat(d)).days / span for d, a in flows)
        if prev_value > 1 and prev_value + weighted > 1:
            ret = (value - prev_value - net) / (prev_value + weighted)
        elif money_in > 1:  # starting from (almost) nothing: return on the new money
            ret = (value - prev_value - net) / (prev_value + money_in)
        else:
            ret = None

        lo, hi = bisect.bisect_left(cdi, (start.isoformat(),)), bisect.bisect_right(cdi, (iso, math.inf))
        cdi_m = math.prod(1 + r / 100 for _, r in cdi[lo:hi]) - 1 if hi > lo else None
        prev_ibov, cur_ibov = ibov.get(_prev_month(month)), ibov.get(month)
        ibov_m = cur_ibov / prev_ibov - 1 if cur_ibov and prev_ibov else None

        points.append(
            {
                "month": month,
                "date": iso,
                "value": value,
                "cost": cost,
                "flow": net,
                "classes": dict(classes),
                "ret": ret,
                "cdi": cdi_m,
                "ibov": ibov_m,
            }
        )
        prev_value = value
    return {"points": points}
