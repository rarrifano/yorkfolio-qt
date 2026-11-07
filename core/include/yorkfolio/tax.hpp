// SPDX-FileCopyrightText: 2026 rarrifano
// SPDX-License-Identifier: MIT

// Brazilian IR (income tax) monthly apuração for B3 variable income.
#pragma once

#include <nlohmann/json.hpp>

namespace yorkfolio::tax {

// `sales` is an array of sale objects as produced by Book (date, code, asset_type, qty, proceeds,
// cost, gain, known, daytrade, institution). Returns one object per month between the first and
// last month with taxable sales (without the sales themselves).
nlohmann::json monthly(const nlohmann::json& sales);

// Last weekday of the month after `month` ("YYYY-MM"); holidays are not considered.
std::string due_date(const std::string& month);

}  // namespace yorkfolio::tax
