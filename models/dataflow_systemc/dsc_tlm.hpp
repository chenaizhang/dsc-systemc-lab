#pragma once

#include <systemc>
#include <tlm>
#include <tlm_utils/simple_initiator_socket.h>
#include <tlm_utils/simple_target_socket.h>

#include <array>
#include <cstdint>
#include <cstring>
#include <iomanip>
#include <ostream>
#include <stdexcept>

#include "dsc_tlm_interface.hpp"

namespace dsc_tlm {

// AXI4-Stream is collapsed to one semantic beat per TLM transaction at the IP
// boundary. The internal core deliberately sees typed FIFO items, not bus pins.
struct AxiStreamInputTlmWrapper : sc_core::sc_module {
    tlm_utils::simple_target_socket<AxiStreamInputTlmWrapper, 192> target{"target"};
    sc_core::sc_fifo_out<PixelBeat> output{"output"};

    SC_CTOR(AxiStreamInputTlmWrapper)
    {
        target.register_b_transport(this, &AxiStreamInputTlmWrapper::b_transport);
    }

    void b_transport(tlm::tlm_generic_payload& trans, sc_core::sc_time& delay)
    {
        const auto* sideband = trans.get_extension<PixelStreamExtension>();
        if (!trans.is_write() || trans.get_data_ptr() == nullptr || sideband == nullptr ||
            trans.get_data_length() != pixel_data_bytes) {
            trans.set_response_status(tlm::TLM_BURST_ERROR_RESPONSE);
            return;
        }
        PixelBeat beat;
        for (unsigned index = 0; index < beat.components.size(); ++index) {
            beat.components[index] = static_cast<std::uint16_t>(
                trans.get_data_ptr()[2 * index] |
                (static_cast<std::uint16_t>(trans.get_data_ptr()[2 * index + 1]) << 8));
        }
        beat.valid_pixels = sideband->valid_pixels;
        beat.start_of_frame = sideband->start_of_frame;
        beat.end_of_frame = sideband->end_of_frame;
        beat.start_of_line = sideband->start_of_line;
        beat.end_of_line = sideband->end_of_line;
        output.write(beat); // A full internal FIFO models stream backpressure.
        delay += sc_core::sc_time(1, sc_core::SC_NS);
        trans.set_response_status(tlm::TLM_OK_RESPONSE);
    }
};

struct AxiStreamOutputTlmWrapper : sc_core::sc_module {
    sc_core::sc_fifo_in<EncodedBeat> input{"input"};
    tlm_utils::simple_initiator_socket<AxiStreamOutputTlmWrapper, 192> initiator{"initiator"};

    SC_CTOR(AxiStreamOutputTlmWrapper) { SC_THREAD(run); }

    void run()
    {
        while (true) {
            const auto beat = input.read();
            auto data = beat.bytes;
            EncodedStreamExtension sideband;
            sideband.valid_bytes = beat.valid_bytes;
            sideband.slice_id = beat.slice_id;
            sideband.start_of_frame = beat.start_of_frame;
            sideband.end_of_frame = beat.end_of_frame;
            sideband.start_of_line = beat.start_of_line;
            sideband.end_of_line = beat.end_of_line;
            sideband.algorithm_placeholder = beat.algorithm_placeholder;
            tlm::tlm_generic_payload trans;
            trans.set_command(tlm::TLM_WRITE_COMMAND);
            trans.set_address(0);
            trans.set_data_ptr(data.data());
            trans.set_data_length(encoded_data_bytes);
            trans.set_streaming_width(encoded_data_bytes);
            trans.set_extension(&sideband);
            sc_core::sc_time delay = sc_core::SC_ZERO_TIME;
            initiator->b_transport(trans, delay);
            trans.clear_extension<EncodedStreamExtension>();
            if (trans.is_response_error())
                SC_REPORT_ERROR(name(), "AXI4-Stream output transaction failed");
            wait(delay);
        }
    }
};

struct SharedState {
    EncoderCommand command = EncoderCommand::Stop;
    bool active = false;
    bool pps_commit_pending = false;
    std::uint32_t pps_generation = 0;
    std::array<std::uint8_t, 128> pps_shadow{};
    std::array<std::uint8_t, 128> pps_active{};
    std::uint8_t pps_index = 0;
    std::uint8_t pixels_per_cycle = 4;
    std::uint8_t output_mode = 7;
    std::uint8_t interrupt_enable = 0;
    std::uint8_t interrupt_cause = 0;
    std::uint8_t interrupt_state = 0;
    std::uint8_t encoded_frame_count = 0;
    std::uint32_t group_sequence = 0;
    sc_core::sc_event command_changed;
    sc_core::sc_event irq_changed;

