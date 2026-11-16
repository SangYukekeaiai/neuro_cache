// What cachesim_run and cachesim_sweep both need, stated once.
//
// This is CLI support and not library code: it is descriptors, usage errors,
// and a run id, none of which the engine, the reader or the stats have any
// business knowing about. It lives under apps/ for that reason, and `make test`
// does not build it -- tests/run_cli.sh and tests/sweep_cli.sh are what cover it.
#pragma once

#include <fcntl.h>
#include <unistd.h>

#include <cerrno>
#include <cstdint>
#include <cstring>
#include <random>
#include <stdexcept>
#include <string>

namespace cachesim {
namespace app {

// A usage error, which exits 2, as distinct from every run-time failure, which
// exits 1. Separated by TYPE rather than by an error code threaded through the
// call chain, so a new caller cannot forget which of the two it is.
struct UsageError : std::runtime_error {
    explicit UsageError(const std::string& what) : std::runtime_error(what) {}
};

inline std::string value_of(int argc, char** argv, int& i) {
    if (i + 1 >= argc) throw UsageError(std::string(argv[i]) + " needs a value");
    return argv[++i];
}

// A CLI integer, refused rather than silently taken as 0. `std::stoll` stops at
// the first character it cannot use, so `--line-trace-core x` would otherwise be
// core 0 and the trace would look filtered to a core the user never named.
inline std::int64_t int_value_of(int argc, char** argv, int& i) {
    const std::string flag = argv[i];
    const std::string text = value_of(argc, argv, i);
    std::size_t used = 0;
    long long v = 0;
    try {
        v = std::stoll(text, &used);
    } catch (const std::exception&) {
        throw UsageError(flag + " needs an integer, got \"" + text + "\"");
    }
    if (used != text.size()) throw UsageError(flag + " needs an integer, got \"" + text + "\"");
    return static_cast<std::int64_t>(v);
}

// Checked rather than passed through, because an unknown arm produces a row
// that joins to nothing and is only noticed in the analysis.
inline void check_arm(const std::string& arm) {
    if (arm != "cache" && arm != "spad_oracle" && arm != "spad_wcache" &&
        arm != "spad_nocsim") {
        throw UsageError("--arm " + arm +
                         " is not one of cache, spad_oracle, spad_wcache, spad_nocsim");
    }
}

// Version 4, variant 1, from std::random_device. The run id only has to be
// unique across a campaign's rows, so there is nothing here to seed or record.
inline std::string uuid4() {
    std::random_device rd;
    std::uniform_int_distribution<unsigned> nibble(0, 15);
    static const char* const hex = "0123456789abcdef";
    std::string s = "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx";
    for (char& c : s) {
        if (c == 'x') c = hex[nibble(rd)];
        else if (c == 'y') c = hex[8u + (nibble(rd) & 3u)];
    }
    return s;
}

// Owns the descriptor only when it opened one, so `-` and `fd:N` hand back a
// descriptor this class must not close.
class TraceFd {
public:
    explicit TraceFd(const std::string& spec) {
        if (spec == "-") {
            fd_ = STDIN_FILENO;
        } else if (spec.rfind("fd:", 0) == 0) {
            fd_ = std::stoi(spec.substr(3));
        } else {
            fd_ = ::open(spec.c_str(), O_RDONLY);
            if (fd_ < 0) {
                throw std::runtime_error("cannot open trace " + spec + ": " +
                                         std::strerror(errno));
            }
            owned_ = true;
        }
    }
    ~TraceFd() { if (owned_) ::close(fd_); }
    TraceFd(const TraceFd&)            = delete;
    TraceFd& operator=(const TraceFd&) = delete;

    int get() const { return fd_; }

private:
    int  fd_    = -1;
    bool owned_ = false;
};

}  // namespace app
}  // namespace cachesim
