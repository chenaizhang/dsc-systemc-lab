#pragma once

#include <systemc>
#include <tlm>
#include <tlm_utils/simple_initiator_socket.h>
#include <tlm_utils/simple_target_socket.h>

#include <algorithm>
#include <array>
#include <cstddef>
#include <cstdint>
#include <cstring>
#include <string>
#include <utility>
#include <vector>

#include "dsc_tlm_interface.hpp"

namespace dsc_function_tlm {

enum class CodecStatus {
    Ok,
    InvalidFrame,
    InvalidPps,
    CodecUnavailable,
    CodecNotGolden,
    EncodeFailed,
};

struct FrameRequest {
    std::array<std::uint8_t, 128> pps{};
    std::vector<dsc_tlm::PixelBeat> beats;
    std::uint8_t pixels_per_cycle = 4;
    std::uint8_t output_mode = 7;
};

struct CodecResult {
    CodecStatus status = CodecStatus::EncodeFailed;
    std::vector<std::uint8_t> bitstream;
    std::string diagnostic;
};

// Adapter point for an independently validated DSC C/C++ reference codec.
// The SystemC model owns no codec algorithm and never fabricates a bitstream.
class SoftwareDscCodec {
public:
    virtual ~SoftwareDscCodec() = default;
    virtual const char* name() const = 0;
    virtual bool is_bit_exact_golden() const = 0;
    virtual CodecResult encode(const FrameRequest& request) = 0;
};

// A single transaction-driven module.  It intentionally contains no child
// SC_MODULE, sc_fifo, SC_METHOD, SC_THREAD, SC_CTHREAD, or clock-edge process.
class DscFunctionTlm : public sc_core::sc_module {
public:
    tlm_utils::simple_target_socket<DscFunctionTlm, 32> apb{"apb"};
    tlm_utils::simple_target_socket<DscFunctionTlm, 192> pixel_stream_in{"pixel_stream_in"};
    tlm_utils::simple_initiator_socket<DscFunctionTlm, 192> bitstream_out{"bitstream_out"};

    explicit DscFunctionTlm(
        sc_core::sc_module_name name,
        SoftwareDscCodec* codec = nullptr,
        bool require_golden_codec = true)
        : sc_core::sc_module(name), codec_(codec), require_golden_codec_(require_golden_codec)
    {
        apb.register_b_transport(this, &DscFunctionTlm::apb_transport);
        pixel_stream_in.register_b_transport(this, &DscFunctionTlm::pixel_transport);
    }

    void set_codec(SoftwareDscCodec* codec) { codec_ = codec; }
    CodecStatus last_codec_status() const { return last_codec_status_; }
    const std::string& last_diagnostic() const { return last_diagnostic_; }
    std::uint32_t encoded_frame_count() const { return encoded_frame_count_; }
    bool active() const { return active_; }

private:
    static constexpr std::uint32_t kInterruptEndOfFrame = 1U << 2;
    static constexpr std::uint32_t kInterruptRateError = 1U << 3;

    SoftwareDscCodec* codec_ = nullptr;
    bool require_golden_codec_ = true;
    dsc_tlm::EncoderCommand command_ = dsc_tlm::EncoderCommand::Stop;
    bool active_ = false;
    bool collecting_frame_ = false;
    bool pps_commit_pending_ = false;
    std::uint8_t pixels_per_cycle_ = 4;
    std::uint8_t output_mode_ = 7;
    std::uint8_t pps_index_ = 0;
    std::uint32_t interrupt_enable_ = 0;
    std::uint32_t interrupt_cause_ = 0;
    std::uint32_t interrupt_state_ = 0;
    std::uint32_t encoded_frame_count_ = 0;
    std::array<std::uint8_t, 128> pps_shadow_{};
    std::array<std::uint8_t, 128> pps_active_{};
    std::vector<dsc_tlm::PixelBeat> frame_beats_;
    CodecStatus last_codec_status_ = CodecStatus::CodecUnavailable;
    std::string last_diagnostic_ = "no software DSC codec is installed";

    void apb_transport(tlm::tlm_generic_payload& trans, sc_core::sc_time& delay)
    {
        if (trans.get_data_ptr() == nullptr || trans.get_data_length() < sizeof(std::uint32_t)
            || trans.get_address() > 0xfff || (trans.get_address() & 3U) != 0) {
            trans.set_response_status(tlm::TLM_ADDRESS_ERROR_RESPONSE);
            return;
        }
        std::uint32_t value = 0;
        std::memcpy(&value, trans.get_data_ptr(), sizeof(value));
        const auto address = static_cast<std::uint16_t>(trans.get_address());
        bool okay = false;
        if (trans.is_write()) {
            value = merge_byte_enables(address, value, trans);
            okay = write32(address, value);
        } else if (trans.is_read()) {
            value = read32(address, okay);
            std::memcpy(trans.get_data_ptr(), &value, sizeof(value));
        }
        delay += sc_core::sc_time(1, sc_core::SC_NS);
        trans.set_response_status(okay ? tlm::TLM_OK_RESPONSE : tlm::TLM_ADDRESS_ERROR_RESPONSE);
    }

