// SPDX-FileCopyrightText: 2026 rarrifano
// SPDX-License-Identifier: MIT

// Minimal dependency-free tests for the C++ core.
#include <cmath>
#include <cstdio>

#include "yorkfolio/aporte.hpp"
#include "yorkfolio/book.hpp"
#include "yorkfolio/tax.hpp"

using namespace yorkfolio;

static int failures = 0;
#define CHECK(cond)                                                              \
    do {                                                                         \
        if (!(cond)) {                                                           \
            std::printf("FAIL %s:%d  %s\n", __FILE__, __LINE__, #cond);          \
            ++failures;                                                          \
        }                                                                        \
    } while (0)
static bool near(double a, double b) { return std::fabs(a - b) < 1e-6; }

static json ev(const char* date, const char* action, double qty, double value, const char* code = "PETR4") {
    return {{"date", date}, {"code", code}, {"action", action}, {"qty", qty}, {"value", value},
            {"price", qty ? value / qty : 0.0}, {"asset_type", "acao"}, {"source", "Negociação"},
            {"label", action}, {"direction", "C"}};
}

static void test_average_cost() {
    Book b;
    b.apply(ev("2024-01-02", "buy", 100, 1000));
    b.apply(ev("2024-02-02", "buy", 100, 2000));
    b.apply(ev("2024-03-02", "sell", 50, 900));
    auto j = b.to_json(true);
    const auto& p = j["positions"]["PETR4"];
    CHECK(near(p["qty"], 150));
    CHECK(near(p["cost"], 2250));  // avg 15 * 150
    CHECK(near(j["sales"][0]["gain"], 900 - 750));
    CHECK(near(j["flows"].size(), 3));
}

static void test_split_and_oversell() {
    Book b;
    b.apply(ev("2024-01-02", "buy", 10, 100));
    b.apply(ev("2024-01-03", "split", 10, 0));
    CHECK(near(b.to_json(false)["positions"]["PETR4"]["qty"], 20));
    b.apply(ev("2024-01-04", "sell", 30, 300));
    CHECK(b.to_json(true)["warnings"].size() == 1);
    CHECK(near(b.to_json(false)["positions"]["PETR4"]["qty"], 0));
}

static void test_waterfill() {
    auto a = waterfill({0, 100}, {0.5, 0.5}, 100);
    CHECK(near(a[0], 100) && near(a[1], 0));
    a = waterfill({0, 100}, {0.5, 0.5}, 300);
    CHECK(near(a[0], 200) && near(a[1], 100));
    a = waterfill({50}, {0}, 100);
    CHECK(near(a[0], 0));
}

static void test_due_date() {
    CHECK(tax::due_date("2024-04") == "2024-05-31");
    CHECK(tax::due_date("2024-11") == "2024-12-31");
    CHECK(tax::due_date("2024-12") == "2025-01-31");
    CHECK(tax::due_date("2024-05") == "2024-06-28");  // 30/06 is a Sunday
}

static void test_tax_exemption() {
    json sales = json::array({{{"date", "2024-03-10"}, {"code", "PETR4"}, {"asset_type", "acao"}, {"qty", 100},
                                {"proceeds", 15000.0}, {"cost", 10000.0}, {"gain", 5000.0}, {"known", true},
                                {"daytrade", false}, {"institution", "X"}}});
    auto rows = tax::monthly(sales);
    CHECK(rows.size() == 1);
    CHECK(rows[0]["exempt"] == true);
    CHECK(near(rows[0]["tax"], 0));
    sales[0]["proceeds"] = 25000.0;
    sales[0]["gain"] = 10000.0;
    rows = tax::monthly(sales);
    CHECK(near(rows[0]["tax"], 1500));
    CHECK(near(rows[0]["irrf"], 1.25));
    CHECK(near(rows[0]["darf"], 1498.75));
}

static void test_plan_errors() {
    bool threw = false;
    try { plan_aporte(json::array(), 0); } catch (const std::invalid_argument&) { threw = true; }
    CHECK(threw);
}

int main() {
    test_average_cost();
    test_split_and_oversell();
    test_waterfill();
    test_due_date();
    test_tax_exemption();
    test_plan_errors();
    std::puts(failures ? "FAILED" : "core tests passed");
    return failures ? 1 : 0;
}
