#include "dsc_tlm.hpp"

#include <array>
#include <cstdint>
#include <cstring>
#include <iostream>
#include <stdexcept>


using namespace dsc_tlm;

struct HostAndVideoSource : sc_core::sc_module {
    tlm_utils::simple_initiator_socket<HostAndVideoSource, 32> apb{"apb"};
    tlm_utils::simple_initiator_socket<HostAndVideoSource, 192> pixels{"pixels"};
    tlm_utils::simple_target_socket<HostAndVideoSource, 192> encoded{"encoded"};
    EncodedBeat received{};
    sc_core::sc_event encoded_ready;

    SC_CTOR(HostAndVideoSource)
    {
        encoded.register_b_transport(this, &HostAndVideoSource::receive_encoded);
        SC_THREAD(run);
    }

    void run()
    {
        write32(0x104, 0);
        write32(0x100, 0x12);
        write32(0x100, 0x0b);
        write32(0x108, 1);
        write32(0x080, 0x04);
        write32(0x000, static_cast<std::uint32_t>(EncoderCommand::FreeRun));
        wait(sc_core::SC_ZERO_TIME);

        PixelBeat beat;
        beat.valid_pixels = 4;
        beat.start_of_frame = true;
        beat.end_of_frame = true;
        beat.start_of_line = true;
        beat.end_of_line = true;
        for (unsigned index = 0; index < beat.components.size(); ++index)
            beat.components[index] = static_cast<std::uint16_t>(0x100 + index);
        send_pixel(beat);

        wait(encoded_ready);
        const auto result = received;
        if (!result.algorithm_placeholder || result.bytes[0] != 0xd5 || result.bytes[1] != 0xc0)
            throw std::runtime_error("unexpected skeleton output marker");

        const auto active = read32(0x004);
        const auto frame_count = read32(0x020);
        const auto cause = read32(0x084);
        const auto cleared_cause = read32(0x084);
        std::cout << "DSC TLM skeleton completed: active=" << active
                  << " frame_count=" << frame_count
                  << " interrupt_cause=0x" << std::hex << cause
                  << " cleared=0x" << cleared_cause << std::dec
                  << " valid_bytes=" << static_cast<unsigned>(result.valid_bytes) << '\n';

        if (active != 1 || frame_count != 1 || cause != 0x04 || cleared_cause != 0)
            throw std::runtime_error("control/status contract failed");
        write32(0x000, static_cast<std::uint32_t>(EncoderCommand::Stop));
        sc_core::sc_stop();
    }

    void send_pixel(PixelBeat& beat)
    {
        std::array<unsigned char, pixel_data_bytes> data{};
        for (unsigned index = 0; index < beat.components.size(); ++index) {
            data[2 * index] = static_cast<unsigned char>(beat.components[index] & 0xff);
            data[2 * index + 1] = static_cast<unsigned char>(beat.components[index] >> 8);
        }
        PixelStreamExtension sideband;
        sideband.valid_pixels = beat.valid_pixels;
        sideband.start_of_frame = beat.start_of_frame;
        sideband.end_of_frame = beat.end_of_frame;
        sideband.start_of_line = beat.start_of_line;
        sideband.end_of_line = beat.end_of_line;
        tlm::tlm_generic_payload payload;
        payload.set_command(tlm::TLM_WRITE_COMMAND);
        payload.set_address(0);
        payload.set_data_ptr(data.data());
        payload.set_data_length(data.size());
        payload.set_streaming_width(data.size());
        payload.set_extension(&sideband);
        sc_core::sc_time delay = sc_core::SC_ZERO_TIME;
        pixels->b_transport(payload, delay);
        payload.clear_extension<PixelStreamExtension>();
        if (payload.is_response_error())
            throw std::runtime_error("AXI4-Stream input transaction failed");
        wait(delay);
    }

    void receive_encoded(tlm::tlm_generic_payload& payload, sc_core::sc_time& delay)
    {
        const auto* sideband = payload.get_extension<EncodedStreamExtension>();
        if (!payload.is_write() || payload.get_data_ptr() == nullptr || sideband == nullptr ||
            payload.get_data_length() != encoded_data_bytes) {
            payload.set_response_status(tlm::TLM_BURST_ERROR_RESPONSE);
            return;
        }
        std::memcpy(received.bytes.data(), payload.get_data_ptr(), encoded_data_bytes);
        received.valid_bytes = sideband->valid_bytes;
        received.slice_id = sideband->slice_id;
        received.start_of_frame = sideband->start_of_frame;
        received.end_of_frame = sideband->end_of_frame;
        received.start_of_line = sideband->start_of_line;
        received.end_of_line = sideband->end_of_line;
        received.algorithm_placeholder = sideband->algorithm_placeholder;
        delay += sc_core::sc_time(1, sc_core::SC_NS);
        payload.set_response_status(tlm::TLM_OK_RESPONSE);
        encoded_ready.notify(sc_core::SC_ZERO_TIME);
    }

    void write32(std::uint64_t address, std::uint32_t value)
    {
        std::array<unsigned char, 4> byte_enable{0xff, 0xff, 0xff, 0xff};
        tlm::tlm_generic_payload payload;
        payload.set_command(tlm::TLM_WRITE_COMMAND);
        payload.set_address(address);
        payload.set_data_ptr(reinterpret_cast<unsigned char*>(&value));
        payload.set_data_length(sizeof(value));
        payload.set_streaming_width(sizeof(value));
        payload.set_byte_enable_ptr(byte_enable.data());
        payload.set_byte_enable_length(byte_enable.size());
        sc_core::sc_time delay = sc_core::SC_ZERO_TIME;
        apb->b_transport(payload, delay);
        if (payload.is_response_error())
            throw std::runtime_error("APB write failed");
        wait(delay);
    }

    std::uint32_t read32(std::uint64_t address)
    {
        std::uint32_t value = 0;
        tlm::tlm_generic_payload payload;
        payload.set_command(tlm::TLM_READ_COMMAND);
        payload.set_address(address);
        payload.set_data_ptr(reinterpret_cast<unsigned char*>(&value));
        payload.set_data_length(sizeof(value));
        payload.set_streaming_width(sizeof(value));
        sc_core::sc_time delay = sc_core::SC_ZERO_TIME;
        apb->b_transport(payload, delay);
        if (payload.is_response_error())
            throw std::runtime_error("APB read failed");
        wait(delay);
        return value;
    }
};

int sc_main(int, char**)
{
    DscEncoderTlm dut("dut");
    HostAndVideoSource host("host");
    sc_core::sc_signal<bool> irq("irq");

    host.apb.bind(dut.apb);
    host.pixels.bind(dut.pixel_stream_in);
    dut.bitstream_out.bind(host.encoded);
    dut.irq(irq);

    sc_core::sc_start();
    return 0;
}
