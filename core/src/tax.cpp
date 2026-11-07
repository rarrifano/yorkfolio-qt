// SPDX-FileCopyrightText: 2026 rarrifano
// SPDX-License-Identifier: MIT

#include "yorkfolio/tax.hpp"

#include <algorithm>
#include <chrono>
#include <cstdio>
#include <map>
#include <string>
#include <utility>
#include <vector>

#include "yorkfolio/book.hpp"

namespace yorkfolio::tax {

namespace {

using json = nlohmann::json;

constexpr double EXEMPTION = 20000.0;
constexpr double DARF_MIN = 10.0;
constexpr const char* BUCKETS[] = {"comum", "daytrade", "fii"};

double rate(const std::string& bucket) { return bucket == "comum" ? 0.15 : 0.20; }

// "" when the sale is outside this report (fixed income, exterior, crypto).
std::string category(const Sale& s) {
    if (s.asset_type == "fii") return "fii";
    if (s.asset_type == "acao" || s.asset_type == "etf" || s.asset_type == "bdr")
        return s.daytrade ? "daytrade" : "comum";
    return "";
}

// Shares: ticker = 4 alphanumerics + a digit 3..8.
bool exempt_eligible(const Sale& s) {
    if (s.asset_type != "acao" || s.daytrade || s.code.size() != 5) return false;
    for (int i = 0; i < 4; ++i) {
        char c = s.code[i];
        if (!((c >= 'A' && c <= 'Z') || (c >= '0' && c <= '9'))) return false;
    }
    return s.code[4] >= '3' && s.code[4] <= '8';
}

std::string month_str(int y, int m) {
    char buf[32];
    std::snprintf(buf, sizeof buf, "%04d-%02d", y, m);
    return buf;
}

// Sum grouped by key keeping first-seen order (stable floating-point results).
struct Grouped {
    std::vector<double> sums;
    std::map<std::pair<std::string, std::string>, std::size_t> index;
    void add(const Sale& s, double v) {
        auto [it, inserted] = index.try_emplace({s.date, s.institution}, sums.size());
        if (inserted) sums.push_back(0.0);
        sums[it->second] += v;
    }
};

double irrf(const std::vector<const Sale*>& sales) {
    Grouped swing, day;
    for (const Sale* s : sales) {
        if (s->daytrade)
            day.add(*s, s->gain);
        else
            swing.add(*s, s->proceeds);
    }
    double a = 0.0, b = 0.0;
    for (double v : swing.sums)
        if (v * 0.00005 > 1.0) a += v * 0.00005;
    for (double g : day.sums)
        if (g > 0) b += g * 0.01;
    return a + b;
}

}  // namespace

std::string due_date(const std::string& ym) {
    using namespace std::chrono;
    int y = std::stoi(ym.substr(0, 4)), m = std::stoi(ym.substr(5, 2));
    if (m == 12) { ++y; m = 1; } else { ++m; }
    sys_days d{year{y} / std::chrono::month{static_cast<unsigned>(m)} / last};
    while (weekday{d} == Saturday || weekday{d} == Sunday) d -= days{1};
    year_month_day ymd{d};
    char buf[32];
    std::snprintf(buf, sizeof buf, "%04d-%02u-%02u", int(ymd.year()), unsigned(ymd.month()), unsigned(ymd.day()));
    return buf;
}

json monthly(const json& sales_json) {
    std::vector<Sale> all;
    for (const auto& j : sales_json) {
        Sale s = Sale::from_json(j);
        if (!category(s).empty()) all.push_back(std::move(s));
    }
    if (all.empty()) return json::array();

    std::map<std::string, std::vector<const Sale*>> by_month;
    for (const auto& s : all) by_month[s.date.substr(0, 7)].push_back(&s);

    std::map<std::string, double> carry{{"comum", 0.0}, {"daytrade", 0.0}, {"fii", 0.0}};
    double darf_carry = 0.0, irrf_carry = 0.0;
    std::string year;
    json rows = json::array();

    const std::string first = by_month.begin()->first, last = by_month.rbegin()->first;
    int y = std::stoi(first.substr(0, 4)), m = std::stoi(first.substr(5, 2));
    for (std::string month = first; month <= last;) {
        if (month.substr(0, 4) != year) {
            year = month.substr(0, 4);
            irrf_carry = 0.0;
        }
        static const std::vector<const Sale*> none;
        auto it = by_month.find(month);
        const auto& ss = it == by_month.end() ? none : it->second;

        double share_sales = 0, share_gain = 0, others = 0;
        std::map<std::string, double> result{{"comum", 0.0}, {"daytrade", 0.0}, {"fii", 0.0}};
        for (const Sale* s : ss) {
            if (exempt_eligible(*s)) {
                share_sales += s->proceeds;
                share_gain += s->gain;
            }
        }
        const bool exempt = share_sales <= EXEMPTION;
        for (const Sale* s : ss) {
            const std::string cat = category(*s);
            if (cat == "comum" && !exempt_eligible(*s)) others += s->gain;
            if (cat == "daytrade" || cat == "fii") result[cat] += s->gain;
        }
        result["comum"] = others + (exempt ? std::min(share_gain, 0.0) : share_gain);

        json detail = json::object();
        double tax = 0.0;
        for (const char* bucket : BUCKETS) {
            const double r = result[bucket];
            double used = 0.0, base = 0.0;
            if (r > 0) {
                used = std::min(r, carry[bucket]);
                base = r - used;
                carry[bucket] -= used;
            } else {
                carry[bucket] -= r;
            }
            detail[bucket] = {{"result", r},
                              {"compensated", used},
                              {"base", base},
                              {"tax", base * rate(bucket)},
                              {"carry", carry[bucket]}};
            tax += base * rate(bucket);
        }
        const double ir = irrf(ss);
        const double due = tax - ir - irrf_carry;
        irrf_carry = std::max(0.0, -due);
        const double total = std::max(0.0, due) + darf_carry;
        const double pay = total >= DARF_MIN ? total : 0.0;
        darf_carry = total - pay;

        rows.push_back({{"month", month},
                        {"share_sales", share_sales},
                        {"exempt", exempt && share_sales > 0},
                        {"exempt_gain", exempt ? std::max(share_gain, 0.0) : 0.0},
                        {"categories", detail},
                        {"tax", tax},
                        {"irrf", ir},
                        {"darf", pay},
                        {"darf_pending", darf_carry},
                        {"due_date", pay != 0.0 ? json(due_date(month)) : json(nullptr)},
                        {"n_sales", ss.size()}});

        if (m == 12) { ++y; m = 1; } else { ++m; }
        month = month_str(y, m);
    }
    return rows;
}

}  // namespace yorkfolio::tax
