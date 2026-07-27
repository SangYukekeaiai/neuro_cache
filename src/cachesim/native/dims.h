#pragma once
// Shared dim vocabulary: the (kh, kw, cin, cout) DIMS tuple from
// config.py, plus order-string parsing shared by layout.h.
#include <stdexcept>
#include <string>
#include <vector>

namespace cachesim {

enum Dim { KH = 0, KW = 1, CIN = 2, COUT = 3, N_DIMS = 4 };

inline Dim dim_from_name(const std::string &s) {
    if (s == "kh") return KH;
    if (s == "kw") return KW;
    if (s == "cin") return CIN;
    if (s == "cout") return COUT;
    throw std::runtime_error("cachesim: unknown dim name '" + s + "'");
}

// Parses an "order" CSV the same way layout.py's expand_events validates
// its `order` argument: must name all 4 dims exactly once. Its last
// entry is the ranged (start, end) one.
inline std::vector<Dim> parse_order(const std::string &csv) {
    std::vector<Dim> order;
    size_t start = 0;
    while (start <= csv.size()) {
        size_t comma = csv.find(',', start);
        std::string tok = csv.substr(start, comma == std::string::npos ? std::string::npos : comma - start);
        order.push_back(dim_from_name(tok));
        if (comma == std::string::npos) break;
        start = comma + 1;
    }
    if (order.size() != N_DIMS) throw std::runtime_error("cachesim: order must name all 4 dims");
    bool seen[N_DIMS] = {false, false, false, false};
    for (Dim d : order) seen[d] = true;
    for (bool b : seen)
        if (!b) throw std::runtime_error("cachesim: order must be a permutation of kh,kw,cin,cout");
    return order;
}

} // namespace cachesim
