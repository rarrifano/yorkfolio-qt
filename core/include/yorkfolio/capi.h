// SPDX-FileCopyrightText: 2026 rarrifano
// SPDX-License-Identifier: MIT

/* Plain C interface of the YorkFolio core, meant for ctypes/FFI.
 * Every function taking or returning text uses UTF-8 JSON. Returned strings are owned by the
 * caller and must be released with yf_free(). Errors are reported as {"error": "message"}. */
#ifndef YORKFOLIO_CAPI_H
#define YORKFOLIO_CAPI_H

#include <stddef.h>

#ifdef _WIN32
#define YF_API __declspec(dllexport)
#else
#define YF_API __attribute__((visibility("default")))
#endif

#ifdef __cplusplus
extern "C" {
#endif

YF_API const char* yf_version(void);
YF_API void yf_free(char* s);

/* Position book. `events` is a JSON array of ledger events. Returns NULL on success. */
YF_API void* yf_book_new(void);
YF_API void yf_book_free(void* book);
YF_API char* yf_book_apply(void* book, const char* events);
/* {"positions", "flows"[, "sales", "proventos", "warnings", "names"]} */
YF_API char* yf_book_json(void* book, int full, size_t from_flow, int open_only);

/* Monthly IR apuração from a JSON array of sales. */
YF_API char* yf_tax_monthly(const char* sales);

/* Water-filling split: current/weights are JSON arrays of numbers; returns a JSON array. */
YF_API char* yf_waterfill(const char* current, const char* weights, double amount);

/* Aporte plan from a JSON array of classes. */
YF_API char* yf_plan_aporte(const char* classes, double amount);

#ifdef __cplusplus
}
#endif
#endif
