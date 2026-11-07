# SPDX-FileCopyrightText: 2026 rarrifano
# SPDX-License-Identifier: MIT

"""ctypes bridge to the C++ core (libyorkfolio_core).

The core speaks JSON over a plain C ABI (core/include/yorkfolio/capi.h), so no compiler,
Python headers or binding generator is needed at install time — only the shared library.
"""

from __future__ import annotations

import ctypes
import json
import os
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_EXT = {"darwin": "dylib", "win32": "dll"}.get(sys.platform, "so")
_NAME = f"libyorkfolio_core.{_EXT}"


class NativeError(RuntimeError):
    """The core reported an error (or could not be loaded)."""


def _load() -> ctypes.CDLL:
    candidates = [os.environ.get("YORKFOLIO_CORE", ""), _HERE / _NAME, _HERE.parent / "build" / _NAME]
    for path in candidates:
        if path and Path(path).exists():
            lib = ctypes.CDLL(str(path))
            break
    else:
        raise NativeError(f"{_NAME} not found: build the C++ core first (`make core`)")

    c_str = ctypes.c_void_p  # returned strings are freed by us, so keep the raw pointer
    lib.yf_version.restype = ctypes.c_char_p
    lib.yf_free.argtypes = [ctypes.c_void_p]
    lib.yf_book_new.restype = ctypes.c_void_p
    lib.yf_book_free.argtypes = [ctypes.c_void_p]
    lib.yf_book_apply.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
    lib.yf_book_apply.restype = c_str
    lib.yf_book_json.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_size_t, ctypes.c_int]
    lib.yf_book_json.restype = c_str
    lib.yf_tax_monthly.argtypes = [ctypes.c_char_p]
    lib.yf_tax_monthly.restype = c_str
    lib.yf_waterfill.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_double]
    lib.yf_waterfill.restype = c_str
    lib.yf_plan_aporte.argtypes = [ctypes.c_char_p, ctypes.c_double]
    lib.yf_plan_aporte.restype = c_str
    return lib


_lib: ctypes.CDLL | None = None


def lib() -> ctypes.CDLL:
    global _lib
    if _lib is None:
        _lib = _load()
    return _lib


def version() -> str:
    return lib().yf_version().decode()


def _dumps(obj) -> bytes:
    return json.dumps(obj, ensure_ascii=False, allow_nan=False).encode()


def _take(ptr: int | None):
    """Decode (and free) a string returned by the core; raise on {"error": ...}."""
    if not ptr:
        return None
    try:
        data = json.loads(ctypes.string_at(ptr).decode())
    finally:
        lib().yf_free(ptr)
    if isinstance(data, dict) and set(data) == {"error"}:
        raise ValueError(data["error"])
    return data


class NativeBook:
    """Handle to a C++ Book. Use `state()` to read it back as plain Python data."""

    def __init__(self):
        self._lib = lib()
        self._handle = self._lib.yf_book_new()

    def __del__(self):
        handle, self._handle = getattr(self, "_handle", None), None
        if handle:
            self._lib.yf_book_free(handle)

    def apply_all(self, events: list[dict]) -> None:
        _take(self._lib.yf_book_apply(self._handle, _dumps(events)))

    def state(self, full: bool = True, from_flow: int = 0, open_only: bool = False) -> dict:
        return _take(self._lib.yf_book_json(self._handle, int(full), from_flow, int(open_only)))


def tax_monthly(sales: list[dict]) -> list[dict]:
    return _take(lib().yf_tax_monthly(_dumps(sales)))


def plan_aporte(classes: list[dict], amount: float) -> dict:
    return _take(lib().yf_plan_aporte(_dumps(classes), float(amount)))


def waterfill(current: list[float], weights: list[float], amount: float) -> list[float]:
    return _take(lib().yf_waterfill(_dumps(current), _dumps(weights), float(amount)))