    std::uint32_t merge_byte_enables(
        std::uint16_t address,
        std::uint32_t incoming,
        const tlm::tlm_generic_payload& trans)
    {
        const auto* enables = trans.get_byte_enable_ptr();
        if (enables == nullptr || trans.get_byte_enable_length() == 0)
            return incoming;
        bool read_okay = false;
        std::uint32_t merged = peek32(address, read_okay);
        if (!read_okay)
            merged = 0;
        for (unsigned index = 0; index < 4; ++index) {
            if (enables[index % trans.get_byte_enable_length()] != 0) {
                const std::uint32_t mask = 0xffU << (index * 8U);
                merged = (merged & ~mask) | (incoming & mask);
            }
        }
        return merged;
    }

    bool write32(std::uint16_t address, std::uint32_t value)
    {
        switch (address) {
        case 0x000:
            if (value > static_cast<std::uint32_t>(dsc_tlm::EncoderCommand::FreeRun))
                return false;
            apply_command(static_cast<dsc_tlm::EncoderCommand>(value));
            return true;
        case 0x008:
            if (value != 1 && value != 2 && value != 4)
                return false;
            pixels_per_cycle_ = static_cast<std::uint8_t>(value);
            return true;
        case 0x030:
            output_mode_ = static_cast<std::uint8_t>(value & 7U);
            return true;
        case 0x080:
            interrupt_enable_ = value & 0x7fU;
            return true;
        case 0x100:
            pps_shadow_[pps_index_] = static_cast<std::uint8_t>(value);
            pps_index_ = static_cast<std::uint8_t>((pps_index_ + 1U) & 0x7fU);
            return true;
        case 0x104:
            pps_index_ = static_cast<std::uint8_t>(value & 0x7fU);
            return true;
        case 0x108:
            pps_commit_pending_ = (value & 1U) != 0;
            return true;
        default:
            return false;
        }
    }

    void apply_command(dsc_tlm::EncoderCommand command)
    {
        command_ = command;
        if (command == dsc_tlm::EncoderCommand::Stop) {
            active_ = false;
        } else if (command == dsc_tlm::EncoderCommand::Reset) {
            active_ = false;
            collecting_frame_ = false;
            frame_beats_.clear();
            interrupt_cause_ = 0;
            interrupt_state_ = 0;
        } else {
            active_ = true;
        }
    }

    std::uint32_t peek32(std::uint16_t address, bool& okay) const
    {
        okay = true;
        switch (address) {
        case 0x000: return static_cast<std::uint32_t>(command_);
        case 0x004: return active_ ? 1U : 0U;
        case 0x008: return pixels_per_cycle_;
        case 0x020: return encoded_frame_count_;
        case 0x030: return output_mode_;
        case 0x080: return interrupt_enable_;
        case 0x084: return interrupt_cause_;
        case 0x088: return interrupt_state_;
        case 0x100: return pps_shadow_[pps_index_];
        case 0x104: return pps_index_;
        case 0x108: return pps_commit_pending_ ? 1U : 0U;
        default:
            okay = false;
            return 0;
        }
    }

    std::uint32_t read32(std::uint16_t address, bool& okay)
    {
        const auto value = peek32(address, okay);
        if (!okay)
            return 0;
        if (address == 0x084) {
            interrupt_cause_ = 0;
        } else if (address == 0x100) {
            pps_index_ = static_cast<std::uint8_t>((pps_index_ + 1U) & 0x7fU);
        }
        return value;
    }

    void pixel_transport(tlm::tlm_generic_payload& trans, sc_core::sc_time& delay)
    {
        const auto* sideband = trans.get_extension<dsc_tlm::PixelStreamExtension>();
        if (!trans.is_write() || trans.get_data_ptr() == nullptr || sideband == nullptr
            || trans.get_data_length() != dsc_tlm::pixel_data_bytes
            || (sideband->valid_pixels != 1 && sideband->valid_pixels != 2
                && sideband->valid_pixels != 4)) {
            trans.set_response_status(tlm::TLM_BURST_ERROR_RESPONSE);
            return;
        }
        if (!active_ || (sideband->start_of_frame && collecting_frame_)
            || (!sideband->start_of_frame && !collecting_frame_)) {
            trans.set_response_status(tlm::TLM_COMMAND_ERROR_RESPONSE);
            return;
        }
        if (sideband->start_of_frame) {
            collecting_frame_ = true;
            frame_beats_.clear();
            if (pps_commit_pending_) {
                pps_active_ = pps_shadow_;
                pps_commit_pending_ = false;
            }
        }

        dsc_tlm::PixelBeat beat;
        for (unsigned index = 0; index < beat.components.size(); ++index) {
            beat.components[index] = static_cast<std::uint16_t>(
                trans.get_data_ptr()[2 * index]
                | (static_cast<std::uint16_t>(trans.get_data_ptr()[2 * index + 1]) << 8U));
        }
        beat.valid_pixels = sideband->valid_pixels;
        beat.start_of_frame = sideband->start_of_frame;
        beat.end_of_frame = sideband->end_of_frame;
        beat.start_of_line = sideband->start_of_line;
        beat.end_of_line = sideband->end_of_line;
        frame_beats_.push_back(beat);
        delay += sc_core::sc_time(1, sc_core::SC_NS);

        if (!sideband->end_of_frame) {
            trans.set_response_status(tlm::TLM_OK_RESPONSE);
            return;
        }
        collecting_frame_ = false;
        const auto status = encode_complete_frame(delay);
        frame_beats_.clear();
        trans.set_response_status(status == CodecStatus::Ok
            ? tlm::TLM_OK_RESPONSE : tlm::TLM_GENERIC_ERROR_RESPONSE);
    }

