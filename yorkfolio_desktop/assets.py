"""Asset types: default class, quote currency and Yahoo Finance symbol pattern."""

from __future__ import annotations

ASSET_TYPES: dict[str, dict] = {
    "acao": {"label": "Ação (B3)", "class": "Ações", "currency": "BRL", "yahoo": "{code}.SA"},
    "fii": {"label": "FII", "class": "FIIs", "currency": "BRL", "yahoo": "{code}.SA"},
    "etf": {"label": "ETF (B3)", "class": "ETFs", "currency": "BRL", "yahoo": "{code}.SA"},
    "bdr": {"label": "BDR", "class": "BDRs", "currency": "BRL", "yahoo": "{code}.SA"},
    "stock": {"label": "Stock (EUA)", "class": "Stocks", "currency": "USD", "yahoo": "{code}"},
    "reit": {"label": "REIT (EUA)", "class": "REITs", "currency": "USD", "yahoo": "{code}"},
    "etf_us": {"label": "ETF (EUA)", "class": "Stocks", "currency": "USD", "yahoo": "{code}"},
    "crypto": {"label": "Cripto", "class": "Cripto", "currency": "USD", "yahoo": "{code}-USD"},
    "tesouro": {"label": "Tesouro Direto", "class": "Renda Fixa", "currency": "BRL", "yahoo": None},
    "rf": {"label": "Renda fixa (CDB, LCI, LCA…)", "class": "Renda Fixa", "currency": "BRL", "yahoo": None},
    "outro": {"label": "Outro", "class": "Outros", "currency": "BRL", "yahoo": None},
}

LISTED_TYPES = {"acao", "fii", "etf", "bdr"}  # traded on B3
QUOTED_TYPES = {t for t, m in ASSET_TYPES.items() if m["yahoo"]}  # have a market quote
FIXED_INCOME_TYPES = {"rf", "tesouro"}
STANDARD_CLASSES = ["Ações", "FIIs", "ETFs", "BDRs", "Stocks", "REITs", "Renda Fixa", "Cripto"]
FX_SYMBOL = "BRL=X"  # USD -> BRL
IBOV_SYMBOL = "^BVSP"


def default_class(asset_type: str) -> str:
    return ASSET_TYPES.get(asset_type, ASSET_TYPES["outro"])["class"]


def currency(asset_type: str) -> str:
    return ASSET_TYPES.get(asset_type, ASSET_TYPES["outro"])["currency"]


def yahoo_symbol(code: str, asset_type: str) -> str | None:
    pattern = ASSET_TYPES.get(asset_type, {}).get("yahoo")
    return pattern.format(code=code.upper()) if pattern else None
