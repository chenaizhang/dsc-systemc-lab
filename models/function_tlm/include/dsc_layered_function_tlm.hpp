#pragma once

#include "dsc_function_tlm.hpp"

#include <array>
#include <cstdint>
#include <cstring>
#include <string>
#include <utility>
#include <vector>

namespace dsc_function_tlm {

class DsceApbFunction : public sc_core::sc_module {
public:
    explicit DsceApbFunction(sc_core::sc_module_name name) : sc_core::sc_module(name) {}

    bool validate(const tlm::tlm_generic_payload& payload) const
    {
        return payload.get_data_ptr() != nullptr
            && payload.get_data_length() >= sizeof(std::uint32_t)
            && payload.get_address() <= 0xfffU && (payload.get_address() & 3U) == 0;
    }

    std::uint32_t merge_byte_enables(
        std::uint32_t previous, std::uint32_t incoming,
        const tlm::tlm_generic_payload& payload) const
    {
        const auto* enables = payload.get_byte_enable_ptr();
        if (enables == nullptr || payload.get_byte_enable_length() == 0)
            return incoming;
        std::uint32_t merged = previous;
        for (unsigned index = 0; index < 4; ++index) {
            if (enables[index % payload.get_byte_enable_length()] != 0) {
                const std::uint32_t mask = 0xffU << (index * 8U);
                merged = (merged & ~mask) | (incoming & mask);
            }
        }
        return merged;
    }
};

class DsceCommandFunction : public sc_core::sc_module {
public:
    explicit DsceCommandFunction(sc_core::sc_module_name name) : sc_core::sc_module(name) {}

    bool apply(std::uint32_t raw)
    {
        if (raw > static_cast<std::uint32_t>(dsc_tlm::EncoderCommand::FreeRun))
            return false;
        command_ = static_cast<dsc_tlm::EncoderCommand>(raw);
        if (command_ == dsc_tlm::EncoderCommand::Stop
            || command_ == dsc_tlm::EncoderCommand::Reset) {
            active_ = false;
            collecting_ = false;
        } else {
            active_ = true;
        }
        return true;
    }

    bool begin_frame(bool start_of_frame)
    {
        if (!active_ || (start_of_frame && collecting_)
            || (!start_of_frame && !collecting_))
            return false;
        if (start_of_frame)
            collecting_ = true;
        return true;
    }

    void finish_frame()
    {
        collecting_ = false;
        if (command_ != dsc_tlm::EncoderCommand::FreeRun)
            active_ = false;
    }

    void fail_frame()
    {
        collecting_ = false;
        active_ = false;
    }

    dsc_tlm::EncoderCommand command() const { return command_; }
    bool active() const { return active_; }
    bool collecting() const { return collecting_; }

private:
    dsc_tlm::EncoderCommand command_ = dsc_tlm::EncoderCommand::Stop;
    bool active_ = false;
    bool collecting_ = false;
};

class DscePpsFunction : public sc_core::sc_module {
public:
    explicit DscePpsFunction(sc_core::sc_module_name name) : sc_core::sc_module(name) {}

