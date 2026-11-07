"""Valuation of positions now (carteira) and at past month ends (history)."""

from __future__ import annotations

from datetime import date

from .assets import FIXED_INCOME_TYPES, FX_SYMBOL, QUOTED_TYPES, currency, yahoo_symbol
from .fixed_income import accrual, indexer_label, last_on_or_before


def _br(iso: str | None) -> str:
    return "/".join(reversed(iso[:10].split("-"))) if iso else "?"


def _prev_month(month: str) -> str:
    y, m = int(month[:4]), int(month[5:7])
    return f"{y - 1}-12" if m == 1 else f"{y}-{m - 1:02d}"


class Valuer:
    """Prices positions using cached market data.

    settings: per-asset settings (manual_price, quote, manual_value, indexer, rate…)
    series:   {key: [(date, value), …]} — 'Y:<symbol>' monthly closes ('YYYY-MM', split-unadjusted),
              'TD:<bond>' Tesouro PU by day, 'BCB:<n>' rate series
    fx_now:   current USD→BRL (None = unknown)
    """

    def __init__(self, settings: dict, series: dict, fx_now: float | None = None, today: date | None = None):
        self.settings, self.series, self.fx_now = settings, series, fx_now
        self.today = (today or date.today()).isoformat()

    # ------------------------------------------------------------ helpers
    def monthly_close(self, key: str, month: str) -> float | None:
        """Close of `month`, or of the previous month when the bar is missing."""
        hit = last_on_or_before(self.series.get(key, []), month)
        return hit[1] if hit and hit[0] >= _prev_month(month) else None

    def fx_at(self, month: str) -> float | None:
        return self.monthly_close(f"Y:{FX_SYMBOL}", month) or self.fx_now

    def fixed_income(self, p, s: dict, at_iso: str) -> tuple[float, str, str]:
        """(value, source, note) for fixed income / other assets at a date (manual value ignored)."""
        if p.asset_type == "tesouro":
            hit = last_on_or_before(self.series.get(f"TD:{p.code}", []), at_iso)
            if hit:
                return p.qty * hit[1], "tesouro", f"preço do Tesouro em {_br(hit[0])}"
        if p.anchor and p.asset_type in FIXED_INCOME_TYPES:
            anchor_date, pu = p.anchor
            if s.get("indexer") and s.get("rate") is not None:
                f = accrual(s["indexer"], s["rate"], anchor_date, at_iso, self.series)
                if f:
                    return (
                        p.qty * pu * f,
                        "indexador",
                        f"{indexer_label(s['indexer'], s['rate'])} desde {_br(anchor_date)}",
                    )
            value = p.qty * pu
            if abs(value - p.cost) > 0.01:
                return value, "último PU", f"último preço unitário conhecido ({_br(anchor_date)})"
        return p.cost, "custo", ""

    # ------------------------------------------------------------ now
    def current(self, p, s: dict) -> dict:
        t = p.asset_type
        if t in QUOTED_TYPES:
            price, source = (s.get("manual_price"), "manual") if s.get("manual_price") else (s.get("quote"), "cotação")
            fx = 1.0 if currency(t) == "BRL" else self.fx_now
            price_brl = price * fx if price and fx else None
            if price_brl is None:
                return {
                    "value": p.cost,
                    "price": price,
                    "price_brl": None,
                    "source": "custo",
                    "note": "sem cotação: avaliado pelo custo",
                }
            note = f"US$ 1 = R$ {fx:.4f}".replace(".", ",") if currency(t) == "USD" else ""
            return {"value": p.qty * price_brl, "price": price, "price_brl": price_brl, "source": source, "note": note}
        if s.get("manual_value") is not None:
            return {
                "value": s["manual_value"],
                "price": None,
                "price_brl": None,
                "source": "manual",
                "note": f"informado em {_br(s.get('manual_value_at'))}",
            }
        value, source, note = self.fixed_income(p, s, self.today)
        return {"value": value, "price": None, "price_brl": None, "source": source, "note": note}

    # ------------------------------------------------------------ history
    def at(self, p, at_iso: str, month: str) -> float:
        t = p.asset_type
        if t in QUOTED_TYPES:
            close = self.monthly_close(f"Y:{yahoo_symbol(p.code, t)}", month)
            fx = 1.0 if currency(t) == "BRL" else self.fx_at(month)
            return p.qty * close * fx if close and fx else p.cost
        return self.fixed_income(p, self.settings.get(p.code, {}), at_iso)[0]
