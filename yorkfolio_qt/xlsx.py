"""Minimal, dependency-free .xlsx reader: first worksheet -> list of rows."""

from __future__ import annotations

import io
import re
import xml.etree.ElementTree as ET
import zipfile

_NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_REL_NS = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
_PKG_REL_NS = "{http://schemas.openxmlformats.org/package/2006/relationships}"


def _col_index(ref: str) -> int:
    idx = 0
    for ch in re.match(r"[A-Z]+", ref).group(0):
        idx = idx * 26 + (ord(ch) - 64)
    return idx - 1


def _text(el) -> str:
    return "".join(t.text or "" for t in el.iter(f"{_NS}t"))


def _first_sheet_path(z: zipfile.ZipFile) -> str:
    try:
        wb = ET.fromstring(z.read("xl/workbook.xml"))
        rid = next(wb.iter(f"{_NS}sheet")).get(f"{_REL_NS}id")
        rels = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
        for rel in rels.iter(f"{_PKG_REL_NS}Relationship"):
            if rel.get("Id") == rid:
                target = rel.get("Target").lstrip("/")
                return target if target.startswith("xl/") else f"xl/{target}"
    except (KeyError, StopIteration, ET.ParseError):
        pass
    sheets = sorted(n for n in z.namelist() if n.startswith("xl/worksheets/sheet"))
    if not sheets:
        raise ValueError("arquivo .xlsx sem planilhas")
    return sheets[0]


def read_rows(data: bytes) -> list[list]:
    """Return the first worksheet as rows of str / float / bool / None."""
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise ValueError("não é um arquivo .xlsx válido") from exc
    with z:
        shared = []
        if "xl/sharedStrings.xml" in z.namelist():
            root = ET.fromstring(z.read("xl/sharedStrings.xml"))
            shared = [_text(si) for si in root.iter(f"{_NS}si")]
        sheet = ET.fromstring(z.read(_first_sheet_path(z)))

    rows = []
    for row in sheet.iter(f"{_NS}row"):
        values = {}
        for pos, c in enumerate(row.findall(f"{_NS}c")):
            kind, v = c.get("t", "n"), c.find(f"{_NS}v")
            if kind == "s":
                val = shared[int(v.text)] if v is not None else ""
            elif kind == "inlineStr":
                inline = c.find(f"{_NS}is")
                val = _text(inline) if inline is not None else ""
            elif kind == "b":
                val = v is not None and v.text == "1"
            elif kind in ("str", "e"):
                val = v.text if v is not None else ""
            else:
                val = float(v.text) if v is not None and v.text else None
            ref = c.get("r")
            values[_col_index(ref) if ref else pos] = val
        rows.append([values.get(i) for i in range(max(values) + 1)] if values else [])
    return rows