    void write_data(std::uint8_t value)
    {
        shadow_[index_] = value;
        index_ = static_cast<std::uint8_t>((index_ + 1U) & 0x7fU);
    }
    std::uint8_t read_data()
    {
        const auto value = shadow_[index_];
        index_ = static_cast<std::uint8_t>((index_ + 1U) & 0x7fU);
        return value;
    }
    std::uint8_t peek_data() const { return shadow_[index_]; }
    void set_index(std::uint8_t index) { index_ = index & 0x7fU; }
    std::uint8_t index() const { return index_; }
    void request_commit(bool pending) { commit_pending_ = pending; }
    bool commit_pending() const { return commit_pending_; }
    void commit_at_frame_start()
    {
        if (commit_pending_) {
            active_ = shadow_;
            commit_pending_ = false;
        }
    }
    const std::array<std::uint8_t, 128>& active() const { return active_; }

private:
    std::array<std::uint8_t, 128> shadow_{};
    std::array<std::uint8_t, 128> active_{};
    std::uint8_t index_ = 0;
    bool commit_pending_ = false;
};

class DsceTimersFunction : public sc_core::sc_module {
public:
    explicit DsceTimersFunction(sc_core::sc_module_name name) : sc_core::sc_module(name) {}
    void frame_completed() { ++encoded_frames_; }
    void reset() { encoded_frames_ = 0; }
    std::uint32_t encoded_frames() const { return encoded_frames_; }

private:
    std::uint32_t encoded_frames_ = 0;
};

class DsceInterruptFunction : public sc_core::sc_module {
public:
    explicit DsceInterruptFunction(sc_core::sc_module_name name) : sc_core::sc_module(name) {}
    void set_enable(std::uint32_t value) { enable_ = value & 0x7fU; }
    void raise(std::uint32_t mask) { cause_ |= mask; state_ |= mask; }
    std::uint32_t take_cause() { const auto value = cause_; cause_ = 0; return value; }
    void reset() { cause_ = 0; state_ = 0; }
    std::uint32_t enable() const { return enable_; }
    std::uint32_t cause() const { return cause_; }
    std::uint32_t state() const { return state_; }

private:
    std::uint32_t enable_ = 0;
    std::uint32_t cause_ = 0;
    std::uint32_t state_ = 0;
};

class DsceResetFunction : public sc_core::sc_module {
public:
    explicit DsceResetFunction(sc_core::sc_module_name name) : sc_core::sc_module(name) {}
    bool requested(dsc_tlm::EncoderCommand command) const
    {
        return command == dsc_tlm::EncoderCommand::Reset;
    }
};

class DsceEngineFunction : public sc_core::sc_module {
public:
    explicit DsceEngineFunction(sc_core::sc_module_name name,
        SoftwareDscCodec* codec = nullptr, bool require_golden = true)
        : sc_core::sc_module(name), codec_(codec), require_golden_(require_golden) {}

    void clear() { beats_.clear(); }
    void push(const dsc_tlm::PixelBeat& beat) { beats_.push_back(beat); }
    void set_codec(SoftwareDscCodec* codec) { codec_ = codec; }
    bool codec_is_golden() const
    {
        return codec_ != nullptr && codec_->is_bit_exact_golden();
    }

    CodecResult encode(const std::array<std::uint8_t, 128>& pps,
        std::uint8_t pixels_per_cycle, std::uint8_t output_mode)
    {
        if (codec_ == nullptr)
            return {CodecStatus::CodecUnavailable, {}, "no software DSC codec is installed"};
        if (require_golden_ && !codec_->is_bit_exact_golden())
            return {CodecStatus::CodecNotGolden, {},
                std::string("codec is not approved as bit-exact golden: ") + codec_->name()};
        FrameRequest request;
        request.pps = pps;
        request.beats = beats_;
        request.pixels_per_cycle = pixels_per_cycle;
        request.output_mode = output_mode;
        return codec_->encode(request);
    }

private:
    SoftwareDscCodec* codec_ = nullptr;
    bool require_golden_ = true;
    std::vector<dsc_tlm::PixelBeat> beats_;
};

// Transaction-level top whose seven child SC_MODULEs match the first RTL
// hierarchy level.  Each child implements a coarse pure function; no child
// contains SC_METHOD/SC_THREAD or attempts to reproduce cycle timing.
class DscLayeredFunctionTlm : public sc_core::sc_module {
public:
    tlm_utils::simple_target_socket<DscLayeredFunctionTlm, 32> apb{"apb"};
    tlm_utils::simple_target_socket<DscLayeredFunctionTlm, 192> pixel_stream_in{"pixel_stream_in"};
    tlm_utils::simple_initiator_socket<DscLayeredFunctionTlm, 192> bitstream_out{"bitstream_out"};

    DsceApbFunction dsce_apb_inst{"dsce_apb_inst"};
    DsceTimersFunction dsce_timers_inst{"dsce_timers_inst"};
    DsceInterruptFunction dsce_interrupt_inst{"dsce_interrupt_inst"};
    DscePpsFunction dsce_pps_inst{"dsce_pps_inst"};
    DsceCommandFunction dsce_command_inst{"dsce_command_inst"};
    DsceResetFunction dsce_reset_inst{"dsce_reset_inst"};
    DsceEngineFunction dsce_engine_inst;

    explicit DscLayeredFunctionTlm(sc_core::sc_module_name name,
        SoftwareDscCodec* codec = nullptr, bool require_golden_codec = true)
        : sc_core::sc_module(name)
        , dsce_engine_inst("dsce_engine_inst", codec, require_golden_codec)
    {
        apb.register_b_transport(this, &DscLayeredFunctionTlm::apb_transport);
        pixel_stream_in.register_b_transport(this, &DscLayeredFunctionTlm::pixel_transport);
    }

