// Where the bytes of a WCTS stream come from, separated from what they mean.
//
// Plan D Task 1. A stream arrives on a pipe in the campaign and from a buffer
// in every test, and `StreamingTileTrace` must not know which: a reader that
// took a file descriptor could only be tested against a real file, and a
// reader that took a buffer could not read a pipe at all.
//
// The contract that matters is the difference between "the stream is over" and
// "the stream stopped in the middle of a record". A pipe that closes between
// two tile frames is a clean end and is how every run finishes; a pipe that
// closes halfway through a burst record is a producer that died, and reporting
// that as an end of stream would turn a crashed generator into a short but
// plausible simulation. So `read_exact` returns false only when zero bytes were
// available, and throws otherwise.
#pragma once

#include <unistd.h>

#include <cerrno>
#include <cstddef>
#include <cstring>
#include <stdexcept>
#include <string>
#include <vector>

namespace wcache {

class ByteSource {
public:
    virtual ~ByteSource() = default;

    // Fills exactly `n` bytes. Returns false ONLY on a clean end of stream,
    // that is when zero bytes were available. A partial read is a truncated
    // stream and throws std::runtime_error naming how many bytes were wanted
    // and how many arrived.
    virtual bool read_exact(void* dst, std::size_t n) = 0;

protected:
    // Protected and defaulted, for the reason decision B67 settled at
    // `CacheArray` and B92 reused at `ReplacementPolicy`: through two base
    // references `a = b` would compile and assign the base subobject only.
    ByteSource()                             = default;
    ByteSource(const ByteSource&)            = default;
    ByteSource(ByteSource&&)                 = default;
    ByteSource& operator=(const ByteSource&) = default;
    ByteSource& operator=(ByteSource&&)      = default;
};

// Reads from an already-open POSIX descriptor, retrying short reads and EINTR.
// Does NOT own the descriptor.
class FdByteSource final : public ByteSource {
public:
    explicit FdByteSource(int fd) : fd_(fd) {}

    bool read_exact(void* dst, std::size_t n) override {
        unsigned char* out = static_cast<unsigned char*>(dst);
        std::size_t got = 0;
        while (got < n) {
            const ssize_t r = ::read(fd_, out + got, n - got);
            if (r < 0) {
                if (errno == EINTR) continue;
                throw std::runtime_error("FdByteSource: read failed on fd " +
                                         std::to_string(fd_) + ": " + std::strerror(errno));
            }
            if (r == 0) {
                if (got == 0) return false;
                throw std::runtime_error("FdByteSource: truncated stream, wanted " +
                                         std::to_string(n) + " bytes and got " +
                                         std::to_string(got));
            }
            got += static_cast<std::size_t>(r);
        }
        return true;
    }

private:
    int fd_;
};

// Reads from a buffer in memory. This is what every test uses.
class MemByteSource final : public ByteSource {
public:
    MemByteSource(const unsigned char* data, std::size_t len) : data_(data), len_(len) {}
    explicit MemByteSource(const std::vector<unsigned char>& v)
        : data_(v.data()), len_(v.size()) {}

    bool read_exact(void* dst, std::size_t n) override {
        const std::size_t avail = len_ - pos_;
        if (n > avail) {
            if (avail == 0) return false;
            throw std::runtime_error("MemByteSource: truncated stream, wanted " +
                                     std::to_string(n) + " bytes and got " +
                                     std::to_string(avail));
        }
        std::memcpy(dst, data_ + pos_, n);
        pos_ += n;
        return true;
    }

    std::size_t consumed() const { return pos_; }

private:
    const unsigned char* data_;
    std::size_t          len_;
    std::size_t          pos_ = 0;
};

}  // namespace wcache