    bool irq_asserted() const { return (interrupt_cause & interrupt_enable) != 0; }

    void activate_pending_pps()
    {
        if (pps_commit_pending) {
            pps_active = pps_shadow;
            pps_commit_pending = false;
            ++pps_generation;
        }
    }

    void reset_engine_only()
    {
        active = false;
        interrupt_cause = 0;
        interrupt_state = 0;
        group_sequence = 0;
        irq_changed.notify(sc_core::SC_ZERO_TIME);
    }
};

struct ControlPlane : sc_core::sc_module {
    tlm_utils::simple_target_socket<ControlPlane, 32> target{"target"};
    SharedState& state;

    explicit ControlPlane(sc_core::sc_module_name name, SharedState& shared)
        : sc_core::sc_module(name), state(shared)
    {
        target.register_b_transport(this, &ControlPlane::b_transport);
    }

    void b_transport(tlm::tlm_generic_payload& trans, sc_core::sc_time& delay)
    {
        if (trans.get_data_ptr() == nullptr || trans.get_data_length() < 4 ||
            trans.get_address() > 0xfff || (trans.get_address() & 0x3) != 0) {
            trans.set_response_status(tlm::TLM_ADDRESS_ERROR_RESPONSE);
            return;
        }
        std::uint32_t value = 0;
        std::memcpy(&value, trans.get_data_ptr(), sizeof(value));
        const auto address = static_cast<std::uint16_t>(trans.get_address());
        bool okay = false;
        if (trans.is_write()) {
            okay = write32(address, merge_byte_enables(address, value, trans));
        } else if (trans.is_read()) {
            value = read32(address, okay);
            std::memcpy(trans.get_data_ptr(), &value, sizeof(value));
        }
        delay += sc_core::sc_time(10, sc_core::SC_NS);
        trans.set_response_status(okay ? tlm::TLM_OK_RESPONSE : tlm::TLM_ADDRESS_ERROR_RESPONSE);
    }

    std::uint32_t merge_byte_enables(
        std::uint16_t address,
        std::uint32_t incoming,
        const tlm::tlm_generic_payload& trans)
    {
        auto* byte_enable = trans.get_byte_enable_ptr();
        if (byte_enable == nullptr || trans.get_byte_enable_length() == 0)
            return incoming;
        bool read_okay = false;
        std::uint32_t merged = read32(address, read_okay);
        if (!read_okay)
            merged = 0;
        for (unsigned index = 0; index < 4; ++index) {
            if (byte_enable[index % trans.get_byte_enable_length()] != 0) {
                const std::uint32_t mask = 0xffu << (index * 8);
                merged = (merged & ~mask) | (incoming & mask);
            }
        }
        return merged;
    }

    bool write32(std::uint16_t address, std::uint32_t value)
    {
        switch (address) {
        case 0x000:
            if (value > static_cast<std::uint32_t>(EncoderCommand::FreeRun))
                return false;
            state.command = static_cast<EncoderCommand>(value);
            state.command_changed.notify(sc_core::SC_ZERO_TIME);
            return true;
        case 0x008:
            if (value != 1 && value != 2 && value != 4)
                return false;
            state.pixels_per_cycle = static_cast<std::uint8_t>(value);
            return true;
        case 0x030:
            state.output_mode = static_cast<std::uint8_t>(value & 0x7);
            return true;
        case 0x080:
            state.interrupt_enable = static_cast<std::uint8_t>(value & 0x7f);
            state.irq_changed.notify(sc_core::SC_ZERO_TIME);
            return true;
        case 0x100:
            state.pps_shadow[state.pps_index] = static_cast<std::uint8_t>(value);
            state.pps_index = static_cast<std::uint8_t>((state.pps_index + 1) & 0x7f);
            return true;
        case 0x104:
            state.pps_index = static_cast<std::uint8_t>(value & 0x7f);
            return true;
        case 0x108:
            if ((value & 1) != 0)
                state.pps_commit_pending = true;
            return true;
        default:
            return false;
        }
    }

