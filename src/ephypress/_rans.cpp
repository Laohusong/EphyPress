// SPDX-License-Identifier: AGPL-3.0-only
// Unconditional four-lane byte rANS, with block-local unconditional frequencies.
#include <algorithm>
#include <array>
#include <cstdint>
#include <cstring>
#include <limits>
#include <new>
#include <vector>

#if defined(_WIN32)
#define API extern "C" __declspec(dllexport)
#else
#define API extern "C" __attribute__((visibility("default")))
#endif

namespace {
using I = std::int16_t;
constexpr unsigned SCALE = 14, TOTAL = 1 << SCALE, LOW = 1 << 23, ESC = 1024, NSYM = 1025;
constexpr unsigned HEADER = 8 + NSYM * 2 + 16;
struct Entry { std::uint16_t symbol, freq, start; };
struct Context {
    std::vector<I> residual;
    std::vector<std::uint16_t> previous;
    std::array<Entry, TOTAL> table;
};
bool valid(std::uint64_t rows, std::uint32_t channels) {
    return rows && channels && rows <= (std::numeric_limits<std::size_t>::max() / 2) / channels;
}
I wrap(unsigned value) {
    auto bits = static_cast<std::uint16_t>(value);
    I result;
    std::memcpy(&result, &bits, 2);
    return result;
}
unsigned fold(I value) { return value < 0 ? unsigned(-int(value) * 2 - 1) : unsigned(value) * 2; }
unsigned get16(const std::uint8_t*& p) {
    unsigned value = p[0] | unsigned(p[1]) << 8;
    p += 2;
    return value;
}
std::uint32_t get32(const std::uint8_t*& p) {
    std::uint32_t value = 0;
    for (unsigned k = 0; k < 4; ++k) value |= std::uint32_t(*p++) << (k * 8);
    return value;
}
void put16(std::vector<std::uint8_t>& out, unsigned value) {
    out.push_back(std::uint8_t(value)); out.push_back(std::uint8_t(value >> 8));
}
void put32(std::vector<std::uint8_t>& out, std::uint32_t value) {
    for (unsigned k = 0; k < 4; ++k) out.push_back(std::uint8_t(value >> (k * 8)));
}
int decode(Context& ctx, const std::uint8_t* src, std::uint64_t length,
           std::uint64_t rows, std::uint32_t channels, I* output) {
    if (!src || !output || !valid(rows, channels) || length < HEADER ||
        length > std::numeric_limits<std::size_t>::max()) return -1;
    const auto* p = src;
    if (get32(p) != 1) return -1;
    unsigned escapes = get32(p);
    if (escapes % 2 || escapes > length - HEADER) return -1;
    unsigned start = 0;
    for (unsigned s = 0; s < NSYM; ++s) {
        unsigned f = get16(p);
        if (start + f > TOTAL) return -1;
        for (unsigned j = start; j < start + f; ++j)
            ctx.table[j] = {std::uint16_t(s), std::uint16_t(f), std::uint16_t(start)};
        start += f;
    }
    if (start != TOTAL) return -1;
    std::uint32_t state[4];
    for (auto& s : state) { s = get32(p); if (s < LOW || s >= (LOW << 8)) return -1; }
    const auto* end = src + length - escapes;
    const auto* escape = end;
    ctx.residual.resize(rows * channels);
    auto one = [&](unsigned lane, I& result) -> bool {
        auto v = state[lane];
        auto e = ctx.table[v & (TOTAL - 1)];
        v = e.freq * (v >> SCALE) + (v & (TOTAL - 1)) - e.start;
        while (v < LOW) { if (p >= end) return false; v = (v << 8) | *p++; }
        state[lane] = v;
        if (e.symbol == ESC) {
            if (std::uint64_t(src + length - escape) < 2) return false;
            result = wrap(get16(escape));
        } else result = I(int(e.symbol >> 1) ^ -int(e.symbol & 1));
        return true;
    };
    std::uint64_t i = 0, count = rows * channels;
    for (; i + 4 <= count; i += 4) {
        I a, b, c, d;
        if (!one(unsigned(i & 3), a) || !one(unsigned((i + 1) & 3), b) ||
            !one(unsigned((i + 2) & 3), c) || !one(unsigned((i + 3) & 3), d)) return -1;
        ctx.residual[i] = a; ctx.residual[i + 1] = b;
        ctx.residual[i + 2] = c; ctx.residual[i + 3] = d;
    }
    for (; i < count; ++i) if (!one(unsigned(i & 3), ctx.residual[i])) return -1;
    if (p != end || escape != src + length) return -1;
    for (auto s : state) if (s != LOW) return -1;
    // Fuse modular inverse delta and channel-major -> time-major tile conversion.
    ctx.previous.assign(channels, 0);
    for (std::uint64_t t = 0; t < rows; t += 64)
        for (std::uint32_t c = 0; c < channels; c += 32)
            for (auto r = t; r < std::min(rows, t + 64); ++r)
                for (auto k = c; k < std::min(channels, c + 32); ++k) {
                    ctx.previous[k] = std::uint16_t(ctx.previous[k] + unsigned(ctx.residual[k * rows + r]));
                    output[r * channels + k] = wrap(ctx.previous[k]);
                }
    return 0;
}
} // namespace

