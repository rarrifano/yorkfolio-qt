#include "yorkfolio/aporte.hpp"

#include <algorithm>
#include <cmath>
#include <limits>
#include <map>
#include <stdexcept>

namespace yorkfolio {

using json = nlohmann::json;

std::vector<double> waterfill(const std::vector<double>& current, const std::vector<double>& weights, double amount) {
    std::vector<double> alloc(current.size(), 0.0);
    std::vector<std::size_t> idx;
    for (std::size_t i = 0; i < weights.size(); ++i)
        if (weights[i] > 0) idx.push_back(i);
    if (amount <= 0 || idx.empty()) return alloc;

    double wsum = 0;
    for (auto i : idx) wsum += weights[i];
    std::map<std::size_t, double> w;
    for (auto i : idx) w[i] = weights[i] / wsum;

    std::stable_sort(idx.begin(), idx.end(),
                     [&](std::size_t a, std::size_t b) { return current[a] / w[a] < current[b] / w[b]; });
    double cum_value = 0, cum_weight = 0;
    for (std::size_t k = 0; k < idx.size(); ++k) {
        cum_value += current[idx[k]];
        cum_weight += w[idx[k]];
        const double level = (amount + cum_value) / cum_weight;
        const double next_ratio =
            k + 1 < idx.size() ? current[idx[k + 1]] / w[idx[k + 1]] : std::numeric_limits<double>::infinity();
        if (level <= next_ratio) {
            for (std::size_t j = 0; j <= k; ++j) alloc[idx[j]] = std::max(0.0, level * w[idx[j]] - current[idx[j]]);
            break;
        }
    }
    return alloc;
}

namespace {

double d(const json& j, const char* key) {
    auto it = j.find(key);
    return (it != j.end() && it->is_number()) ? it->get<double>() : 0.0;
}

std::string s(const json& j, const char* key) {
    auto it = j.find(key);
    return (it != j.end() && it->is_string()) ? it->get<std::string>() : std::string();
}

struct Row {
    std::string code, name;
    double price = 0, value = 0, nota = 0, ideal = 0, amount = 0;
    bool whole = false;
    long long qty = 0;
};

}  // namespace

json plan_aporte(const json& classes, double amount) {
    if (amount <= 0) throw std::invalid_argument("informe um valor de aporte positivo");
    bool any_target = false;
    for (const auto& c : classes) any_target = any_target || d(c, "target") > 0;
    if (!any_target) throw std::invalid_argument("defina as metas (%) por classe antes de calcular o aporte");

    std::vector<double> values, targets;
    for (const auto& c : classes) {
        values.push_back(d(c, "value"));
        targets.push_back(d(c, "target"));
    }
    const auto budgets = waterfill(values, targets, amount);

    json result = json::array();
    double leftover = 0.0;
    for (std::size_t ci = 0; ci < classes.size(); ++ci) {
        const json& c = classes[ci];
        const double budget = budgets[ci];
        if (budget < 0.01) continue;

        static const json no_assets = json::array();
        const json& assets = c.contains("assets") ? c["assets"] : no_assets;
        std::vector<const json*> cands;
        for (const auto& a : assets)
            if (d(a, "nota") > 0) cands.push_back(&a);
        if (cands.empty()) {
            result.push_back({{"class", s(c, "name")},
                              {"budget", budget},
                              {"spent", budget},
                              {"assets", json::array()},
                              {"note", "sem notas nesta classe: escolha livremente o ativo"}});
            continue;
        }

        std::vector<double> vals, notas;
        for (auto a : cands) {
            vals.push_back(d(*a, "value"));
            notas.push_back(d(*a, "nota"));
        }
        const auto ideal = waterfill(vals, notas, budget);

        std::vector<Row> rows;
        for (std::size_t i = 0; i < cands.size(); ++i) {
            const json& a = *cands[i];
            Row r{.code = s(a, "code"), .name = s(a, "name"), .price = d(a, "price_brl"), .value = d(a, "value"),
                  .nota = d(a, "nota"), .ideal = ideal[i]};
            r.whole = a.value("quoted", false) && r.price != 0.0 && s(a, "asset_type") != "crypto";
            if (r.whole) {
                r.qty = static_cast<long long>(std::floor(ideal[i] / r.price + 1e-9));
                r.amount = r.qty * r.price;
            } else {
                r.amount = ideal[i];
            }
            rows.push_back(r);
        }
        double spent = 0;
        for (const auto& r : rows) spent += r.amount;
        double left = budget - spent;
        for (;;) {  // spend what rounding left over: one more share of the most underweight that fits
            Row* best = nullptr;
            for (auto& r : rows) {
                if (!r.whole || r.price > left + 1e-9) continue;
                if (!best || (r.value + r.amount) / r.nota < (best->value + best->amount) / best->nota) best = &r;
            }
            if (!best) break;
            best->qty += 1;
            best->amount += best->price;
            left -= best->price;
        }
        leftover += left;

        std::vector<const Row*> kept;
        for (const auto& r : rows)
            if (r.amount >= 0.01) kept.push_back(&r);
        std::stable_sort(kept.begin(), kept.end(), [](const Row* a, const Row* b) { return a->amount > b->amount; });
        json out_assets = json::array();
        for (const Row* r : kept)
            out_assets.push_back({{"code", r->code},
                                  {"name", r->name},
                                  {"price", r->price != 0.0 ? json(r->price) : json(nullptr)},
                                  {"value", r->value},
                                  {"nota", r->nota},
                                  {"ideal", r->ideal},
                                  {"qty", r->whole ? json(r->qty) : json(nullptr)},
                                  {"amount", r->amount}});
        result.push_back(
            {{"class", s(c, "name")}, {"budget", budget}, {"spent", budget - left}, {"assets", out_assets}});
    }
    return {{"amount", amount}, {"leftover", leftover}, {"classes", result}};
}

}  // namespace yorkfolio
