// Minimal check harness for the wcache fixture tests.
//
// Deliberately not a framework. gtest 1.11 is installed in the conda base
// environment, but only as a shared object under miniconda/lib, so linking it
// would give every test binary a conda path dependency for the sake of
// assertion macros this file provides in thirty lines. Its one real advantage
// was death tests for the assert-only preconditions, and making expand's
// range check a throw closed most of that gap.
//
// Every failure prints and the run continues, so one invocation reports every
// failure rather than stopping at the first. Exit code is 1 if anything
// failed.
#pragma once

#include <cstdint>
#include <cstdio>
#include <exception>
#include <string>
#include <vector>

namespace check {

inline int g_checks   = 0;
inline int g_failures = 0;

inline void group(const char* name) {
    std::printf("\n== %s\n", name);
}

// Declared before eq(), so unqualified lookup at the template's definition
// point finds it. ADL would not: std::vector's associated namespace is std.
inline std::string to_str(const std::vector<std::int64_t>& v) {
    std::string s = "[";
    for (std::size_t i = 0; i < v.size(); ++i) {
        if (i != 0) s += ", ";
        s += std::to_string(v[i]);
    }
    return s + "]";
}

template <typename T>
std::string to_str(const T& v) {
    return std::to_string(v);
}

template <typename A, typename B>
void eq(const char* file, int line, const char* expr, const A& a, const B& b) {
    ++g_checks;
    if (!(a == b)) {
        ++g_failures;
        std::printf("FAIL %s:%d\n  expr     : %s\n  actual   : %s\n  expected : %s\n",
                    file, line, expr, to_str(a).c_str(), to_str(b).c_str());
    }
}

inline void is_true(const char* file, int line, const char* expr, bool cond) {
    ++g_checks;
    if (!cond) {
        ++g_failures;
        std::printf("FAIL %s:%d\n  expected true: %s\n", file, line, expr);
    }
}

// Signed size, so CHECK_EQ against an int literal does not trip -Wsign-compare.
template <typename T>
std::int64_t ssize(const T& c) {
    return static_cast<std::int64_t>(c.size());
}

inline int summary() {
    std::printf("\n%d checks, %d failures\n", g_checks, g_failures);
    return g_failures == 0 ? 0 : 1;
}

}  // namespace check

#define CHECK_EQ(actual, expected) \
    check::eq(__FILE__, __LINE__, #actual, (actual), (expected))

#define CHECK_TRUE(cond) \
    check::is_true(__FILE__, __LINE__, #cond, (cond))

// Names the exception type, because the code under test distinguishes them:
// invalid_argument for a bad configuration, out_of_range for a burst that
// leaves the tensor.
#define CHECK_THROWS(ExcType, expr)                                          \
    do {                                                                     \
        ++check::g_checks;                                                   \
        bool threw_expected = false;                                         \
        std::string other;                                                   \
        try {                                                                \
            (void)(expr);                                                    \
        } catch (const ExcType&) {                                           \
            threw_expected = true;                                           \
        } catch (const std::exception& e) {                                  \
            other = e.what();                                                \
        } catch (...) {                                                      \
            other = "(non-std exception)";                                   \
        }                                                                    \
        if (!threw_expected) {                                               \
            ++check::g_failures;                                             \
            std::printf("FAIL %s:%d\n  expected %s from: %s\n  got      : %s\n", \
                        __FILE__, __LINE__, #ExcType, #expr,                 \
                        other.empty() ? "no exception" : other.c_str());     \
        }                                                                    \
    } while (0)
