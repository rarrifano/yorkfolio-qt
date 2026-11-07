"""SQLite persistence: raw B3 rows, manual entries, user settings and the market-data cache."""

from __future__ import annotations

import os
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

APP_DIR = "yorkfolio-qt"


def data_dir() -> Path:
    """Where the portfolio database lives: $YORKFOLIO_DATA, else the OS per-user data directory."""
    if os.environ.get("YORKFOLIO_DATA"):
        return Path(os.environ["YORKFOLIO_DATA"]).expanduser()
    if sys.platform == "win32":
        return Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming")) / APP_DIR
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_DIR
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / APP_DIR


def default_db_path() -> Path:
    return data_dir() / "portfolio.db"


SCHEMA = """
CREATE TABLE IF NOT EXISTS trades (            -- B3 Negociação
    uid TEXT PRIMARY KEY, date TEXT NOT NULL, side TEXT NOT NULL, market TEXT, maturity TEXT,
    institution TEXT, ticker TEXT NOT NULL, raw_ticker TEXT, qty REAL NOT NULL, price REAL,
    value REAL, source TEXT, imported_at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS movements (         -- B3 Movimentação
    uid TEXT PRIMARY KEY, date TEXT NOT NULL, direction TEXT NOT NULL, kind TEXT NOT NULL,
    product TEXT NOT NULL, institution TEXT, qty REAL, price REAL, value REAL,
    source TEXT, imported_at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS manual_ops (        -- user-entered operations (exterior, crypto, fixes…)
    id INTEGER PRIMARY KEY AUTOINCREMENT, date TEXT NOT NULL, op TEXT NOT NULL, code TEXT NOT NULL,
    name TEXT, asset_type TEXT NOT NULL, qty REAL, price REAL, total REAL, fees REAL,
    currency TEXT NOT NULL DEFAULT 'BRL', fx REAL, kind TEXT, institution TEXT, note TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS assets (            -- per-asset settings & cached quotes
    code TEXT PRIMARY KEY, name TEXT, class TEXT, nota REAL, manual_price REAL,
    manual_value REAL, manual_value_at TEXT, quote REAL, quote_at TEXT, indexer TEXT, rate REAL,
    asset_type TEXT
);
CREATE TABLE IF NOT EXISTS class_targets (class TEXT PRIMARY KEY, target REAL NOT NULL);
CREATE TABLE IF NOT EXISTS series (            -- market data cache: Y:<symbol>, TD:<bond>, BCB:<n>
    key TEXT NOT NULL, date TEXT NOT NULL, value REAL NOT NULL, PRIMARY KEY (key, date)
);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
"""

TRADE_COLS = [
    "uid",
    "date",
    "side",
    "market",
    "maturity",
    "institution",
    "ticker",
    "raw_ticker",
    "qty",
    "price",
    "value",
    "source",
]
MOVEMENT_COLS = ["uid", "date", "direction", "kind", "product", "institution", "qty", "price", "value", "source"]
MANUAL_COLS = [
    "date",
    "op",
    "code",
    "name",
    "asset_type",
    "qty",
    "price",
    "total",
    "fees",
    "currency",
    "fx",
    "kind",
    "institution",
    "note",
]
ASSET_FIELDS = {"name", "class", "nota", "manual_price", "manual_value", "indexer", "rate", "asset_type"}


def now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _migrate(con) -> None:
    cols = {r["name"] for r in con.execute("PRAGMA table_info(assets)")}
    for col, kind in (("indexer", "TEXT"), ("rate", "REAL"), ("asset_type", "TEXT")):
        if col not in cols:
            con.execute(f"ALTER TABLE assets ADD COLUMN {col} {kind}")
    con.commit()