    CodecStatus encode_complete_frame(sc_core::sc_time& delay)
    {
        if (codec_ == nullptr) {
            return codec_error(CodecStatus::CodecUnavailable, "no software DSC codec is installed");
        }
        if (require_golden_codec_ && !codec_->is_bit_exact_golden()) {
            return codec_error(CodecStatus::CodecNotGolden,
                std::string("codec is not approved as bit-exact golden: ") + codec_->name());
        }
        FrameRequest request;
        request.pps = pps_active_;
        request.beats = frame_beats_;
        request.pixels_per_cycle = pixels_per_cycle_;
        request.output_mode = output_mode_;
        auto result = codec_->encode(request);
        last_codec_status_ = result.status;
        last_diagnostic_ = result.diagnostic;
        if (result.status != CodecStatus::Ok || result.bitstream.empty())
            return codec_error(result.status == CodecStatus::Ok ? CodecStatus::EncodeFailed : result.status,
                result.diagnostic.empty() ? "codec returned no bitstream" : result.diagnostic);

        delay += sc_core::sc_time(10, sc_core::SC_NS);
        if (!emit_bitstream(result.bitstream, codec_->is_bit_exact_golden(), delay))
            return last_codec_status_;
        ++encoded_frame_count_;
        interrupt_cause_ |= kInterruptEndOfFrame;
        interrupt_state_ |= kInterruptEndOfFrame;
        if (command_ != dsc_tlm::EncoderCommand::FreeRun)
            active_ = false;
        last_codec_status_ = CodecStatus::Ok;
        return CodecStatus::Ok;
    }

    CodecStatus codec_error(CodecStatus status, std::string diagnostic)
    {
        last_codec_status_ = status;
        last_diagnostic_ = std::move(diagnostic);
        interrupt_cause_ |= kInterruptRateError;
        interrupt_state_ |= kInterruptRateError;
        active_ = false;
        return status;
    }

    bool emit_bitstream(
        const std::vector<std::uint8_t>& bitstream,
        bool is_golden,
        sc_core::sc_time& parent_delay)
    {
        const std::size_t chunks = (bitstream.size() + dsc_tlm::encoded_data_bytes - 1)
            / dsc_tlm::encoded_data_bytes;
        for (std::size_t chunk = 0; chunk < chunks; ++chunk) {
            std::array<unsigned char, dsc_tlm::encoded_data_bytes> data{};
            const auto offset = chunk * dsc_tlm::encoded_data_bytes;
            const auto count = std::min<std::size_t>(
                dsc_tlm::encoded_data_bytes, bitstream.size() - offset);
            std::copy_n(bitstream.begin() + static_cast<std::ptrdiff_t>(offset), count, data.begin());

            dsc_tlm::EncodedStreamExtension sideband;
            sideband.valid_bytes = static_cast<std::uint8_t>(count);
            sideband.slice_id = 0;
            sideband.start_of_frame = chunk == 0;
            sideband.end_of_frame = chunk + 1 == chunks;
            sideband.start_of_line = chunk == 0;
            sideband.end_of_line = chunk + 1 == chunks;
            sideband.algorithm_placeholder = !is_golden;

            tlm::tlm_generic_payload output;
            output.set_command(tlm::TLM_WRITE_COMMAND);
            output.set_address(0);
            output.set_data_ptr(data.data());
            output.set_data_length(dsc_tlm::encoded_data_bytes);
            output.set_streaming_width(dsc_tlm::encoded_data_bytes);
            output.set_extension(&sideband);
            sc_core::sc_time output_delay = sc_core::SC_ZERO_TIME;
            bitstream_out->b_transport(output, output_delay);
            output.clear_extension<dsc_tlm::EncodedStreamExtension>();
            parent_delay += output_delay;
            if (output.is_response_error()) {
                codec_error(CodecStatus::EncodeFailed, "downstream rejected encoded data");
                return false;
            }
        }
        return true;
    }
};

} // namespace dsc_function_tlm
