"""Parsers for B3 "Área do Investidor" exports (Extratos → Baixar → Excel).

* negociacao-*.xlsx    trades: Data do Negócio, Tipo de Movimentação, Mercado, Código de Negociação…
* movimentacao-*.xlsx  everything else: settlements, proventos, corporate events, fixed income…
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from collections import Counter
from datetime import date, datetime, timedelta

from .assets import LISTED_TYPES
from .xlsx import read_rows

EPS = 1e-9

# "11" tickers are ambiguous (FII, ETF or unit). Names in Movimentação usually tell
# them apart; these lists cover the common cases when only Negociação is available.
KNOWN_UNITS = {
    "TAEE11",
    "SAPR11",
    "KLBN11",
    "SANB11",
    "BPAC11",
    "ALUP11",
    "ENGI11",
    "SULA11",
    "IGTI11",
    "BRBI11",
    "CPLE11",
    "AESB11",
    "RNEW11",
}
KNOWN_ETFS = {
    "BOVA11",
    "BOVV11",
    "BOVX11",
    "IVVB11",
    "SMAL11",
    "SMAC11",
    "HASH11",
    "GOLD11",
    "DIVO11",
    "XINA11",
    "NASD11",
    "SPXI11",
    "ACWI11",
    "ECOO11",
    "BRAX11",
    "PIBB11",
    "FIND11",
    "MATB11",
    "IMAB11",
    "B5P211",
    "FIXA11",
    "IRFM11",
    "LFTS11",
    "DEBB11",
    "TECK11",
    "QBTC11",
    "ETHE11",
    "BITH11",
    "WRLD11",
    "EURP11",
    "SPXB11",
    "NDIV11",
}

# Movimentação labels (normalized) that are cash income.
PROVENTOS = {
    "dividendo": "Dividendo",
    "juros sobre capital proprio": "JCP",
    "rendimento": "Rendimento",
    "amortizacao": "Amortização",
    "juros": "Juros",
    "pagamento de juros": "Juros",
    "leilao de fracao": "Leilão de Fração",
    "reembolso": "Reembolso",
}
# Fixed-income labels: Credito = money in (buy), Debito = money out (sell/redeem).
FIXED_INCOME_OPS = {"aplicacao", "compra", "venda", "compra / venda", "resgate", "resgate antecipado", "vencimento"}
# Informational / net-zero movements (custody transfers, securities lending, ISIN updates).
IGNORED = {"atualizacao", "transferencia"}

_FRACTIONAL = re.compile(r"^([A-Z0-9]{4}\d{1,2})F$")
_LISTED_PRODUCT = re.compile(r"^([A-Z0-9]{4}\d{1,2}[A-Z]?)\s+-\s+(.+)$")
_FIXED_INCOME_PRODUCT = re.compile(
    r"^(CDB|LCI|LCA|LCD|LC|LF|LIG|RDB|CRI|CRA|DEB|DEBENTURE|COE)\s*-\s*(\S+)(?:\s+-\s+(.+))?$", re.I
)


# ---------------------------------------------------------------- helpers
def norm(value) -> str:
    """Lower-case, accent-free, whitespace-collapsed text (for matching B3 labels)."""
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", text).strip().lower()


def parse_num(value) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    text = str(value).replace("R$", "").replace("\xa0", "").replace(" ", "").strip()
    if text in ("", "-", "--"):
        return None
    if "," in text and "." in text:  # 1.234,56 (pt-BR) or 1,234.56
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    elif "," in text:
        text = text.replace(",", ".")
    elif re.fullmatch(r"-?[1-9]\d{0,2}(\.\d{3})+", text):  # 4.000 / 1.234.567 = pt-BR thousands
        text = text.replace(".", "")
    try:
        return float(text)
    except ValueError:
        return None


def parse_date(value) -> str | None:
    """dd/mm/yyyy, ISO or Excel serial -> 'YYYY-MM-DD'."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return (date(1899, 12, 30) + timedelta(days=int(value))).isoformat()
    text = str(value).strip()
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d/%m/%y", "%d-%m-%Y"):
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def base_ticker(ticker: str) -> str:
    """ABEV3F (mercado fracionário) -> ABEV3."""
    t = (ticker or "").strip().upper()
    m = _FRACTIONAL.match(t)
    return m.group(1) if m else t


