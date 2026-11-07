// Weighted-average-cost position engine.
//
// A Book applies ledger events in date order and keeps positions, realized sales (for IR),
// proventos and external cash flows (+ money in, - money out) for return calculations.
#pragma once

#include <map>
#include <optional>
#include <string>
#include <utility>
#include <vector>

#include <nlohmann/json.hpp>

namespace yorkfolio {

using json = nlohmann::json;

constexpr double EPS = 1e-9;

struct Position {
    Position() = default;
    explicit Position(std::string c) : code(std::move(c)) {}

    std::string code, name, asset_type;
    double qty = 0.0;
    double cost = 0.0;                  // BRL
    std::optional<double> cost_usd = 0.0;  // nullopt: bought in another currency
    double realized = 0.0;
    bool realized_unknown = false;
    double proventos = 0.0;
    std::string first_date, last_date, institution;
    std::optional<std::pair<std::string, double>> anchor;  // last (date, unit price) seen in a trade

    json to_json() const;
};

struct Sale {
    std::string date, code, asset_type, institution;
    double qty = 0, proceeds = 0, cost = 0, gain = 0;
    bool known = true, daytrade = false;

    json to_json() const;
    static Sale from_json(const json& j);
};

class Book {
public:
    void apply(const json& event);

    // Positions that were ever opened (or only open ones), flows from `from_flow` on and,
    // when `full`, also sales, proventos, warnings and names.
    json to_json(bool full, std::size_t from_flow = 0, bool open_only = false) const;

    std::size_t flow_count() const { return flows_.size(); }

private:
    void warn(const json& ev, const std::string& msg, const char* level = "warn");

    std::map<std::string, Position> positions_;
    std::vector<Sale> sales_;
    std::vector<json> proventos_;
    std::vector<std::pair<std::string, double>> flows_;
    std::vector<json> warnings_;
    std::map<std::string, std::string> names_;
};

}  // namespace yorkfolio
