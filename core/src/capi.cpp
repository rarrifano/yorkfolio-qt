// SPDX-FileCopyrightText: 2026 rarrifano
// SPDX-License-Identifier: MIT

#include "yorkfolio/capi.h"

#include <cstdlib>
#include <cstring>
#include <exception>
#include <string>
#include <vector>

#include "yorkfolio/aporte.hpp"
#include "yorkfolio/book.hpp"
#include "yorkfolio/tax.hpp"

using nlohmann::json;

namespace {

char* dup(const std::string& s) {
    char* out = static_cast<char*>(std::malloc(s.size() + 1));
    if (out) std::memcpy(out, s.c_str(), s.size() + 1);
    return out;
}

char* error(const std::exception& e) { return dup(json{{"error", e.what()}}.dump()); }

template <class F>
char* guarded(F&& f) {
    try {
        return dup(f().dump());
    } catch (const std::exception& e) {
        return error(e);
    }
}

}  // namespace

extern "C" {

const char* yf_version(void) { return "0.1.0"; }

void yf_free(char* s) { std::free(s); }

void* yf_book_new(void) { return new yorkfolio::Book(); }

void yf_book_free(void* book) { delete static_cast<yorkfolio::Book*>(book); }

char* yf_book_apply(void* book, const char* events) {
    try {
        auto* b = static_cast<yorkfolio::Book*>(book);
        for (const auto& ev : json::parse(events)) b->apply(ev);
        return nullptr;
    } catch (const std::exception& e) {
        return error(e);
    }
}

char* yf_book_json(void* book, int full, size_t from_flow, int open_only) {
    return guarded([&] { return static_cast<yorkfolio::Book*>(book)->to_json(full != 0, from_flow, open_only != 0); });
}

char* yf_tax_monthly(const char* sales) {
    return guarded([&] { return yorkfolio::tax::monthly(json::parse(sales)); });
}

char* yf_waterfill(const char* current, const char* weights, double amount) {
    return guarded([&] {
        return json(yorkfolio::waterfill(json::parse(current).get<std::vector<double>>(),
                                         json::parse(weights).get<std::vector<double>>(), amount));
    });
}

char* yf_plan_aporte(const char* classes, double amount) {
    return guarded([&] { return yorkfolio::plan_aporte(json::parse(classes), amount); });
}

}  // extern "C"
