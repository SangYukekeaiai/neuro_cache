#pragma once
// Port of config.py's CacheConfig: cache_size_bytes, line_size_bytes,
// cache_type, inner_dim, policy, associativity, layout, cin_block/
// cout_block and the four shape bounds -- same fields, same
// capacity_lines derivation. Validation (positivity, associativity only
// for set_associative, divisibility) is the CLI/bridge caller's job here
// (src/cachesim/config.py's CacheConfig already validates before the
// bridge ever shells out -- see native_bridge.py), so this struct itself
// stays a plain value type, no __post_init__ equivalent.
#include <cstdint>
#include <stdexcept>
#include <string>

#include "dims.h"

namespace cachesim {

enum class CacheType { DirectMapped, SetAssociative, FullyAssociative };

inline CacheType cache_type_from_name(const std::string &s) {
    if (s == "direct_mapped") return CacheType::DirectMapped;
    if (s == "set_associative") return CacheType::SetAssociative;
    if (s == "fully_associative") return CacheType::FullyAssociative;
    throw std::runtime_error("cachesim: unknown cache_type '" + s + "'");
}

// config.py's LAYOUTS: InnerDim collapses only `inner_dim`, Hybrid keeps
// kh/kw exact and collapses cin and cout by their own block sizes.
enum class Layout { InnerDim, Hybrid };

inline Layout layout_from_name(const std::string &s) {
    if (s == "inner_dim") return Layout::InnerDim;
    if (s == "hybrid") return Layout::Hybrid;
    throw std::runtime_error("cachesim: unknown layout '" + s + "'");
}

struct CacheConfig {
    int64_t cache_size_bytes;
    int64_t line_size_bytes;
    CacheType cache_type;
    Dim inner_dim; // unused when layout == Hybrid
    int64_t associativity; // 0 means "not set" (direct_mapped / fully_associative)
    std::string policy;
    Layout layout = Layout::InnerDim;
    int64_t cin_block = 4, cout_block = 4;                   // Hybrid only
    int64_t kh_bound = 0, kw_bound = 0;                      // layer's true shape,
    int64_t cin_bound = 0, cout_bound = 0;                   // 0 means "not set"

    // capacity_lines property: cache_size_bytes // line_size_bytes, floored, minimum 1.
    int64_t capacity_lines() const {
        int64_t c = cache_size_bytes / line_size_bytes;
        return c < 1 ? 1 : c;
    }
};

} // namespace cachesim
