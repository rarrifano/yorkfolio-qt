// Holder-style aporte planning ("water-filling").
#pragma once

#include <vector>

#include <nlohmann/json.hpp>

namespace yorkfolio {

// Split `amount` so the most underweight items (value / weight) are topped up first.
// Items with weight <= 0 never receive money and none is pushed past its target.
std::vector<double> waterfill(const std::vector<double>& current, const std::vector<double>& weights, double amount);

// `classes`: [{name, value, target, assets: [{code, name, value, nota, quoted, price_brl, asset_type}]}].
// Throws std::invalid_argument (pt-BR message) on invalid input.
nlohmann::json plan_aporte(const nlohmann::json& classes, double amount);

}  // namespace yorkfolio