    std::uint32_t read32(std::uint16_t address, bool& okay)
    {
        okay = true;
        switch (address) {
        case 0x000:
            return static_cast<std::uint32_t>(state.command);
        case 0x004:
            return state.active ? 1 : 0;
        case 0x008:
            return state.pixels_per_cycle;
        case 0x020:
            return state.encoded_frame_count;
        case 0x030:
            return state.output_mode;
        case 0x080:
            return state.interrupt_enable;
        case 0x084: {
            const auto cause = state.interrupt_cause;
            state.interrupt_cause = 0;
            state.irq_changed.notify(sc_core::SC_ZERO_TIME);
            return cause;
        }
        case 0x088:
            return state.interrupt_state;
        case 0x100: {
            const auto value = state.pps_shadow[state.pps_index];
            state.pps_index = static_cast<std::uint8_t>((state.pps_index + 1) & 0x7f);
            return value;
        }
        case 0x104:
            return state.pps_index;
        case 0x108:
            return state.pps_commit_pending ? 1 : 0;
        default:
            okay = false;
            return 0;
        }
    }
};

struct CommandSequencer : sc_core::sc_module {
    SharedState& state;

    SC_HAS_PROCESS(CommandSequencer);
    explicit CommandSequencer(sc_core::sc_module_name name, SharedState& shared)
        : sc_core::sc_module(name), state(shared)
    {
        SC_THREAD(run);
    }

    void run()
    {
        while (true) {
            wait(state.command_changed);
            switch (state.command) {
            case EncoderCommand::Stop:
                state.active = false;
                break;
            case EncoderCommand::Reset:
                state.reset_engine_only();
                break;
            case EncoderCommand::EncodeFrame:
            case EncoderCommand::FreeRun:
                state.active = true;
                break;
            case EncoderCommand::EncodeChunk:
            case EncoderCommand::EncodeSlice:
                SC_REPORT_WARNING(name(), "chunk/slice commands are not implemented in the draft skeleton");
                state.active = false;
                break;
            }
        }
    }
};

struct PixelFrontend : sc_core::sc_module {
    sc_core::sc_fifo_in<PixelBeat> input{"input"};
    sc_core::sc_fifo_out<SliceWorkItem> output{"output"};
    SharedState& state;

    SC_HAS_PROCESS(PixelFrontend);
    explicit PixelFrontend(sc_core::sc_module_name name, SharedState& shared)
        : sc_core::sc_module(name), state(shared)
    {
        SC_THREAD(run);
    }

    void run()
    {
        while (true) {
            while (!state.active)
                wait(state.command_changed);
            const auto beat = input.read();
            if (!state.active)
                continue;
            if (beat.start_of_frame)
                state.activate_pending_pps();
            SliceWorkItem work;
            work.beat = beat;
            work.group_sequence = state.group_sequence++;
            work.pps_generation = state.pps_generation;
            work.slice_id = 0; // Pool dispatch is intentionally deferred to the next model revision.
            output.write(work);
        }
    }
};

struct SliceProcessor : sc_core::sc_module {
    sc_core::sc_fifo_in<SliceWorkItem> input{"input"};
    sc_core::sc_fifo_out<EncodedBeat> output{"output"};
    sc_core::sc_time group_latency;

    SC_HAS_PROCESS(SliceProcessor);
    SliceProcessor(sc_core::sc_module_name name, sc_core::sc_time latency)
        : sc_core::sc_module(name), group_latency(latency)
    {
        SC_THREAD(run);
    }

