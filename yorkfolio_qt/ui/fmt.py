# SPDX-FileCopyrightText: 2026 rarrifano
# SPDX-License-Identifier: MIT

"""pt-BR number/date formatting (no locale dependency)."""

from __future__ import annotations

MONTHS = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]
MONTHS_LONG = [
    "janeiro", "fevereiro", "março", "abril", "maio", "junho",
    "julho", "agosto", "setembro", "outubro", "novembro", "dezembro",
]  # fmt: skip


def num(v, decimals: int = 2) -> str:
    if v is None:
        return "–"
    return f"{v:,.{decimals}f}".replace(",", "\0").replace(".", ",").replace("\0", ".")


def brl(v) -> str:
    if v is None:
        return "–"
    if round(v, 2) == 0:
        v = 0.0
    return "-R$ " + num(-v) if v < 0 else "R$ " + num(v)


def money(v, currency: str = "BRL") -> str:
    if v is None:
        return "–"
    return ("US$ " + num(v)) if currency == "USD" else brl(v)


def qty(v) -> str:
    if v is None:
        return "–"
    return num(v, 8).rstrip("0").rstrip(",") if abs(v - round(v)) > 1e-9 else num(v, 0)


def pct(v, decimals: int = 1) -> str:
    return "–" if v is None else num(v * 100, decimals) + "%"


def signed_pct(v, decimals: int = 2) -> str:
    return "–" if v is None else ("+" if v > 0 else "") + num(v * 100, decimals) + "%"


def br_date(iso: str | None) -> str:
    return "/".join(reversed(iso[:10].split("-"))) if iso else "–"


def month_label(ym: str) -> str:
    return f"{MONTHS[int(ym[5:7]) - 1]}/{ym[2:4]}"


def month_long(ym: str) -> str:
    return f"{MONTHS_LONG[int(ym[5:7]) - 1]} de {ym[:4]}"


def compact(v: float) -> str:
    a = abs(v)
    for limit, suffix in ((1e9, " bi"), (1e6, " mi"), (1e3, " mil")):
        if a >= limit:
            return num(v / limit, 1 if a < limit * 10 else 0) + suffix
    return num(v, 0)


def parse_number(text: str | None) -> float | None:
    """'1234.5', '1234,5', '1.234,50' -> float; empty -> None; invalid -> ValueError."""
    from ..b3 import parse_num

    text = (text or "").strip()
    if not text:
        return None
    value = parse_num(text)
    if value is None:
        raise ValueError(f"número inválido: {text}")
    return value