def listed_type(code: str, name: str = "") -> str:
    """Guess acao / fii / etf / bdr for a B3 ticker (name helps with '11' tickers)."""
    n = norm(name)
    if re.search(r"\bfii\b|fdo inv imob|fundo de investimento imob|\bimob\b|fiagro", n):
        return "fii"
    if re.search(r"\betf\b|\bindice\b|ishares|it now", n):
        return "etf"
    m = re.match(r"^[A-Z0-9]{4}(\d{1,2})$", code or "")
    suffix = int(m.group(1)) if m else None
    if suffix in (3, 4, 5, 6, 7, 8):
        return "acao"
    if suffix in (32, 33, 34, 35, 39):
        return "bdr"
    if suffix == 11:
        if code in KNOWN_ETFS:
            return "etf"
        if code in KNOWN_UNITS or " s.a" in n or " s/a" in n or n.endswith(" sa"):
            return "acao"
        return "fii"
    return "outro"


def parse_product(product: str, institution: str = "") -> dict:
    """'ITUB3 - ITAU UNIBANCO…' / 'CDB - CDB123 - BANCO X' / 'Tesouro Selic 2031' -> code, name, type."""
    p = (product or "").strip()
    if norm(p).startswith("tesouro"):
        return {"code": p, "name": p, "asset_type": "tesouro"}
    m = _FIXED_INCOME_PRODUCT.match(p)
    if m:
        kind, ident, issuer = m.group(1).upper(), m.group(2).upper(), m.group(3)
        code = ident if ident.startswith(kind) else f"{kind} {ident}"
        return {"code": code, "name": f"{kind} {issuer or institution or ''}".strip(), "asset_type": "rf", "kind": kind}
    m = _LISTED_PRODUCT.match(p)
    if m:
        code = base_ticker(m.group(1))
        return {"code": code, "name": m.group(2).strip(), "asset_type": listed_type(code, m.group(2))}
    return {"code": p, "name": p, "asset_type": "outro"}


def classify_movement(m: dict) -> dict:
    """Map a Movimentação row to an engine action (+ asset info)."""
    info = parse_product(m["product"], m.get("institution") or "")
    kind = re.sub(r"\s*-\s*transferido$", "", norm(m["kind"]).rstrip("/ "))
    credit = m["direction"] == "C"
    listed = info["asset_type"] in LISTED_TYPES

    if kind in PROVENTOS:
        action, label = ("provento" if credit else "ignore"), PROVENTOS[kind]
    elif kind == "transferencia - liquidacao":
        action, label = "settlement", "Compra" if credit else "Venda"
    elif kind.startswith("bonificacao"):
        action, label = "bonus", "Bonificação"
    elif kind.startswith("desdobr"):
        action, label = "split", "Desdobramento"
    elif kind == "grupamento":
        action, label = "reverse_split", "Grupamento"
    elif kind == "restituicao de capital":
        action, label = "capital_return", "Restituição de Capital"
    elif kind == "fracao em ativos":
        action, label = ("ignore" if credit else "fraction_out"), "Fração em Ativos"
    elif kind in IGNORED or kind.startswith("emprestimo"):
        action, label = "ignore", m["kind"]
    elif not listed and kind in FIXED_INCOME_OPS:
        action = "buy" if credit else "sell"
        label = {"aplicacao": "Aplicação", "vencimento": "Vencimento"}.get(
            kind, ("Compra" if credit else "Venda") if "compra" in kind or kind == "venda" else "Resgate"
        )
    else:
        action, label = "unhandled", m["kind"]
    return {**info, "action": action, "label": label}


