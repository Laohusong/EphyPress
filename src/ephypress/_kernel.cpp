// SPDX-License-Identifier: MIT
// Named, reversible integer prediction and fixed-width residual planes.
#include "_prediction.h"
#include "fse.h"
#include <algorithm>
#include <cstddef>
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
#define EPHYPRESS_STRINGIFY_IMPL(value) #value
#define EPHYPRESS_STRINGIFY(value) EPHYPRESS_STRINGIFY_IMPL(value)
#if defined(_OPENMP)
#if defined(_MSC_VER)
#define EPHYPRESS_PARALLEL_FOR(condition) __pragma(omp parallel for num_threads(2) if(condition))
#else
#define EPHYPRESS_PARALLEL_FOR(condition) _Pragma(EPHYPRESS_STRINGIFY(omp parallel for num_threads(2) if(condition)))
#endif
#else
#define EPHYPRESS_PARALLEL_FOR(condition)
#endif

namespace {
using namespace ephypress;

bool valid_shape(std::uint64_t rows, std::uint32_t channels) {
    const auto maximum = static_cast<std::uint64_t>(std::numeric_limits<std::int64_t>::max() - 7);
    return rows && channels && rows <= maximum / channels &&
           rows * channels <= (std::numeric_limits<std::size_t>::max() / 2) - 7;
}
std::int16_t wrap_sample(int value) {
    const auto unsigned_value = static_cast<std::uint16_t>(value);
    std::int16_t result;
    std::memcpy(&result, &unsigned_value, sizeof(result));
    return result;
}
int floor_divide(int value, int denominator) {
    return value / denominator - (value < 0 && value % denominator != 0);
}
int temporal_prediction(std::int16_t previous) {
    return floor_divide(int(previous) * kTemporalNumerator, kTemporalDenominator);
}

template<bool UseSpatialPrediction>
void predict(const std::int16_t *input, std::int16_t *residual,
             std::int64_t rows, std::uint32_t channels) {
    EPHYPRESS_PARALLEL_FOR(rows * channels >= 262144)
    for (std::int64_t row = 0; row < rows; ++row) {
        const auto base = static_cast<std::uint64_t>(row) * channels;
        for (std::uint32_t channel = 0; channel < channels; ++channel) {
            const int previous = row ? temporal_prediction(input[base + channel - channels]) : 0;
            residual[base + channel] = wrap_sample(int(input[base + channel]) - previous);
        }
        if constexpr (UseSpatialPrediction) {
            for (std::int64_t channel = static_cast<std::int64_t>(channels) - 1; channel >= 0; --channel) {
                int sum = 0;
                for (int lag = 0; lag < kSpatialOrder; ++lag)
                    if (lag < channel) sum += kSpatialWeights[lag] * int(residual[base + channel - lag - 1]);
                residual[base + channel] = wrap_sample(int(residual[base + channel]) - floor_divide(sum, kSpatialDenominator));
            }
        }
    }
}
template<bool UseSpatialPrediction>
void restore_prediction(std::int16_t *output, std::int64_t rows, std::uint32_t channels) {
    if constexpr (UseSpatialPrediction) {
        EPHYPRESS_PARALLEL_FOR(rows * channels >= 262144)
        for (std::int64_t row = 0; row < rows; ++row) {
            int previous[kSpatialOrder] = {};
            const auto base = static_cast<std::uint64_t>(row) * channels;
            for (std::uint32_t channel = 0; channel < channels; ++channel) {
                int sum = 0;
                for (int lag = 0; lag < kSpatialOrder; ++lag) sum += kSpatialWeights[lag] * previous[lag];
                const int value = wrap_sample(int(output[base + channel]) + floor_divide(sum, kSpatialDenominator));
                output[base + channel] = static_cast<std::int16_t>(value);
                for (int lag = kSpatialOrder - 1; lag > 0; --lag) previous[lag] = previous[lag - 1];
                previous[0] = value;
            }
        }
    }
    for (std::int64_t row = 1; row < rows; ++row) {
        const auto base = static_cast<std::uint64_t>(row) * channels;
        for (std::uint32_t channel = 0; channel < channels; ++channel)
            output[base + channel] = wrap_sample(int(output[base + channel]) + temporal_prediction(output[base + channel - channels]));
    }
}
void pack_residual(const std::int16_t *residual, std::int64_t count,
                   std::uint8_t *low, std::uint8_t *high) {
    const std::int64_t padded = ((count + 7) / 8) * 8;
    EPHYPRESS_PARALLEL_FOR(count >= 262144)
    for (std::int64_t index = 0; index < padded; index += 8) {
        std::uint32_t word = 0;
        for (int position = 0; position < 8; ++position) {
            const int value = index + position < count ? residual[index + position] : 0;
            const auto zigzag = static_cast<std::uint16_t>(value >= 0 ? 2 * value : -2 * value - 1);
            word |= std::uint32_t(zigzag & 15) << (position * kResidualLowBits);
            high[index + position] = static_cast<std::uint8_t>(zigzag >> kResidualLowBits);
            high[padded + index + position] = static_cast<std::uint8_t>(zigzag >> (kResidualLowBits + 8));
        }
        for (int byte = 0; byte < kResidualLowBits; ++byte)
            low[(index / 8) * kResidualLowBits + byte] = static_cast<std::uint8_t>(word >> (8 * byte));
    }
}
void unpack_residual(const std::uint8_t *low, const std::uint8_t *high,
                     std::int64_t count, std::int16_t *output) {
    const std::int64_t padded = ((count + 7) / 8) * 8;
    EPHYPRESS_PARALLEL_FOR(count >= 262144)
    for (std::int64_t index = 0; index < padded; index += 8) {
        std::uint32_t word = 0;
        for (int byte = 0; byte < kResidualLowBits; ++byte)
            word |= std::uint32_t(low[(index / 8) * kResidualLowBits + byte]) << (8 * byte);
        for (int position = 0; position < 8 && index + position < count; ++position) {
            const auto upper = std::uint16_t(high[index + position]) |
                               std::uint16_t(std::uint16_t(high[padded + index + position]) << 8);
            const auto zigzag = std::uint16_t(std::uint16_t(upper << kResidualLowBits) |
                               std::uint16_t((word >> (position * kResidualLowBits)) & 15));
            output[index + position] = static_cast<std::int16_t>((zigzag >> 1) ^ -int(zigzag & 1));
        }
    }
}
template<bool UseSpatialPrediction>
int encode(const std::int16_t *input, std::uint64_t rows, std::uint32_t channels,
           std::uint8_t *low, std::uint8_t *high) noexcept {
    if (!valid_shape(rows, channels) || !input || !low || !high) return -1;
    try {
        const auto count = static_cast<std::int64_t>(rows * channels);
        std::vector<std::int16_t> residual(static_cast<std::size_t>(count));
        predict<UseSpatialPrediction>(input, residual.data(), static_cast<std::int64_t>(rows), channels);
        pack_residual(residual.data(), count, low, high);
        return 0;
    } catch (const std::bad_alloc &) { return -2; }
}
template<bool UseSpatialPrediction>
int decode(const std::uint8_t *low, const std::uint8_t *high, std::uint64_t rows,
           std::uint32_t channels, std::int16_t *output) noexcept {
    if (!valid_shape(rows, channels) || !low || !high || !output) return -1;
    unpack_residual(low, high, static_cast<std::int64_t>(rows * channels), output);
    restore_prediction<UseSpatialPrediction>(output, static_cast<std::int64_t>(rows), channels);
    return 0;
}
}

