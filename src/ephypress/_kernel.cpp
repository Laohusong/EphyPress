// SPDX-License-Identifier: MIT
// Reversible temporal difference and channel-major residual layout.
#include <algorithm>
#include <cstdint>
#include <cstring>
#include <limits>
#include <new>
#include <vector>

#if defined(_WIN32)
#define EPHYPRESS_EXPORT extern "C" __declspec(dllexport)
#else
#define EPHYPRESS_EXPORT extern "C" __attribute__((visibility("default")))
#endif

namespace {
bool valid_shape(std::uint64_t rows, std::uint32_t channels) {
    const auto maximum = static_cast<std::uint64_t>(std::numeric_limits<std::int64_t>::max() - 7);
    return rows && channels && rows <= maximum / channels &&
           rows * channels <= (std::numeric_limits<std::size_t>::max() / 2) - 7;
}
std::int16_t wrap_sample(int value) {
    const auto bits = static_cast<std::uint16_t>(value);
    std::int16_t result;
    std::memcpy(&result, &bits, sizeof(result));
    return result;
}
void predict(const std::int16_t* input, std::int16_t* residual,
             std::int64_t rows, std::uint32_t channels) {
    for (std::int64_t row = 0; row < rows; ++row) {
        const auto base = static_cast<std::uint64_t>(row) * channels;
        for (std::uint32_t channel = 0; channel < channels; ++channel) {
            const int previous = row ? int(input[base + channel - channels]) : 0;
            residual[base + channel] = wrap_sample(int(input[base + channel]) - previous);
        }
    }
}
} // namespace

// Transpose in bounded tiles, with an explicit little-endian wire representation.
// The compressor sees each channel's complete int16 residuals, without bit splitting.
EPHYPRESS_EXPORT int ephypress_encode_delta_channels16(const std::int16_t *input, std::uint64_t rows, std::uint32_t channels,
                      std::uint8_t *output) noexcept {
    if (!valid_shape(rows, channels) || !input || !output) return -1;
    try {
        std::vector<std::int16_t> residual(static_cast<std::size_t>(rows * channels));
        predict(input, residual.data(), static_cast<std::int64_t>(rows), channels);
        const auto row_limit = static_cast<std::int64_t>(rows);
        const auto channel_limit = static_cast<std::int64_t>(channels);
        for (std::int64_t first_row = 0; first_row < row_limit; first_row += 64) {
            for (std::int64_t first_channel = 0; first_channel < channel_limit; first_channel += 32) {
                for (auto channel = first_channel; channel < std::min(channel_limit, first_channel + 32); ++channel) {
                    for (auto row = first_row; row < std::min(row_limit, first_row + 64); ++row) {
                        const auto value = static_cast<std::uint16_t>(residual[row * channels + channel]);
                        const auto position = 2 * (channel * rows + row);
                        output[position] = static_cast<std::uint8_t>(value);
                        output[position + 1] = static_cast<std::uint8_t>(value >> 8);
                    }
                }
            }
        }
        return 0;
    } catch (const std::bad_alloc &) { return -2; }
}
