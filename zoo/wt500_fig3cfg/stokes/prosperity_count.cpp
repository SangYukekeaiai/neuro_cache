#include <algorithm>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <fcntl.h>
#include <fstream>
#include <iostream>
#include <regex>
#include <string>
#include <sys/mman.h>
#include <sys/stat.h>
#include <unistd.h>
#include <vector>

struct MMap {
    int fd = -1;
    size_t size = 0;
    const uint8_t *data = nullptr;
    ~MMap() {
        if (data) munmap(const_cast<uint8_t *>(data), size);
        if (fd >= 0) close(fd);
    }
};

static bool next_int(const std::string &s, size_t &pos, int &value) {
    while (pos < s.size() && (s[pos] < '0' || s[pos] > '9')) ++pos;
    if (pos == s.size()) return false;
    value = 0;
    while (pos < s.size() && s[pos] >= '0' && s[pos] <= '9') {
        value = value * 10 + (s[pos] - '0');
        ++pos;
    }
    return true;
}

static MMap open_npy(const char *path, int &T, int &B, int &C, int &H, int &W) {
    MMap mm;
    mm.fd = open(path, O_RDONLY);
    if (mm.fd < 0) { perror(path); std::exit(2); }
    struct stat st{};
    if (fstat(mm.fd, &st) != 0) { perror("fstat"); std::exit(2); }
    mm.size = static_cast<size_t>(st.st_size);
    const size_t probe = std::min<size_t>(mm.size, 4096);
    std::vector<char> head(probe);
    if (pread(mm.fd, head.data(), probe, 0) != static_cast<ssize_t>(probe)) {
        perror("pread"); std::exit(2);
    }
    if (probe < 10 || std::memcmp(head.data(), "\x93NUMPY", 6) != 0) {
        std::cerr << "not an NPY file: " << path << "\n"; std::exit(2);
    }
    const int major = static_cast<unsigned char>(head[6]);
    size_t header_len_bytes = major >= 2 ? 4 : 2;
    size_t header_pos = 8;
    uint32_t header_len = 0;
    for (size_t i = 0; i < header_len_bytes; ++i)
        header_len |= static_cast<uint32_t>(static_cast<unsigned char>(head[header_pos + i])) << (8 * i);
    std::string header;
    header.resize(header_len);
    if (pread(mm.fd, header.data(), header_len, static_cast<off_t>(header_pos + header_len_bytes)) !=
        static_cast<ssize_t>(header_len)) {
        perror("header read"); std::exit(2);
    }
    size_t pos = header.find("'shape'");
    if (pos == std::string::npos) { std::cerr << "NPY shape missing\n"; std::exit(2); }
    std::vector<int> dims;
    pos = header.find('(', pos);
    while (pos < header.size() && dims.size() < 5) {
        int x;
        if (!next_int(header, pos, x)) break;
        dims.push_back(x);
        if (header.find(')', pos) < header.find(',', pos)) break;
    }
    if (dims.size() != 5) { std::cerr << "expected rank-5 NPY\n"; std::exit(2); }
    T = dims[0]; B = dims[1]; C = dims[2]; H = dims[3]; W = dims[4];
    const size_t offset = header_pos + header_len_bytes + header_len;
    const size_t expected = offset + static_cast<size_t>(T) * B * C * H * W;
    if (expected > mm.size) { std::cerr << "short NPY data\n"; std::exit(2); }
    void *mapped = mmap(nullptr, mm.size, PROT_READ, MAP_PRIVATE, mm.fd, 0);
    if (mapped == MAP_FAILED) { perror("mmap"); std::exit(2); }
    mm.data = static_cast<const uint8_t *>(mapped) + offset;
    return mm;
}

static inline uint8_t value(const uint8_t *x, int T, int B, int C, int H, int W,
                            int t, int b, int c, int h, int w) {
    const size_t idx = ((((static_cast<size_t>(t) * B + b) * C + c) * H + h) * W + w);
    return x[idx];
}

