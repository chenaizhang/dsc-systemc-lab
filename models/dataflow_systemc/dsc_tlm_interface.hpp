#pragma once

#include <systemc>
#include <tlm>

#include <array>
#include <cstdint>
#include <ostream>

namespace dsc_tlm {

enum class EncoderCommand : std::uint32_t {
    Stop = 0,
    Reset = 1,
    EncodeChunk = 2,
    EncodeSlice = 3,
    EncodeFrame = 4,
    FreeRun = 5,
};

struct PixelBeat {
    std::array<std::uint16_t, 12> components{};
    std::uint8_t valid_pixels = 4;
    bool start_of_frame = false;
    bool end_of_frame = false;
    bool start_of_line = false;
    bool end_of_line = false;
};

inline std::ostream& operator<<(std::ostream& os, const PixelBeat& beat)
{
    return os << "PixelBeat(valid_pixels=" << static_cast<unsigned>(beat.valid_pixels)
              << ", sof=" << beat.start_of_frame << ", eof=" << beat.end_of_frame << ")";
}

struct SliceWorkItem {
    PixelBeat beat;
    std::uint32_t group_sequence = 0;
    std::uint32_t pps_generation = 0;
    std::uint8_t slice_id = 0;
};

inline std::ostream& operator<<(std::ostream& os, const SliceWorkItem& item)
{
    return os << "SliceWorkItem(group=" << item.group_sequence
              << ", slice=" << static_cast<unsigned>(item.slice_id) << ")";
}

struct EncodedBeat {
    std::array<std::uint8_t, 24> bytes{};
    std::uint8_t valid_bytes = 0;
    std::uint8_t slice_id = 0;
    bool start_of_frame = false;
    bool end_of_frame = false;
    bool start_of_line = false;
    bool end_of_line = false;
    bool algorithm_placeholder = true;
};

inline std::ostream& operator<<(std::ostream& os, const EncodedBeat& beat)
{
    return os << "EncodedBeat(valid_bytes=" << static_cast<unsigned>(beat.valid_bytes)
              << ", placeholder=" << beat.algorithm_placeholder << ")";
}

struct PixelStreamExtension : tlm::tlm_extension<PixelStreamExtension> {
    std::uint8_t valid_pixels = 0;
    bool start_of_frame = false;
    bool end_of_frame = false;
    bool start_of_line = false;
    bool end_of_line = false;

    PixelStreamExtension* clone() const override { return new PixelStreamExtension(*this); }
    void copy_from(const tlm::tlm_extension_base& other) override
    {
        *this = static_cast<const PixelStreamExtension&>(other);
    }
};

struct EncodedStreamExtension : tlm::tlm_extension<EncodedStreamExtension> {
    std::uint8_t valid_bytes = 0;
    std::uint8_t slice_id = 0;
    bool start_of_frame = false;
    bool end_of_frame = false;
    bool start_of_line = false;
    bool end_of_line = false;
    bool algorithm_placeholder = true;

    EncodedStreamExtension* clone() const override { return new EncodedStreamExtension(*this); }
    void copy_from(const tlm::tlm_extension_base& other) override
    {
        *this = static_cast<const EncodedStreamExtension&>(other);
    }
};

constexpr unsigned pixel_data_bytes = 24;
constexpr unsigned encoded_data_bytes = 24;

} // namespace dsc_tlm
