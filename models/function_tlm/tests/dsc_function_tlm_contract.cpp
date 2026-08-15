#include "dsc_function_tlm.hpp"

#include <systemc>
#include <tlm>
#include <tlm_utils/simple_initiator_socket.h>
#include <tlm_utils/simple_target_socket.h>

#include <array>
#include <cstdint>
#include <vector>

namespace {

class NonGoldenTestCodec final : public dsc_function_tlm::SoftwareDscCodec {
public:
    const char* name() const override { return "non-golden-plumbing-test-codec"; }
    bool is_bit_exact_golden() const override { return false; }

    dsc_function_tlm::CodecResult encode(
        const dsc_function_tlm::FrameRequest& request) override
    {
        dsc_function_tlm::CodecResult result;
        if (request.beats.size() != 1 || request.beats[0].valid_pixels != 4) {
            result.status = dsc_function_tlm::CodecStatus::InvalidFrame;
            result.diagnostic = "unexpected plumbing-test frame";
            return result;
        }
        result.status = dsc_function_tlm::CodecStatus::Ok;
        for (std::uint8_t value = 0; value < 30; ++value)
            result.bitstream.push_back(value);
        return result;
    }
};

struct Initiator : sc_core::sc_module {
    tlm_utils::simple_initiator_socket<Initiator, 32> apb{"apb"};
    tlm_utils::simple_initiator_socket<Initiator, 192> pixel{"pixel"};

    explicit Initiator(sc_core::sc_module_name name) : sc_core::sc_module(name) {}

    tlm::tlm_response_status write_command(std::uint32_t command, sc_core::sc_time& delay)
    {
        std::array<unsigned char, 4> data{
            static_cast<unsigned char>(command), 0, 0, 0};
        tlm::tlm_generic_payload payload;
        payload.set_command(tlm::TLM_WRITE_COMMAND);
        payload.set_address(0);
        payload.set_data_ptr(data.data());
        payload.set_data_length(data.size());
        payload.set_streaming_width(data.size());
        apb->b_transport(payload, delay);
        return payload.get_response_status();
    }

    tlm::tlm_response_status write_single_beat(sc_core::sc_time& delay)
    {
        std::array<unsigned char, dsc_tlm::pixel_data_bytes> data{};
        for (unsigned component = 0; component < 12; ++component) {
            const std::uint16_t value = static_cast<std::uint16_t>(component + 1);
            data[2 * component] = static_cast<unsigned char>(value & 0xffU);
            data[2 * component + 1] = static_cast<unsigned char>(value >> 8U);
        }
        dsc_tlm::PixelStreamExtension sideband;
        sideband.valid_pixels = 4;
        sideband.start_of_frame = true;
        sideband.end_of_frame = true;
        sideband.start_of_line = true;
        sideband.end_of_line = true;

        tlm::tlm_generic_payload payload;
        payload.set_command(tlm::TLM_WRITE_COMMAND);
        payload.set_address(0);
        payload.set_data_ptr(data.data());
        payload.set_data_length(data.size());
        payload.set_streaming_width(data.size());
        payload.set_extension(&sideband);
        pixel->b_transport(payload, delay);
        payload.clear_extension<dsc_tlm::PixelStreamExtension>();
        return payload.get_response_status();
    }
};

struct EncodedSink : sc_core::sc_module {
    tlm_utils::simple_target_socket<EncodedSink, 192> target{"target"};
    std::vector<std::uint8_t> bytes;
    std::vector<bool> placeholders;

    explicit EncodedSink(sc_core::sc_module_name name) : sc_core::sc_module(name)
    {
        target.register_b_transport(this, &EncodedSink::b_transport);
    }

    void b_transport(tlm::tlm_generic_payload& payload, sc_core::sc_time& delay)
    {
        const auto* sideband = payload.get_extension<dsc_tlm::EncodedStreamExtension>();
        if (!payload.is_write() || payload.get_data_ptr() == nullptr || sideband == nullptr
            || sideband->valid_bytes > payload.get_data_length()) {
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

bool contains_child_module(const sc_core::sc_module& module)
{
    for (const auto* child : module.get_child_objects()) {
        if (dynamic_cast<const sc_core::sc_module*>(child) != nullptr)
            return true;
    }
    return false;
}

} // namespace

int sc_main(int, char**)
{
    NonGoldenTestCodec codec;
    dsc_function_tlm::DscFunctionTlm plumbing_model("plumbing_model", &codec, false);
    Initiator plumbing_initiator("plumbing_initiator");
    EncodedSink plumbing_sink("plumbing_sink");
    plumbing_initiator.apb.bind(plumbing_model.apb);
    plumbing_initiator.pixel.bind(plumbing_model.pixel_stream_in);
    plumbing_model.bitstream_out.bind(plumbing_sink.target);

    dsc_function_tlm::DscFunctionTlm strict_model("strict_model", &codec);
    Initiator strict_initiator("strict_initiator");
    EncodedSink strict_sink("strict_sink");
    strict_initiator.apb.bind(strict_model.apb);
    strict_initiator.pixel.bind(strict_model.pixel_stream_in);
    strict_model.bitstream_out.bind(strict_sink.target);

    sc_core::sc_start(sc_core::SC_ZERO_TIME);

    if (contains_child_module(plumbing_model) || contains_child_module(strict_model))
        return 1;

    sc_core::sc_time command_delay = sc_core::SC_ZERO_TIME;
    if (plumbing_initiator.write_command(
            static_cast<std::uint32_t>(dsc_tlm::EncoderCommand::EncodeFrame), command_delay)
            != tlm::TLM_OK_RESPONSE
        || command_delay != sc_core::sc_time(1, sc_core::SC_NS))
        return 2;

    sc_core::sc_time frame_delay = sc_core::SC_ZERO_TIME;
    if (plumbing_initiator.write_single_beat(frame_delay) != tlm::TLM_OK_RESPONSE
        || frame_delay != sc_core::sc_time(15, sc_core::SC_NS)
        || plumbing_model.encoded_frame_count() != 1
        || plumbing_model.last_codec_status() != dsc_function_tlm::CodecStatus::Ok)
        return 3;
    if (plumbing_sink.bytes.size() != 30 || plumbing_sink.placeholders.size() != 2)
        return 4;
    for (std::size_t index = 0; index < plumbing_sink.bytes.size(); ++index) {
        if (plumbing_sink.bytes[index] != index)
            return 5;
    }
    for (const bool placeholder : plumbing_sink.placeholders) {
        if (!placeholder)
            return 6;
    }

    sc_core::sc_time strict_command_delay = sc_core::SC_ZERO_TIME;
    if (strict_initiator.write_command(
            static_cast<std::uint32_t>(dsc_tlm::EncoderCommand::EncodeFrame), strict_command_delay)
        != tlm::TLM_OK_RESPONSE)
        return 7;
    sc_core::sc_time strict_frame_delay = sc_core::SC_ZERO_TIME;
    if (strict_initiator.write_single_beat(strict_frame_delay)
            != tlm::TLM_GENERIC_ERROR_RESPONSE
        || strict_model.last_codec_status() != dsc_function_tlm::CodecStatus::CodecNotGolden
        || !strict_sink.bytes.empty())
        return 8;

    return 0;
}
