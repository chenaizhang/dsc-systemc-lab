#include "vesa_reference_codec.hpp"

extern "C" {
#include "dsc_codec.h"
#include "dsc_utils.h"
#include "utl.h"
}

#include <algorithm>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <cstring>
#include <limits>
#include <memory>
#include <sstream>
#include <vector>

namespace dsc_function_tlm {
namespace {

struct PictureDeleter {
    void operator()(pic_t* picture) const
    {
        if (picture != nullptr)
            pdestroy(picture);
    }
};

using PicturePtr = std::unique_ptr<pic_t, PictureDeleter>;

CodecResult fail(CodecStatus status, const std::string& diagnostic)
{
    CodecResult result;
    result.status = status;
    result.diagnostic = diagnostic;
    return result;
}

bool has_valid_pps_header(const std::array<std::uint8_t, 128>& pps)
{
    return (pps[0] >> 4U) == 1U && (pps[0] & 0x0fU) >= 1U;
}

std::size_t request_pixel_count(const FrameRequest& request)
{
    std::size_t count = 0;
    for (const auto& beat : request.beats)
        count += beat.valid_pixels;
    return count;
}

bool framing_is_consistent(const FrameRequest& request, int width, int height)
{
    if (request.beats.empty() || !request.beats.front().start_of_frame
        || !request.beats.back().end_of_frame)
        return false;

    std::size_t pixel_index = 0;
    for (std::size_t beat_index = 0; beat_index < request.beats.size(); ++beat_index) {
        const auto& beat = request.beats[beat_index];
        if (beat.valid_pixels != 1 && beat.valid_pixels != 2 && beat.valid_pixels != 4)
            return false;
        if (beat_index != 0 && beat.start_of_frame)
            return false;
        if (beat_index + 1 != request.beats.size() && beat.end_of_frame)
            return false;
        const bool expected_sol = (pixel_index % static_cast<std::size_t>(width)) == 0;
        const auto next_pixel = pixel_index + beat.valid_pixels;
        const bool expected_eol = (next_pixel % static_cast<std::size_t>(width)) == 0;
        if (beat.start_of_line != expected_sol || beat.end_of_line != expected_eol)
            return false;
        pixel_index = next_pixel;
    }
    return pixel_index == static_cast<std::size_t>(width) * static_cast<std::size_t>(height);
}

int sample_from_bus(std::uint16_t value, int bits_per_component)
{
    return static_cast<int>(value >> (16 - bits_per_component));
}

} // namespace

CodecResult VesaReferenceCodec::encode(const FrameRequest& request)
{
    if (!has_valid_pps_header(request.pps))
        return fail(CodecStatus::InvalidPps, "PPS does not identify DSC major version 1");

    dsc_cfg_t config{};
    auto pps = request.pps;
    parse_pps(pps.data(), &config);

    if (config.pic_width <= 0 || config.pic_height <= 0 || config.slice_width <= 0
        || config.slice_height <= 0 || config.chunk_size <= 0)
        return fail(CodecStatus::InvalidPps, "PPS contains a zero image, slice, or chunk dimension");
    if (config.bits_per_component < 8 || config.bits_per_component > 16
        || (config.bits_per_component & 1) != 0)
        return fail(CodecStatus::InvalidPps, "PPS bits_per_component must be 8, 10, 12, 14, or 16");
    if (config.simple_422 || config.native_422 || config.native_420 || !config.convert_rgb)
        return fail(CodecStatus::InvalidPps,
            "the current AXI pixel adapter is qualified for RGB 4:4:4 PPS data only");
    if (request.pixels_per_cycle != 1 && request.pixels_per_cycle != 2
        && request.pixels_per_cycle != 4)
        return fail(CodecStatus::InvalidFrame, "pixels_per_cycle must be 1, 2, or 4");

    const auto expected_pixels = static_cast<std::size_t>(config.pic_width)
        * static_cast<std::size_t>(config.pic_height);
    if (request_pixel_count(request) != expected_pixels
        || !framing_is_consistent(request, config.pic_width, config.pic_height))
        return fail(CodecStatus::InvalidFrame,
            "pixel count or SOF/EOF/SOL/EOL framing does not match the PPS dimensions");

    // These parameters are C-model-only state and are intentionally not
    // carried in the 128-byte PPS.  They match the VESA CLI decoder path.
    config.very_flat_qp = 1 + 2 * (config.bits_per_component - 8);
    config.somewhat_flat_qp_delta = 4;
    config.somewhat_flat_qp_thresh = 7 + 2 * (config.bits_per_component - 8);
    config.rcb_bits = static_cast<int>(std::ceil(
        (config.initial_xmit_delay + config.initial_dec_delay)
        * (config.bits_per_pixel / 16.0)));
    config.mux_word_size = config.bits_per_component >= 12 ? 64 : 48;
    config.full_ich_err_precision = 0;

    PicturePtr input(pcreate_ext(FRAME, RGB, YUV_444, config.pic_width, config.pic_height,
        config.bits_per_component));
    PicturePtr reconstructed(pcreate_ext(FRAME, RGB, YUV_444, config.pic_width,
        config.pic_height, config.bits_per_component));
    if (!input || !reconstructed)
        return fail(CodecStatus::EncodeFailed, "VESA picture allocation failed");
    input->alpha = 0;
    reconstructed->alpha = 0;

    std::size_t pixel_index = 0;
    for (const auto& beat : request.beats) {
        for (std::size_t pixel = 0; pixel < beat.valid_pixels; ++pixel, ++pixel_index) {
            const auto y = static_cast<int>(pixel_index / static_cast<std::size_t>(config.pic_width));
            const auto x = static_cast<int>(pixel_index % static_cast<std::size_t>(config.pic_width));
            const auto component = pixel * 3;
            // AXI bits [15:0], [31:16], [47:32] are B, G, R.  Samples are
            // left-aligned in each 16-bit lane as required by the core guide.
            input->data.rgb.b[y][x] = sample_from_bus(
                beat.components[component], config.bits_per_component);
            input->data.rgb.g[y][x] = sample_from_bus(
                beat.components[component + 1], config.bits_per_component);
            input->data.rgb.r[y][x] = sample_from_bus(
                beat.components[component + 2], config.bits_per_component);
        }
    }

    std::array<PicturePtr, 2> temporary{
        PicturePtr(pcreate_ext(FRAME, YUV_HD, YUV_444, config.pic_width, config.pic_height,
            config.bits_per_component)),
        PicturePtr(pcreate_ext(FRAME, YUV_HD, YUV_444, config.pic_width, config.pic_height,
            config.bits_per_component))};
    if (!temporary[0] || !temporary[1])
        return fail(CodecStatus::EncodeFailed, "VESA color-conversion allocation failed");
    pic_t* temporary_raw[2]{temporary[0].get(), temporary[1].get()};

    const auto slices_per_line = (config.pic_width + config.slice_width - 1) / config.slice_width;
    const auto slice_rows = (config.pic_height + config.slice_height - 1) / config.slice_height;
    if (slices_per_line <= 0 || slice_rows <= 0)
        return fail(CodecStatus::InvalidPps, "invalid slice grid");
    const auto buffer_size = static_cast<std::size_t>(config.chunk_size)
        * static_cast<std::size_t>(config.slice_height);
    if (buffer_size > static_cast<std::size_t>(std::numeric_limits<int>::max()))
        return fail(CodecStatus::InvalidPps, "slice buffer is too large");

    std::vector<std::vector<unsigned char>> buffers(
        static_cast<std::size_t>(slices_per_line), std::vector<unsigned char>(buffer_size));
    std::vector<std::vector<int>> chunk_sizes(
        static_cast<std::size_t>(slices_per_line),
        std::vector<int>(static_cast<std::size_t>(config.slice_height)));

    CodecResult result;
    result.status = CodecStatus::Ok;
    result.bitstream.reserve(
        buffer_size * static_cast<std::size_t>(slices_per_line * slice_rows));
    for (int slice_row = 0; slice_row < slice_rows; ++slice_row) {
        const auto y_start = slice_row * config.slice_height;
        for (int slice_x = 0; slice_x < slices_per_line; ++slice_x) {
            std::fill(buffers[static_cast<std::size_t>(slice_x)].begin(),
                buffers[static_cast<std::size_t>(slice_x)].end(), 0);
            config.xstart = slice_x * config.slice_width;
            config.ystart = y_start;
            const auto encoded_bits = DSC_Encode(&config, input.get(), reconstructed.get(),
                buffers[static_cast<std::size_t>(slice_x)].data(), temporary_raw,
                chunk_sizes[static_cast<std::size_t>(slice_x)].data());
            if (encoded_bits <= 0)
                return fail(CodecStatus::EncodeFailed, "VESA DSC_Encode returned no data");
        }

        std::vector<std::size_t> offsets(static_cast<std::size_t>(slices_per_line));
        for (int line = 0; line < config.slice_height; ++line) {
            for (int slice_x = 0; slice_x < slices_per_line; ++slice_x) {
                const auto index = static_cast<std::size_t>(slice_x);
                auto byte_count = static_cast<std::size_t>(config.chunk_size);
                if (config.vbr_enable) {
                    const auto signed_count = chunk_sizes[index][static_cast<std::size_t>(line)];
                    if (signed_count < 0)
                        return fail(CodecStatus::EncodeFailed, "VESA returned a negative VBR chunk size");
                    byte_count = static_cast<std::size_t>(signed_count);
                    result.bitstream.push_back(static_cast<std::uint8_t>((byte_count >> 8U) & 0xffU));
                    result.bitstream.push_back(static_cast<std::uint8_t>(byte_count & 0xffU));
                }
                if (offsets[index] + byte_count > buffers[index].size())
                    return fail(CodecStatus::EncodeFailed, "VESA chunk exceeds the allocated slice buffer");
                result.bitstream.insert(result.bitstream.end(),
                    buffers[index].begin() + static_cast<std::ptrdiff_t>(offsets[index]),
                    buffers[index].begin()
                        + static_cast<std::ptrdiff_t>(offsets[index] + byte_count));
                offsets[index] += byte_count;
            }
        }
    }
    result.diagnostic = "encoded by the VESA DSC 1.67 reference algorithm";
    return result;
}

} // namespace dsc_function_tlm