# ---------------------------------------------------------------- file parsing
# field -> (normalized header, required)
NEGOCIACAO = {
    "date": ("data do negocio", True),
    "side": ("tipo de movimentacao", True),
    "market": ("mercado", False),
    "maturity": ("prazo/vencimento", False),
    "institution": ("instituicao", False),
    "ticker": ("codigo de negociacao", True),
    "qty": ("quantidade", True),
    "price": ("preco", True),
    "value": ("valor", False),
}
MOVIMENTACAO = {
    "direction": ("entrada/saida", True),
    "date": ("data", True),
    "kind": ("movimentacao", True),
    "product": ("produto", True),
    "institution": ("instituicao", False),
    "qty": ("quantidade", False),
    "price": ("preco unitario", False),
    "value": ("valor da operacao", False),
}


def _detect(rows):
    for i, row in enumerate(rows[:15]):
        headers = [norm(c) for c in row]
        for kind, spec in (("negociacao", NEGOCIACAO), ("movimentacao", MOVIMENTACAO)):
            if all(h in headers for h, required in spec.values() if required):
                return kind, i, {f: headers.index(h) for f, (h, _) in spec.items() if h in headers}
    raise ValueError("formato não reconhecido: esperado o Excel de Negociação ou Movimentação da B3")


def _text(v) -> str:
    return "" if v is None else str(v).strip()


def _trade(get) -> dict | None:
    d, raw = parse_date(get("date")), _text(get("ticker")).upper()
    side = norm(get("side"))
    side = "C" if side.startswith("compra") else "V" if side.startswith("venda") else None
    qty, price, value = parse_num(get("qty")), parse_num(get("price")), parse_num(get("value"))
    if not d or not raw or not side or not qty:
        return None
    if value is None and price is not None:
        value = round(qty * price, 2)
    return {
        "date": d,
        "side": side,
        "market": _text(get("market")),
        "maturity": _text(get("maturity")),
        "institution": _text(get("institution")),
        "ticker": base_ticker(raw),
        "raw_ticker": raw,
        "qty": qty,
        "price": price,
        "value": value,
    }


def _movement(get) -> dict | None:
    d, product, kind = parse_date(get("date")), _text(get("product")), _text(get("kind"))
    direction = norm(get("direction"))
    direction = (
        "C" if direction.startswith(("cred", "entrada")) else "D" if direction.startswith(("deb", "saida")) else None
    )
    if not d or not product or not kind or not direction:
        return None
    return {
        "date": d,
        "direction": direction,
        "kind": kind,
        "product": product,
        "institution": _text(get("institution")),
        "qty": parse_num(get("qty")),
        "price": parse_num(get("price")),
        "value": parse_num(get("value")),
    }


def _identity(kind: str, r: dict) -> str:
    """Content key used to de-duplicate rows across overlapping exports."""
    if kind == "negociacao":
        parts = [
            "T",
            r["date"],
            r["side"],
            norm(r["market"]),
            norm(r["institution"]),
            r["raw_ticker"],
            r["qty"],
            r["price"],
        ]
    else:
        code = parse_product(r["product"])["code"]
        parts = [
            "M",
            r["date"],
            r["direction"],
            norm(r["kind"]),
            code,
            norm(r["institution"]),
            r["qty"],
            r["price"],
            r["value"],
        ]
    return "|".join(map(str, parts))


def parse_file(data: bytes, source: str = "") -> tuple[str, list[dict]]:
    """Parse a B3 .xlsx export. Returns (kind, records) with a stable `uid` per record."""
    rows = read_rows(data)
    kind, header, cols = _detect(rows)
    builder = _trade if kind == "negociacao" else _movement
    seen, records = Counter(), []
    for row in rows[header + 1 :]:
        rec = builder(lambda f, row=row: row[cols[f]] if f in cols and cols[f] < len(row) else None)
        if rec is None:
            continue
        ident = _identity(kind, rec)
        seen[ident] += 1  # identical rows inside one file are legit (e.g. two equal trades)
        rec["uid"] = hashlib.sha1(f"{ident}#{seen[ident]}".encode()).hexdigest()
        rec["source"] = source
        records.append(rec)
    return kind, records