    CodecStatus last_codec_status() const { return last_codec_status_; }
    const std::string& last_diagnostic() const { return last_diagnostic_; }
    std::uint32_t encoded_frame_count() const { return dsce_timers_inst.encoded_frames(); }
    bool active() const { return dsce_command_inst.active(); }

private:
    static constexpr std::uint32_t kInterruptEndOfFrame = 1U << 2;
    static constexpr std::uint32_t kInterruptRateError = 1U << 3;
    std::uint8_t pixels_per_cycle_ = 4;
    std::uint8_t output_mode_ = 7;
    CodecStatus last_codec_status_ = CodecStatus::CodecUnavailable;
    std::string last_diagnostic_ = "no software DSC codec is installed";

    std::uint32_t peek32(std::uint16_t address, bool& okay) const
    {
        okay = true;
        switch (address) {
        case 0x000: return static_cast<std::uint32_t>(dsce_command_inst.command());
        case 0x004: return dsce_command_inst.active() ? 1U : 0U;
        case 0x008: return pixels_per_cycle_;
        case 0x020: return dsce_timers_inst.encoded_frames();
        case 0x030: return output_mode_;
        case 0x080: return dsce_interrupt_inst.enable();
        case 0x084: return dsce_interrupt_inst.cause();
        case 0x088: return dsce_interrupt_inst.state();
        case 0x100: return dsce_pps_inst.peek_data();
        case 0x104: return dsce_pps_inst.index();
        case 0x108: return dsce_pps_inst.commit_pending() ? 1U : 0U;
        default: okay = false; return 0;
        }
    }

    bool write32(std::uint16_t address, std::uint32_t value)
    {
        switch (address) {
        case 0x000:
            if (!dsce_command_inst.apply(value)) return false;
            if (dsce_reset_inst.requested(dsce_command_inst.command())) {
                dsce_engine_inst.clear();
                dsce_interrupt_inst.reset();
            }
            return true;
        case 0x008:
            if (value != 1 && value != 2 && value != 4) return false;
            pixels_per_cycle_ = static_cast<std::uint8_t>(value); return true;
        case 0x030: output_mode_ = static_cast<std::uint8_t>(value & 7U); return true;
        case 0x080: dsce_interrupt_inst.set_enable(value); return true;
        case 0x100: dsce_pps_inst.write_data(static_cast<std::uint8_t>(value)); return true;
        case 0x104: dsce_pps_inst.set_index(static_cast<std::uint8_t>(value)); return true;
        case 0x108: dsce_pps_inst.request_commit((value & 1U) != 0); return true;
        default: return false;
        }
    }

    std::uint32_t read32(std::uint16_t address, bool& okay)
    {
        if (address == 0x084) { okay = true; return dsce_interrupt_inst.take_cause(); }
        if (address == 0x100) { okay = true; return dsce_pps_inst.read_data(); }
        return peek32(address, okay);
    }

    void apb_transport(tlm::tlm_generic_payload& payload, sc_core::sc_time& delay)
    {
        if (!dsce_apb_inst.validate(payload)) {
            payload.set_response_status(tlm::TLM_ADDRESS_ERROR_RESPONSE); return;
        }
        std::uint32_t value = 0;
        std::memcpy(&value, payload.get_data_ptr(), sizeof(value));
        const auto address = static_cast<std::uint16_t>(payload.get_address());
        bool okay = false;
        if (payload.is_write()) {
            bool read_okay = false;
            const auto previous = peek32(address, read_okay);
            value = dsce_apb_inst.merge_byte_enables(
                read_okay ? previous : 0U, value, payload);
            okay = write32(address, value);
        } else if (payload.is_read()) {
            value = read32(address, okay);
            std::memcpy(payload.get_data_ptr(), &value, sizeof(value));
        }
        delay += sc_core::sc_time(1, sc_core::SC_NS);
        payload.set_response_status(okay ? tlm::TLM_OK_RESPONSE : tlm::TLM_ADDRESS_ERROR_RESPONSE);
    }

    CodecStatus fail(CodecStatus status, std::string diagnostic)
    {
        last_codec_status_ = status;
        last_diagnostic_ = std::move(diagnostic);
        dsce_interrupt_inst.raise(kInterruptRateError);
        dsce_command_inst.fail_frame();
        return status;
    }

