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

// When set, checks still count but print nothing. Used only by the
// expect-failure driver in test_layout.cpp, which drives deliberately broken
// code through the ordinary checks and cares about the count rather than the
// text: a run that printed twenty FAIL lines and then exited 0 would be
// unreadable, and would train the reader to skim past FAIL. Nothing else sets
// it, so the positive suites are unaffected.
inline bool g_quiet = false;

// Scoped, so an early return or a throw inside the body cannot leave the rest
// of the run silent. That is not hypothetical here: the checks it wraps are
// deliberately being fed mappers that throw where they should not.
class Quiet {
public:
    Quiet() : saved_(g_quiet) { g_quiet = true; }
    ~Quiet() { g_quiet = saved_; }
    Quiet(const Quiet&) = delete;
    Quiet& operator=(const Quiet&) = delete;

private:
    bool saved_;
};

inline void group(const char* name) {
    if (!g_quiet) std::printf("\n== %s\n", name);
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

// Two overloads rather than one, and both are constrained through their return
// type so that exactly one is viable for any given T. Written as a single
// unconstrained template plus a tagged-scalar one, the two would have identical
// signatures and every call would be ambiguous.
//
// The second exists because U16 typed Placement's fields, so CHECK_EQ now
// compares SetIndex against SetIndex and TagId against TagId and has to print
// them. It only affects PRINTING: eq() still needs `a == b`, and Tagged has no
// operator== against its representation, so a check comparing a tagged scalar
// to a raw int is still a compile error. The wall is unchanged.
template <typename T>
auto to_str(const T& v) -> decltype(std::to_string(v)) {
    return std::to_string(v);
}

template <typename T>
auto to_str(const T& v) -> decltype(std::to_string(v.get())) {
    return std::to_string(v.get());
}

template <typename A, typename B>
void eq(const char* file, int line, const char* expr, const A& a, const B& b) {
    ++g_checks;
    if (!(a == b)) {
        ++g_failures;
        if (!g_quiet)
            std::printf("FAIL %s:%d\n  expr     : %s\n  actual   : %s\n  expected : %s\n",
                        file, line, expr, to_str(a).c_str(), to_str(b).c_str());
    }
}

inline void is_true(const char* file, int line, const char* expr, bool cond) {
    ++g_checks;
    if (!cond) {
        ++g_failures;
        if (!g_quiet) std::printf("FAIL %s:%d\n  expected true: %s\n", file, line, expr);
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
//
// The caught reference is check_ex_, not e: a caller whose own parameter is
// named `e` (an Env, a Burst) otherwise gets a -Wshadow warning pointing into
// this macro, which reads as a bug in the caller and is not one.
#define CHECK_THROWS(ExcType, expr)                                          \
    do {                                                                     \
        ++check::g_checks;                                                   \
        bool threw_expected = false;                                         \
        std::string other;                                                   \
        try {                                                                \
            (void)(expr);                                                    \
        } catch (const ExcType&) {                                           \
            threw_expected = true;                                           \
        } catch (const std::exception& check_ex_) {                          \
            other = check_ex_.what();                                        \
        } catch (...) {                                                      \
            other = "(non-std exception)";                                   \
        }                                                                    \
        if (!threw_expected) {                                               \
            ++check::g_failures;                                             \
            if (!check::g_quiet)                                             \
                std::printf("FAIL %s:%d\n  expected %s from: %s\n  got      : %s\n", \
                            __FILE__, __LINE__, #ExcType, #expr,             \
                            other.empty() ? "no exception" : other.c_str()); \
        }                                                                    \
    } while (0)
