#include "layout_common.h"

#include <cstdint>
#include <stdexcept>
#include <string>

namespace cachesim {
namespace detail {

void reject(const char* cls, const std::string& what) {
    throw std::invalid_argument(std::string(cls) + ": " + what);
}

void reject_range(const char* cls, const std::string& what) {
    throw std::out_of_range(std::string(cls) + ": " + what);
}

std::int64_t checked_mul(const char* cls, std::int64_t a, std::int64_t b, const char* what) {
    if (b > INT64_MAX / a) {
        reject(cls, std::string(what) + " overflows a signed 64-bit value: " +
                        std::to_string(a) + " * " + std::to_string(b));
    }
    return a * b;
}

void check_shape_and_blocking(const char* cls, const WeightShape& shape,
                              std::int32_t cin_block, std::int32_t cout_block,
                              std::int32_t weight_bytes) {
    for (Axis a : kAxes) {
        const std::int32_t n = extent_on(shape, a);
        if (n < 1) {
            reject(cls, std::string(axis_name(a)) + " extent must be >= 1, got " +
                            std::to_string(n));
        }
    }
    positive_or_reject(cls, "cin_block", cin_block);
    positive_or_reject(cls, "cout_block", cout_block);
    positive_or_reject(cls, "weight_bytes", weight_bytes);
}

std::int64_t line_size_bytes(const char* cls, std::int32_t cin_block, std::int32_t cout_block,
                             std::int32_t weight_bytes) {
    return checked_mul(cls, checked_mul(cls, cin_block, cout_block, "line_size_bytes"),
                       weight_bytes, "line_size_bytes");
}

std::string line_size_terms(std::int32_t cin_block, std::int32_t cout_block,
                            std::int32_t weight_bytes) {
    return "cin_block " + std::to_string(cin_block) + " x cout_block " +
           std::to_string(cout_block) + " x weight_bytes " + std::to_string(weight_bytes);
}

}  // namespace detail
}  // namespace cachesim