    bool emit(const CodecResult& result, bool golden, sc_core::sc_time& delay)
    {
        const auto chunks = (result.bitstream.size() + dsc_tlm::encoded_data_bytes - 1)
            / dsc_tlm::encoded_data_bytes;
        for (std::size_t chunk = 0; chunk < chunks; ++chunk) {
            std::array<unsigned char, dsc_tlm::encoded_data_bytes> data{};
            const auto offset = chunk * dsc_tlm::encoded_data_bytes;
            const auto count = std::min<std::size_t>(dsc_tlm::encoded_data_bytes,
                result.bitstream.size() - offset);
            std::copy_n(result.bitstream.begin() + static_cast<std::ptrdiff_t>(offset),
                count, data.begin());
            dsc_tlm::EncodedStreamExtension sideband;
            sideband.valid_bytes = static_cast<std::uint8_t>(count);
            sideband.start_of_frame = chunk == 0;
            sideband.end_of_frame = chunk + 1 == chunks;
            sideband.start_of_line = sideband.start_of_frame;
            sideband.end_of_line = sideband.end_of_frame;
            sideband.algorithm_placeholder = !golden;
            tlm::tlm_generic_payload output;
            output.set_command(tlm::TLM_WRITE_COMMAND);
            output.set_data_ptr(data.data());
            output.set_data_length(data.size());
            output.set_streaming_width(data.size());
            output.set_extension(&sideband);
            sc_core::sc_time output_delay = sc_core::SC_ZERO_TIME;
            bitstream_out->b_transport(output, output_delay);
            output.clear_extension<dsc_tlm::EncodedStreamExtension>();
            delay += output_delay;
            if (output.is_response_error()) return false;
        }
        return true;
    }

    void pixel_transport(tlm::tlm_generic_payload& payload, sc_core::sc_time& delay)
    {
        const auto* sideband = payload.get_extension<dsc_tlm::PixelStreamExtension>();
        if (!payload.is_write() || payload.get_data_ptr() == nullptr || sideband == nullptr
            || payload.get_data_length() != dsc_tlm::pixel_data_bytes
            || (sideband->valid_pixels != 1 && sideband->valid_pixels != 2
                && sideband->valid_pixels != 4)) {
            payload.set_response_status(tlm::TLM_BURST_ERROR_RESPONSE); return;
        }
        if (!dsce_command_inst.begin_frame(sideband->start_of_frame)) {
            payload.set_response_status(tlm::TLM_COMMAND_ERROR_RESPONSE); return;
        }
        if (sideband->start_of_frame) {
            dsce_engine_inst.clear();
            dsce_pps_inst.commit_at_frame_start();
        }
        dsc_tlm::PixelBeat beat;
        for (unsigned index = 0; index < beat.components.size(); ++index)
            beat.components[index] = static_cast<std::uint16_t>(payload.get_data_ptr()[2 * index]
                | (static_cast<std::uint16_t>(payload.get_data_ptr()[2 * index + 1]) << 8U));
        beat.valid_pixels = sideband->valid_pixels;
        beat.start_of_frame = sideband->start_of_frame;
        beat.end_of_frame = sideband->end_of_frame;
        beat.start_of_line = sideband->start_of_line;
        beat.end_of_line = sideband->end_of_line;
        dsce_engine_inst.push(beat);
        delay += sc_core::sc_time(1, sc_core::SC_NS);
        if (!sideband->end_of_frame) {
            payload.set_response_status(tlm::TLM_OK_RESPONSE); return;
        }
        auto result = dsce_engine_inst.encode(
            dsce_pps_inst.active(), pixels_per_cycle_, output_mode_);
        last_codec_status_ = result.status;
        last_diagnostic_ = result.diagnostic;
        if (result.status != CodecStatus::Ok || result.bitstream.empty()) {
            fail(result.status == CodecStatus::Ok ? CodecStatus::EncodeFailed : result.status,
                result.diagnostic.empty() ? "codec returned no bitstream" : result.diagnostic);
            payload.set_response_status(tlm::TLM_GENERIC_ERROR_RESPONSE); return;
        }
        delay += sc_core::sc_time(10, sc_core::SC_NS);
        if (!emit(result, dsce_engine_inst.codec_is_golden(), delay)) {
            fail(CodecStatus::EncodeFailed, "downstream rejected encoded data");
            payload.set_response_status(tlm::TLM_GENERIC_ERROR_RESPONSE); return;
        }
        dsce_timers_inst.frame_completed();
        dsce_interrupt_inst.raise(kInterruptEndOfFrame);
        dsce_command_inst.finish_frame();
        dsce_engine_inst.clear();
        payload.set_response_status(tlm::TLM_OK_RESPONSE);
    }
};

} // namespace dsc_function_tlm