def connect(path: str | os.PathLike) -> sqlite3.Connection:
    """Open (creating/migrating) a portfolio database (default: default_db_path())."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    _migrate(con)
    return con


def insert_records(con, kind: str, records: list[dict]) -> int:
    table, cols = ("trades", TRADE_COLS) if kind == "negociacao" else ("movements", MOVEMENT_COLS)
    sql = f"INSERT OR IGNORE INTO {table} ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})"
    before = con.total_changes
    with con:
        con.executemany(sql, [[r.get(c) for c in cols] for r in records])
    return con.total_changes - before


def load(con) -> dict:
    series = defaultdict(list)
    for r in con.execute("SELECT key, date, value FROM series ORDER BY key, date"):
        series[r["key"]].append((r["date"], r["value"]))
    return {
        "trades": [dict(r) for r in con.execute("SELECT * FROM trades ORDER BY date")],
        "movements": [dict(r) for r in con.execute("SELECT * FROM movements ORDER BY date")],
        "manual": [dict(r) for r in con.execute("SELECT * FROM manual_ops ORDER BY date, id")],
        "settings": {r["code"]: dict(r) for r in con.execute("SELECT * FROM assets")},
        "targets": {r["class"]: r["target"] for r in con.execute("SELECT * FROM class_targets")},
        "series": dict(series),
        "meta": {r["key"]: r["value"] for r in con.execute("SELECT * FROM meta")},
    }


def update_asset(con, code: str, fields: dict) -> None:
    fields = {k: v for k, v in fields.items() if k in ASSET_FIELDS}
    for key in ("class", "indexer", "asset_type"):
        if isinstance(fields.get(key), str):
            fields[key] = fields[key].strip() or None
    if "manual_value" in fields:
        fields["manual_value_at"] = now() if fields["manual_value"] is not None else None
    with con:
        con.execute("INSERT OR IGNORE INTO assets (code) VALUES (?)", (code,))
        for key, value in fields.items():
            con.execute(f"UPDATE assets SET {key} = ? WHERE code = ?", (value, code))


def delete_asset_settings(con, code: str) -> None:
    with con:
        con.execute("DELETE FROM assets WHERE code = ?", (code,))


def set_targets(con, targets: dict[str, float]) -> None:
    with con:
        con.execute("DELETE FROM class_targets")
        con.executemany(
            "INSERT INTO class_targets (class, target) VALUES (?, ?)",
            [(k.strip(), float(v)) for k, v in targets.items() if k.strip() and v and float(v) > 0],
        )


def save_quotes(con, quotes: dict[str, float]) -> None:
    ts = now()
    with con:
        for code, price in quotes.items():
            con.execute("INSERT OR IGNORE INTO assets (code) VALUES (?)", (code,))
            con.execute("UPDATE assets SET quote = ?, quote_at = ? WHERE code = ?", (price, ts, code))


def add_manual(con, op: dict) -> int:
    with con:
        cur = con.execute(
            f"INSERT INTO manual_ops ({','.join(MANUAL_COLS)}) VALUES ({','.join('?' * len(MANUAL_COLS))})",
            [op.get(c) for c in MANUAL_COLS],
        )
    return cur.lastrowid


def delete_manual(con, op_id: int) -> None:
    with con:
        con.execute("DELETE FROM manual_ops WHERE id = ?", (op_id,))


def save_series(con, key: str, rows: list[tuple[str, float]], replace: bool = False) -> None:
    with con:
        if replace:
            con.execute("DELETE FROM series WHERE key = ?", (key,))
        con.executemany(
            "INSERT OR REPLACE INTO series (key, date, value) VALUES (?, ?, ?)", [(key, d, v) for d, v in rows]
        )


def series_last_date(con, key: str) -> str | None:
    row = con.execute("SELECT MAX(date) AS d FROM series WHERE key = ?", (key,)).fetchone()
    return row["d"] if row else None


def get_meta(con, key: str) -> str | None:
    row = con.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else None


def set_meta(con, key: str, value: str) -> None:
    with con:
        con.execute("INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)", (key, value))


def reset(con, everything: bool = False) -> None:
    with con:
        con.execute("DELETE FROM trades")
        con.execute("DELETE FROM movements")
        if everything:
            for table in ("manual_ops", "assets", "class_targets"):
                con.execute(f"DELETE FROM {table}")