int main(int argc, char **argv) {
    if (argc != 9) {
        std::cerr << "usage: prosperity_count NPY KH KW HO_BOUND WO_BOUND CIN_BOUND T_BOUND COUT_BOUND\n";
        return 2;
    }
    const char *path = argv[1];
    const int kh = std::stoi(argv[2]), kw = std::stoi(argv[3]);
    const int ho_bound = std::stoi(argv[4]), wo_bound = std::stoi(argv[5]);
    const int cin_bound = std::stoi(argv[6]), t_bound = std::stoi(argv[7]);
    const int cout_bound = std::stoi(argv[8]);
    int T, B, C, H, W;
    MMap mm = open_npy(path, T, B, C, H, W);
    const int cout_blocks = (std::stoi(argv[8]) > 0) ? 1 : 0; // replaced below by caller's COUT slab count
    (void)cout_blocks;
    // The caller passes the realized COUT slab width as the final argument;
    // COUT itself is not present in the input trace, so it is encoded by the
    // number of slabs only in the Python-side multiplication.  This helper
    // emits the per-input-slab count; the caller multiplies it.
    const int pad_h = (kh - 1) / 2, pad_w = (kw - 1) / 2;
    std::vector<unsigned long long> totals(B, 0);
    const unsigned long long bit_limit = kh * kw >= 64 ? ~0ULL : (1ULL << (kh * kw)) - 1ULL;
    (void)bit_limit;
    #pragma omp parallel for schedule(static)
    for (int b = 0; b < B; ++b) {
        unsigned long long total = 0;
        if (kh == 1 && kw == 1) {
            // With one tap, the native prefix walk emits exactly one record
            // for a channel if any row in this realized tile fires.
            for (int h0 = 0; h0 < H; h0 += ho_bound) {
                const int hn = std::min(ho_bound, H - h0);
                for (int w0 = 0; w0 < W; w0 += wo_bound) {
                    const int wn = std::min(wo_bound, W - w0);
                    for (int c0 = 0; c0 < C; c0 += cin_bound) {
                        const int cn = std::min(cin_bound, C - c0);
                        for (int t0 = 0; t0 < T; t0 += t_bound) {
                            const int tn = std::min(t_bound, T - t0);
                            for (int c = c0; c < c0 + cn; ++c) {
                                bool active = false;
                                for (int h = h0; h < h0 + hn && !active; ++h)
                                    for (int w = w0; w < w0 + wn && !active; ++w)
                                        for (int t = t0; t < t0 + tn; ++t)
                                            if (value(mm.data, T, B, C, H, W, t, b, c, h, w)) {
                                                active = true;
                                                break;
                                            }
                                total += active ? 1ULL : 0ULL;
                            }
                        }
                    }
                }
            }
            totals[b] = total;
            continue;
        }
        for (int h0 = 0; h0 < H; h0 += ho_bound) {
            const int hn = std::min(ho_bound, H - h0);
            for (int w0 = 0; w0 < W; w0 += wo_bound) {
                const int wn = std::min(wo_bound, W - w0);
                for (int c0 = 0; c0 < C; c0 += cin_bound) {
                    const int cn = std::min(cin_bound, C - c0);
                    for (int t0 = 0; t0 < T; t0 += t_bound) {
                        const int tn = std::min(t_bound, T - t0);
                        const int m = hn * wn * tn;
                        for (int c = c0; c < c0 + cn; ++c) {
                            std::vector<uint64_t> bits(m, 0);
                            for (int hl = 0; hl < hn; ++hl) {
                                const int ho = h0 + hl;
                                for (int wl = 0; wl < wn; ++wl) {
                                    const int wo = w0 + wl;
                                    for (int tl = 0; tl < tn; ++tl) {
                                        const int t = t0 + tl;
                                        const int row = (hl * wn + wl) * tn + tl;
                                        uint64_t mask = 0;
                                        for (int kh_i = 0; kh_i < kh; ++kh_i) {
                                            const int hi = ho + kh_i - pad_h;
                                            if (hi < 0 || hi >= H) continue;
                                            for (int kw_i = 0; kw_i < kw; ++kw_i) {
                                                const int wi = wo + kw_i - pad_w;
                                                if (wi >= 0 && wi < W && value(mm.data, T, B, C, H, W, t, b, c, hi, wi))
                                                    mask |= 1ULL << (kh_i * kw + kw_i);
                                            }
                                        }
                                        bits[row] = mask;
                                    }
                                }
                            }
                            std::vector<int> order(m);
                            for (int i = 0; i < m; ++i) order[i] = i;
                            std::stable_sort(order.begin(), order.end(), [&](int a, int z) {
                                return __builtin_popcountll(bits[a]) < __builtin_popcountll(bits[z]);
                            });
                            std::vector<uint64_t> processed(m, 0);
                            for (int step = 0; step < m; ++step) {
                                const uint64_t cur = bits[order[step]];
                                uint64_t pattern = cur;
                                for (int prev = step - 1; prev >= 0; --prev) {
                                    if ((processed[prev] & ~cur) == 0) {
                                        pattern = cur ^ processed[prev];
                                        break;
                                    }
                                }
                                total += __builtin_popcountll(pattern);
                                processed[step] = cur;
                            }
                        }
                    }
                }
            }
        }
        totals[b] = total;
    }
    for (int b = 0; b < B; ++b) std::cout << totals[b] << '\n';
    return 0;
}