EPHYPRESS_EXPORT int ephypress_encode_temporal(const std::int16_t *input, std::uint64_t rows,
    std::uint32_t channels, std::uint8_t *low, std::uint8_t *high) {
    return encode<false>(input, rows, channels, low, high);
}
EPHYPRESS_EXPORT int ephypress_encode_spatiotemporal(const std::int16_t *input, std::uint64_t rows,
    std::uint32_t channels, std::uint8_t *low, std::uint8_t *high) {
    return encode<true>(input, rows, channels, low, high);
}
EPHYPRESS_EXPORT int ephypress_decode_temporal(const std::uint8_t *low, const std::uint8_t *high,
    std::uint64_t rows, std::uint32_t channels, std::int16_t *output) {
    return decode<false>(low, high, rows, channels, output);
}
EPHYPRESS_EXPORT int ephypress_decode_spatiotemporal(const std::uint8_t *low, const std::uint8_t *high,
    std::uint64_t rows, std::uint32_t channels, std::int16_t *output) {
    return decode<true>(low, high, rows, channels, output);
}
EPHYPRESS_EXPORT int ephypress_decode_channels(const std::uint8_t *source, std::uint64_t bytes,
    std::uint64_t rows, std::uint32_t channels, std::uint8_t *output) {
    if (!valid_shape(rows, channels) || !source || !output) return -1;
    try {
        std::vector<std::uint64_t> offsets(channels), lengths(channels);
        std::uint64_t position = 0;
        for (std::uint32_t channel = 0; channel < channels; ++channel) {
            if (position > bytes || bytes - position < 4) return -1;
            const std::uint32_t length = std::uint32_t(source[position]) |
                (std::uint32_t(source[position + 1]) << 8) | (std::uint32_t(source[position + 2]) << 16) |
                (std::uint32_t(source[position + 3]) << 24);
            position += 4;
            if (!length || length > bytes - position) return -1;
            offsets[channel] = position; lengths[channel] = length; position += length;
        }
        if (position != bytes) return -1;
        std::vector<std::uint8_t> planes(static_cast<std::size_t>(rows * channels));
        std::vector<int> errors(channels, 0);
        const auto channel_limit = static_cast<std::int64_t>(channels);
        EPHYPRESS_PARALLEL_FOR(rows * channels >= 262144)
        for (std::int64_t channel = 0; channel < channel_limit; ++channel) {
            const auto length = lengths[channel];
            const auto *packet = source + offsets[channel];
            auto *destination = planes.data() + channel * rows;
            if (packet[0] == 0 && length == rows + 1) std::memcpy(destination, packet + 1, rows);
            else if (packet[0] == 2 && length == 2) std::memset(destination, packet[1], rows);
            else if (packet[0] == 1 && length >= 3) {
                if (FSE_decompress(destination, rows, packet + 1, length - 1) != rows) errors[channel] = 1;
            } else errors[channel] = 1;
        }
        for (const int error : errors) if (error) return -1;
        const auto row_limit = static_cast<std::int64_t>(rows);
        EPHYPRESS_PARALLEL_FOR(rows * channels >= 262144)
        for (std::int64_t first_row = 0; first_row < row_limit; first_row += 64) {
            for (std::int64_t first_channel = 0; first_channel < channel_limit; first_channel += 32) {
                for (auto row = first_row; row < std::min(row_limit, first_row + 64); ++row)
                    for (auto channel = first_channel; channel < std::min(channel_limit, first_channel + 32); ++channel)
                        output[row * channels + channel] = planes[channel * rows + row];
            }
        }
        return 0;
    } catch (const std::bad_alloc &) { return -2; }
}
