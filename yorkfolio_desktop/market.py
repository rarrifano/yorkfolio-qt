"""Market data over HTTP (stdlib only): Yahoo Finance, Banco Central (SGS) and Tesouro Transparente."""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone

YAHOO = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?{query}"
BCB = "https://api.bcb.gov.br/dados/serie/bcdata.sgs.{series}/dados?formato=json&dataInicial={start}&dataFinal={end}"
TESOURO_CSV = (
    "https://www.tesourotransparente.gov.br/ckan/dataset/df56aa42-484a-4a59-8184-7676580c81e3/"
    "resource/796d2059-14e9-44e3-80c9-2d9e30b405c1/download/PrecoTaxaTesouroDireto.csv"
)
CDI, SELIC, IPCA, PTAX = 12, 11, 433, 1


def _get(url: str, timeout: float = 30) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def parallel(fn, items, workers: int = 8) -> tuple[dict, dict]:
    """Run fn(item) concurrently. Returns ({item: result}, {item: error message})."""
    ok, errors = {}, {}

    def one(item):
        try:
            return item, fn(item), None
        except Exception as exc:  # network / unknown symbol / bad payload
            return item, None, f"{type(exc).__name__}: {exc}"

    with ThreadPoolExecutor(max_workers=workers) as pool:
        for item, result, err in pool.map(one, list(items)):
            if err:
                errors[item] = err
            else:
                ok[item] = result
    return ok, errors


# ------------------------------------------------------------ Yahoo Finance
def _chart(symbol: str, **params) -> dict:
    query = urllib.parse.urlencode(params)
    return json.loads(_get(YAHOO.format(symbol=urllib.parse.quote(symbol), query=query)))["chart"]["result"][0]


def fetch_quote(symbol: str) -> float:
    meta = _chart(symbol, range="1d", interval="1d")["meta"]
    price = meta.get("regularMarketPrice") or meta.get("previousClose")
    if not price:
        raise ValueError("sem preço")
    return float(price)


def unadjust(bars: list[tuple[str, str, float]], splits: list[tuple[str, float]]) -> list[tuple[str, float]]:
    """Yahoo closes are split-adjusted; undo it so they match the quantities held at the time.
    bars: (month, last_day_iso, close); splits: (iso_date, ratio new/old)."""
    out = []
    for month, last_day, close in bars:
        factor = 1.0
        for when, ratio in splits:
            if when > last_day:
                factor *= ratio
        out.append((month, close * factor))
    return out


def fetch_monthly(symbol: str, start: date) -> list[tuple[str, float]]:
    """Monthly closes ('YYYY-MM', close) since `start`, as traded at the time (split-unadjusted)."""
    period1 = int(datetime(start.year, start.month, 1, tzinfo=timezone.utc).timestamp())
    res = _chart(
        symbol, period1=period1, period2=int(datetime.now(timezone.utc).timestamp()), interval="1mo", events="split"
    )
    offset = res["meta"].get("gmtoffset", 0)
    stamps, closes = res.get("timestamp") or [], res["indicators"]["quote"][0].get("close") or []
    bars = []
    for ts, close in zip(stamps, closes, strict=False):
        if close is None:
            continue
        day = datetime.fromtimestamp(ts + offset, timezone.utc).date()
        nxt = (day.replace(day=1) + timedelta(days=32)).replace(day=1)
        bars.append((day.strftime("%Y-%m"), (nxt - timedelta(days=1)).isoformat(), float(close)))
    splits = [
        (datetime.fromtimestamp(s["date"] + offset, timezone.utc).date().isoformat(), s["numerator"] / s["denominator"])
        for s in (res.get("events") or {}).get("splits", {}).values()
        if s.get("denominator")
    ]
    monthly = dict(unadjust(bars, splits))  # last bar of a month wins
    return sorted(monthly.items())


# ------------------------------------------------------------ Banco Central (SGS)
def fetch_bcb(series: int, start: date, end: date) -> list[tuple[str, float]]:
    """[(iso_date, value)] — requested in ≤ 5-year windows (the API rejects longer daily ranges)."""
    out, cur = [], start
    while cur <= end:
        stop = min(end, cur + timedelta(days=5 * 365))
        url = BCB.format(series=series, start=cur.strftime("%d/%m/%Y"), end=stop.strftime("%d/%m/%Y"))
        try:
            rows = json.loads(_get(url))
        except urllib.error.HTTPError as exc:
            if exc.code != 404:  # 404 = no data in the window
                raise
            rows = []
        for r in rows:
            d = datetime.strptime(r["data"], "%d/%m/%Y").date().isoformat()
            out.append((d, float(r["valor"])))
        cur = stop + timedelta(days=1)
    return out


def fetch_ptax(day: date) -> float | None:
    """USD→BRL PTAX (venda) on `day` or the closest previous business day."""
    rows = fetch_bcb(PTAX, day - timedelta(days=10), day)
    return rows[-1][1] if rows else None


# ------------------------------------------------------------ Tesouro Direto
def fetch_tesouro() -> str:
    return _get(TESOURO_CSV, timeout=120).decode("latin-1")


def parse_tesouro(text: str, names: set[str]) -> dict[str, list[tuple[str, float]]]:
    """Daily PU (preço unitário base) for the wanted bonds, e.g. 'Tesouro IPCA+ 2029'."""
    out: dict[str, list] = {n: [] for n in names}
    for line in text.splitlines()[1:]:
        cols = line.split(";")
        if len(cols) < 8:
            continue
        name = f"{cols[0].strip()} {cols[1].strip()[-4:]}"
        if name not in out:
            continue
        pu = cols[7].strip() or cols[6].strip()
        if not pu:
            continue
        d, m, y = cols[2].strip().split("/")
        out[name].append((f"{y}-{m}-{d}", float(pu.replace(".", "").replace(",", "."))))
    return {k: sorted(v) for k, v in out.items() if v}
