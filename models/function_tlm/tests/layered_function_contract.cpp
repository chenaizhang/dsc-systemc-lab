#include "dsc_layered_function_tlm.hpp"

#include <systemc>
#include <tlm>
#include <tlm_utils/simple_initiator_socket.h>
#include <tlm_utils/simple_target_socket.h>

#include <array>
#include <cstdint>
#include <string>
#include <vector>

namespace {

class DeterministicCodec final : public dsc_function_tlm::SoftwareDscCodec {
public:
    const char* name() const override { return "layered-function-contract-codec"; }
    bool is_bit_exact_golden() const override { return false; }
    dsc_function_tlm::CodecResult encode(
        const dsc_function_tlm::FrameRequest& request) override
    {
        dsc_function_tlm::CodecResult result;
        if (request.beats.size() != 1 || request.beats.front().valid_pixels != 4) {
            result.status = dsc_function_tlm::CodecStatus::InvalidFrame;
            result.diagnostic = "unexpected contract frame";
            return result;
        }
        result.status = dsc_function_tlm::CodecStatus::Ok;
        result.diagnostic = "deterministic contract output";
        for (std::uint8_t value = 0; value < 47; ++value)
            result.bitstream.push_back(static_cast<std::uint8_t>(value ^ 0x5aU));
        return result;
    }
};

struct Initiator : sc_core::sc_module {
    tlm_utils::simple_initiator_socket<Initiator, 32> apb{"apb"};
    tlm_utils::simple_initiator_socket<Initiator, 192> pixel{"pixel"};
    explicit Initiator(sc_core::sc_module_name name) : sc_core::sc_module(name) {}

    tlm::tlm_response_status write32(
        std::uint16_t address, std::uint32_t value, sc_core::sc_time& delay)
    {
        std::array<unsigned char, 4> data{
            static_cast<unsigned char>(value),
            static_cast<unsigned char>(value >> 8U),
            static_cast<unsigned char>(value >> 16U),
            static_cast<unsigned char>(value >> 24U)};
        tlm::tlm_generic_payload payload;
        payload.set_command(tlm::TLM_WRITE_COMMAND);
        payload.set_address(address);
        payload.set_data_ptr(data.data());
        payload.set_data_length(data.size());
        payload.set_streaming_width(data.size());
        apb->b_transport(payload, delay);
        return payload.get_response_status();
    }

    std::pair<tlm::tlm_response_status, std::uint32_t> read32(
        std::uint16_t address, sc_core::sc_time& delay)
    {
        std::array<unsigned char, 4> data{};
        tlm::tlm_generic_payload payload;
        payload.set_command(tlm::TLM_READ_COMMAND);
        payload.set_address(address);
        payload.set_data_ptr(data.data());
        payload.set_data_length(data.size());
        payload.set_streaming_width(data.size());
        apb->b_transport(payload, delay);
        const auto value = static_cast<std::uint32_t>(data[0])
            | (static_cast<std::uint32_t>(data[1]) << 8U)
            | (static_cast<std::uint32_t>(data[2]) << 16U)
            | (static_cast<std::uint32_t>(data[3]) << 24U);
        return {payload.get_response_status(), value};
    }

