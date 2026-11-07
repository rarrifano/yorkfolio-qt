#include "yorkfolio/book.hpp"

#include <algorithm>
#include <cstdio>

namespace yorkfolio {

namespace {

std::string str(const json& ev, const char* key) {
    auto it = ev.find(key);
    return (it != ev.end() && it->is_string()) ? it->get<std::string>() : std::string();
}

std::optional<double> num(const json& ev, const char* key) {
    auto it = ev.find(key);
    if (it == ev.end() || !it->is_number()) return std::nullopt;
    return it->get<double>();
}

std::string trim(const std::string& s) {
    const char* ws = " \t\r\n";
    auto a = s.find_first_not_of(ws);
    if (a == std::string::npos) return "";
    return s.substr(a, s.find_last_not_of(ws) - a + 1);
}

// Python's f"{x:g}".
std::string g(double x) {
    char buf[64];
    std::snprintf(buf, sizeof buf, "%g", x);
    return buf;
}

bool is_usd(const std::string& t) { return t == "stock" || t == "reit" || t == "etf_us" || t == "crypto"; }

void usd_cost(Position& p, const json& ev) {
    std::string t = str(ev, "asset_type");
    if (t.empty()) t = p.asset_type;
    if (!is_usd(t) || !p.cost_usd) return;
    if (str(ev, "currency") == "USD") {
        *p.cost_usd += num(ev, "value_ccy").value_or(0.0);
    } else {
        p.cost_usd.reset();
    }
}

}  // namespace

json Position::to_json() const {
    return {
        {"code", code},
        {"name", name},
        {"asset_type", asset_type},
        {"qty", qty},
        {"cost", cost},
        {"cost_usd", cost_usd ? json(*cost_usd) : json(nullptr)},
        {"realized", realized},
        {"realized_unknown", realized_unknown},
        {"proventos", proventos},
        {"first_date", first_date},
        {"last_date", last_date},
        {"institution", institution},
        {"anchor", anchor ? json::array({anchor->first, anchor->second}) : json(nullptr)},
    };
}

json Sale::to_json() const {
    return {{"date", date},         {"code", code},         {"asset_type", asset_type},
            {"qty", qty},           {"proceeds", proceeds}, {"cost", cost},
            {"gain", gain},         {"known", known},       {"daytrade", daytrade},
            {"institution", institution}};
}

Sale Sale::from_json(const json& j) {
    Sale s;
    s.date = str(j, "date");
    s.code = str(j, "code");
    s.asset_type = str(j, "asset_type");
    s.institution = str(j, "institution");
    s.qty = num(j, "qty").value_or(0.0);
    s.proceeds = num(j, "proceeds").value_or(0.0);
    s.cost = num(j, "cost").value_or(0.0);
    s.gain = num(j, "gain").value_or(0.0);
    s.known = j.value("known", true);
    s.daytrade = j.value("daytrade", false);
    return s;
}

void Book::warn(const json& ev, const std::string& msg, const char* level) {
    warnings_.push_back({{"level", level}, {"date", str(ev, "date")}, {"code", str(ev, "code")}, {"msg", msg}});
}

void Book::apply(const json& ev) {
    const std::string action = str(ev, "action");
    const std::string code = str(ev, "code");
    if (!str(ev, "name").empty()) names_[code] = str(ev, "name");
    if (action == "skip" || action == "ignore" || action == "dt_part") return;
    if (action == "unhandled") {
        std::string what = str(ev, "kind");
        if (what.empty()) what = str(ev, "label");
        warn(ev, trim("movimentação não tratada: “" + what + "” " + str(ev, "note")));
        return;
    }

    Position& p = positions_.try_emplace(code, Position(code)).first->second;
    if (!str(ev, "name").empty()) p.name = str(ev, "name");
    if (!str(ev, "asset_type").empty() && (p.asset_type.empty() || str(ev, "source") != "Negociação"))
        p.asset_type = str(ev, "asset_type");
    if (!str(ev, "institution").empty()) p.institution = str(ev, "institution");

    const std::string d = str(ev, "date");
    const double qty = num(ev, "qty").value_or(0.0);
    const std::optional<double> value = num(ev, "value");
    const double price = num(ev, "price").value_or(0.0);
    const double value0 = value.value_or(0.0);

    if (action == "buy") {
        const double amount = value ? *value : qty * price;
        if (p.qty <= EPS) {
            p.first_date = d;
            p.cost_usd = 0.0;
        }
        p.qty += qty;
        p.cost += amount;
        usd_cost(p, ev);
        flows_.emplace_back(d, amount);
        if (price != 0.0) p.anchor = {d, price};
    } else if (action == "sell" || action == "fraction_out") {
        if (p.qty <= EPS) {
            warn(ev, "saída de " + g(qty) + " sem posição em carteira (histórico incompleto?)");
            return;
        }
        if (qty - p.qty > 1e-6) warn(ev, "saída de " + g(qty) + " maior que a posição (" + g(p.qty) + ")");
        const double q = std::min(qty, p.qty);
        const double frac = q / p.qty;
        const double cost_out = p.cost * frac;
        if (action == "sell") {
            const bool known = value0 != 0.0;
            const double proceeds = known ? value0 : cost_out;  // unknown proceeds: assume no gain
            if (known)
                p.realized += proceeds - cost_out;
            else
                p.realized_unknown = true;
            sales_.push_back({d, p.code, p.asset_type, str(ev, "institution"), q, proceeds, cost_out,
                              proceeds - cost_out, known, false});
            flows_.emplace_back(d, -proceeds);
        }
        p.qty -= q;
        p.cost -= cost_out;
        if (p.cost_usd) *p.cost_usd -= *p.cost_usd * frac;
        if (price != 0.0) p.anchor = {d, price};
        if (p.qty <= 1e-9) p.qty = p.cost = 0.0;
    } else if (action == "daytrade") {
        const double sell_value = num(ev, "sell_value").value_or(0.0), buy_value = num(ev, "buy_value").value_or(0.0);
        const double gain = sell_value - buy_value;
        p.realized += gain;
        sales_.push_back({d, p.code, p.asset_type, str(ev, "institution"), qty, sell_value, buy_value, gain, true, true});
        flows_.emplace_back(d, -gain);
    } else if (action == "bonus") {
        p.qty += qty;
        p.cost += value0;
        if (value0 == 0.0)
            warn(ev,
                 "bonificação de " + g(qty) +
                     " ações registrada com custo R$ 0 (a B3 não informa o custo atribuído; use um lançamento "
                     "manual de ajuste de custo se quiser corrigir)",
                 "info");
    } else if (action == "split") {
        p.qty += qty;
    } else if (action == "reverse_split") {
        p.qty += str(ev, "direction") == "C" ? qty : -qty;
        warn(ev, "grupamento: confira a quantidade final", "info");
    } else if (action == "capital_return") {
        p.cost = std::max(0.0, p.cost - value0);
        flows_.emplace_back(d, -value0);
    } else if (action == "provento") {
        p.proventos += value0;
        proventos_.push_back({{"date", d},
                              {"code", p.code},
                              {"type", str(ev, "label")},
                              {"asset_type", p.asset_type},
                              {"qty", num(ev, "qty") ? json(*num(ev, "qty")) : json(nullptr)},
                              {"unit", num(ev, "price") ? json(*num(ev, "price")) : json(nullptr)},
                              {"value", value0}});
        flows_.emplace_back(d, -value0);
    } else if (action == "adjust") {
        p.cost += value0;
        usd_cost(p, ev);
        flows_.emplace_back(d, value0);
    }
    p.last_date = d;
}

json Book::to_json(bool full, std::size_t from_flow, bool open_only) const {
    json out;
    json pos = json::object();
    for (const auto& [code, p] : positions_)
        if (!open_only || p.qty > EPS) pos[code] = p.to_json();
    out["positions"] = std::move(pos);
    json flows = json::array();
    for (std::size_t i = from_flow; i < flows_.size(); ++i) flows.push_back({flows_[i].first, flows_[i].second});
    out["flows"] = std::move(flows);
    if (full) {
        json sales = json::array();
        for (const auto& s : sales_) sales.push_back(s.to_json());
        out["sales"] = std::move(sales);
        out["proventos"] = proventos_;
        out["warnings"] = warnings_;
        out["names"] = names_;
    }
    return out;
}

}  // namespace yorkfolio