    void run()
    {
        while (true) {
            const auto work = input.read();
            wait(group_latency);
            EncodedBeat encoded;
            encoded.bytes[0] = 0xd5;
            encoded.bytes[1] = 0xc0;
            encoded.bytes[2] = static_cast<std::uint8_t>(work.pps_generation);
            encoded.bytes[3] = static_cast<std::uint8_t>(work.group_sequence);
            const auto pixels = static_cast<unsigned>(work.beat.valid_pixels > 4 ? 4 : work.beat.valid_pixels);
            for (unsigned index = 0; index < pixels * 3; ++index)
                encoded.bytes[4 + index] = static_cast<std::uint8_t>(work.beat.components[index] & 0xff);
            encoded.valid_bytes = static_cast<std::uint8_t>(4 + pixels * 3);
            encoded.slice_id = work.slice_id;
            encoded.start_of_frame = work.beat.start_of_frame;
            encoded.end_of_frame = work.beat.end_of_frame;
            encoded.start_of_line = work.beat.start_of_line;
            encoded.end_of_line = work.beat.end_of_line;
            output.write(encoded);
        }
    }
};

struct BitstreamBackend : sc_core::sc_module {
    sc_core::sc_fifo_in<EncodedBeat> input{"input"};
    sc_core::sc_fifo_out<EncodedBeat> output{"output"};
    SharedState& state;

    SC_HAS_PROCESS(BitstreamBackend);
    explicit BitstreamBackend(sc_core::sc_module_name name, SharedState& shared)
        : sc_core::sc_module(name), state(shared)
    {
        SC_THREAD(run);
    }

    void run()
    {
        while (true) {
            const auto encoded = input.read();
            output.write(encoded);
            if (encoded.end_of_frame) {
                ++state.encoded_frame_count;
                state.interrupt_state |= 0x04;
                state.interrupt_cause |= 0x04;
                if (state.command == EncoderCommand::EncodeFrame)
                    state.active = false;
                state.irq_changed.notify(sc_core::SC_ZERO_TIME);
            }
        }
    }
};

struct DscEncoderTlm : sc_core::sc_module {
    tlm::tlm_target_socket<32> apb{"apb"};
    tlm::tlm_target_socket<192> pixel_stream_in{"pixel_stream_in"};
    tlm::tlm_initiator_socket<192> bitstream_out{"bitstream_out"};
    sc_core::sc_out<bool> irq{"irq"};

    SharedState state;
    ControlPlane control;
    AxiStreamInputTlmWrapper input_wrapper;
    AxiStreamOutputTlmWrapper output_wrapper;
    CommandSequencer sequencer;
    PixelFrontend frontend;
    SliceProcessor slice_processor;
    BitstreamBackend backend;
    sc_core::sc_fifo<SliceWorkItem> frontend_to_slice;
    sc_core::sc_fifo<EncodedBeat> slice_to_backend;
    sc_core::sc_fifo<PixelBeat> input_to_frontend;
    sc_core::sc_fifo<EncodedBeat> backend_to_output;

    SC_HAS_PROCESS(DscEncoderTlm);
    explicit DscEncoderTlm(sc_core::sc_module_name name)
        : sc_core::sc_module(name),
          control("control", state),
          input_wrapper("input_wrapper"),
          output_wrapper("output_wrapper"),
          sequencer("sequencer", state),
          frontend("frontend", state),
          slice_processor("slice_processor", sc_core::sc_time(5, sc_core::SC_NS)),
          backend("backend", state),
          frontend_to_slice("frontend_to_slice", 4),
          slice_to_backend("slice_to_backend", 4),
          input_to_frontend("input_to_frontend", 4),
          backend_to_output("backend_to_output", 4)
    {
        apb.bind(control.target);
        pixel_stream_in.bind(input_wrapper.target);
        input_wrapper.output(input_to_frontend);
        frontend.input(input_to_frontend);
        frontend.output(frontend_to_slice);
        slice_processor.input(frontend_to_slice);
        slice_processor.output(slice_to_backend);
        backend.input(slice_to_backend);
        backend.output(backend_to_output);
        output_wrapper.input(backend_to_output);
        output_wrapper.initiator.bind(bitstream_out);
        SC_METHOD(update_irq);
        sensitive << state.irq_changed;
    }

    void update_irq() { irq.write(state.irq_asserted()); }
};

} // namespace dsc_tlm