    tlm::tlm_response_status frame(sc_core::sc_time& delay)
    {
        std::array<unsigned char, dsc_tlm::pixel_data_bytes> data{};
        for (unsigned index = 0; index < data.size(); ++index)
            data[index] = static_cast<unsigned char>(index + 3U);
        dsc_tlm::PixelStreamExtension sideband;
        sideband.valid_pixels = 4;
        sideband.start_of_frame = true;
        sideband.end_of_frame = true;
        sideband.start_of_line = true;
        sideband.end_of_line = true;
        tlm::tlm_generic_payload payload;
        payload.set_command(tlm::TLM_WRITE_COMMAND);
        payload.set_data_ptr(data.data());
        payload.set_data_length(data.size());
        payload.set_streaming_width(data.size());
        payload.set_extension(&sideband);
        pixel->b_transport(payload, delay);
        payload.clear_extension<dsc_tlm::PixelStreamExtension>();
        return payload.get_response_status();
    }
};

struct Sink : sc_core::sc_module {
    tlm_utils::simple_target_socket<Sink, 192> target{"target"};
    std::vector<std::uint8_t> bytes;
    std::vector<bool> placeholders;
    explicit Sink(sc_core::sc_module_name name) : sc_core::sc_module(name)
    {
        target.register_b_transport(this, &Sink::transport);
    }
    void transport(tlm::tlm_generic_payload& payload, sc_core::sc_time& delay)
    {
        const auto* sideband = payload.get_extension<dsc_tlm::EncodedStreamExtension>();
        if (!payload.is_write() || payload.get_data_ptr() == nullptr || sideband == nullptr) {
            payload.set_response_status(tlm::TLM_BURST_ERROR_RESPONSE);
            return;
        }
        bytes.insert(bytes.end(), payload.get_data_ptr(),
            payload.get_data_ptr() + sideband->valid_bytes);
        placeholders.push_back(sideband->algorithm_placeholder);
        delay += sc_core::sc_time(2, sc_core::SC_NS);
        payload.set_response_status(tlm::TLM_OK_RESPONSE);
    }
};

bool has_exact_depth_one_modules(const sc_core::sc_module& top)
{
    static const std::array<std::string, 7> expected{
        "dsce_apb_inst", "dsce_timers_inst", "dsce_interrupt_inst",
        "dsce_pps_inst", "dsce_command_inst", "dsce_reset_inst",
        "dsce_engine_inst"};
    std::vector<std::string> observed;
    for (const auto* child : top.get_child_objects())
        if (dynamic_cast<const sc_core::sc_module*>(child) != nullptr)
            observed.emplace_back(child->basename());
    return observed.size() == expected.size()
        && std::all_of(expected.begin(), expected.end(), [&](const auto& name) {
               return std::find(observed.begin(), observed.end(), name) != observed.end();
           });
}

} // namespace

int sc_main(int, char**)
{
    DeterministicCodec flat_codec;
    DeterministicCodec layered_codec;
    dsc_function_tlm::DscFunctionTlm flat("flat", &flat_codec, false);
    dsc_function_tlm::DscLayeredFunctionTlm layered("layered", &layered_codec, false);
    Initiator flat_input("flat_input");
    Initiator layered_input("layered_input");
    Sink flat_sink("flat_sink");
    Sink layered_sink("layered_sink");
    flat_input.apb.bind(flat.apb);
    flat_input.pixel.bind(flat.pixel_stream_in);
    flat.bitstream_out.bind(flat_sink.target);
    layered_input.apb.bind(layered.apb);
    layered_input.pixel.bind(layered.pixel_stream_in);
    layered.bitstream_out.bind(layered_sink.target);
    sc_core::sc_start(sc_core::SC_ZERO_TIME);

    if (!has_exact_depth_one_modules(layered)) return 1;
    const std::array<std::pair<std::uint16_t, std::uint32_t>, 7> writes{{
        {0x008, 4}, {0x030, 5}, {0x080, 0x7f}, {0x104, 3},
        {0x100, 0x12}, {0x108, 1},
        {0x000, static_cast<std::uint32_t>(dsc_tlm::EncoderCommand::EncodeFrame)}}};
    sc_core::sc_time flat_delay = sc_core::SC_ZERO_TIME;
    sc_core::sc_time layered_delay = sc_core::SC_ZERO_TIME;
    for (const auto& [address, value] : writes) {
        if (flat_input.write32(address, value, flat_delay)
                != layered_input.write32(address, value, layered_delay)
            || flat_delay != layered_delay)
            return 2;
    }
    if (flat_input.frame(flat_delay) != layered_input.frame(layered_delay)
        || flat_delay != layered_delay)
        return 3;
    if (flat_sink.bytes != layered_sink.bytes
        || flat_sink.placeholders != layered_sink.placeholders
        || flat.encoded_frame_count() != layered.encoded_frame_count()
        || flat.last_codec_status() != layered.last_codec_status()
        || flat.active() != layered.active())
        return 4;

    auto flat_cause = flat_input.read32(0x084, flat_delay);
    auto layered_cause = layered_input.read32(0x084, layered_delay);
    if (flat_cause != layered_cause || flat_delay != layered_delay
        || flat_cause.second != (1U << 2))
        return 5;
    auto flat_cause_after_clear = flat_input.read32(0x084, flat_delay);
    auto layered_cause_after_clear = layered_input.read32(0x084, layered_delay);
    if (flat_cause_after_clear != layered_cause_after_clear
        || flat_cause_after_clear.second != 0 || flat_delay != layered_delay)
        return 6;
    return 0;
}