API void* ephypress_rans_create() { try { return new Context; } catch (...) { return nullptr; } }
API void ephypress_rans_destroy(void* context) { delete static_cast<Context*>(context); }
API int ephypress_rans_decode(void* context, const std::uint8_t* src, std::uint64_t length,
                              std::uint64_t rows, std::uint32_t channels, I* output) {
    if (!context) return -1;
    try { return decode(*static_cast<Context*>(context), src, length, rows, channels, output); }
    catch (const std::bad_alloc&) { return -2; } catch (...) { return -1; }
}

// Input is the channel-major int16 delta residual buffer, in native endianness.
API std::int64_t ephypress_rans_encode(const I* values, std::uint64_t count,
                                      std::uint8_t* dst, std::uint64_t capacity) {
    if (!values || !count || !dst || count > std::numeric_limits<std::size_t>::max() / 4) return -1;
    try {
        std::array<std::uint64_t, NSYM> hist{};
        std::array<std::uint16_t, NSYM> freq{}, starts{};
        std::vector<std::uint8_t> escapes;
        for (std::uint64_t i = 0; i < count; ++i) {
            auto s = std::min(fold(values[i]), ESC);
            ++hist[s];
            if (s == ESC) put16(escapes, std::uint16_t(values[i]));
        }
        if (escapes.size() > std::numeric_limits<std::uint32_t>::max()) return -1;
        unsigned used = 0, peak = 0;
        for (unsigned s = 0; s < NSYM; ++s) {
            if (hist[s] > hist[peak]) peak = s;
            freq[s] = hist[s] ? std::uint16_t(std::max(std::uint64_t(1), hist[s] * TOTAL / count)) : 0;
            used += freq[s];
        }
        if (used <= TOTAL) freq[peak] += std::uint16_t(TOTAL - used);
        else {
            std::array<unsigned, NSYM> order;
            for (unsigned s = 0; s < NSYM; ++s) order[s] = s;
            std::sort(order.begin(), order.end(), [&](unsigned a, unsigned b) { return hist[a] > hist[b]; });
            for (auto s : order) {
                auto take = std::min(used - TOTAL, unsigned(freq[s] ? freq[s] - 1 : 0));
                freq[s] -= std::uint16_t(take); used -= take;
                if (used == TOTAL) break;
            }
        }
        std::vector<std::uint8_t> header;
        put32(header, 1); put32(header, std::uint32_t(escapes.size()));
        unsigned cumulative = 0;
        for (unsigned s = 0; s < NSYM; ++s) {
            starts[s] = std::uint16_t(cumulative); cumulative += freq[s]; put16(header, freq[s]);
        }
        if (cumulative != TOTAL) return -1;
        std::vector<std::uint8_t> bytes;
        bytes.reserve(count * 2);
        std::uint32_t state[4] = {LOW, LOW, LOW, LOW};
        for (auto i = count; i-- > 0;) {
            auto s = std::min(fold(values[i]), ESC);
            std::uint32_t f = freq[s], v = state[i & 3], maximum = ((LOW >> SCALE) << 8) * f;
            while (v >= maximum) { bytes.push_back(std::uint8_t(v)); v >>= 8; }
            state[i & 3] = ((v / f) << SCALE) + v % f + starts[s];
        }
        for (auto s : state) put32(header, s);
        auto total = header.size() + bytes.size() + escapes.size();
        if (total > capacity) return -1;
        auto* out = dst;
        std::memcpy(out, header.data(), header.size()); out += header.size();
        for (auto i = bytes.rbegin(); i != bytes.rend(); ++i) *out++ = *i;
        if (!escapes.empty()) std::memcpy(out, escapes.data(), escapes.size());
        return std::int64_t(total);
    } catch (const std::bad_alloc&) { return -2; } catch (...) { return -1; }
}
