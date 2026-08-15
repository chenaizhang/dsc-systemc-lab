#pragma once

#include <systemc>

#include <cstdint>

// Cycle-level SystemC implementation of the public APB/register behavior used
// by the DSC regression. Packed outputs preserve the SystemVerilog struct bit
// layout so this module can replace Verilator's Vdsce_apb in HybridTop.
SC_MODULE(CycleApb) {
    sc_core::sc_in<bool> apb_clk{"apb_clk"};
    sc_core::sc_in<bool> apb_reset_n{"apb_reset_n"};
    sc_core::sc_in<bool> apb_select{"apb_select"};
    sc_core::sc_in<bool> apb_enable{"apb_enable"};
    sc_core::sc_in<bool> apb_write{"apb_write"};
    sc_core::sc_in<std::uint32_t> apb_strobe{"apb_strobe"};
    sc_core::sc_in<std::uint32_t> apb_protect{"apb_protect"};
    sc_core::sc_in<std::uint32_t> apb_addr{"apb_addr"};
    sc_core::sc_in<std::uint32_t> apb_wdata{"apb_wdata"};
    sc_core::sc_out<bool> apb_ready{"apb_ready"};
    sc_core::sc_out<bool> apb_slave_error{"apb_slave_error"};
    sc_core::sc_out<std::uint32_t> apb_rdata{"apb_rdata"};

    sc_core::sc_out<bool> apb_pps_write{"apb_pps_write"};
    sc_core::sc_out<std::uint32_t> apb_pps_index{"apb_pps_index"};
    sc_core::sc_out<std::uint32_t> apb_pps_wdata{"apb_pps_wdata"};
    sc_core::sc_out<bool> apb_pps_commit{"apb_pps_commit"};
    sc_core::sc_in<std::uint32_t> apb_pps_rdata{"apb_pps_rdata"};

    sc_core::sc_out<sc_dt::sc_bv<92>> cfg_dsc_encoder{"cfg_dsc_encoder"};
    sc_core::sc_in<std::uint32_t> cfg_dsc_encoder_status{"cfg_dsc_encoder_status"};
    sc_core::sc_out<std::uint32_t> cfg_dsc_interrupt{"cfg_dsc_interrupt"};
    sc_core::sc_in<std::uint32_t> cfg_dsc_interrupt_status{"cfg_dsc_interrupt_status"};
    sc_core::sc_out<std::uint32_t> cfg_dsc_timers_config{"cfg_dsc_timers_config"};
    sc_core::sc_in<std::uint32_t> cfg_dsc_timers_status{"cfg_dsc_timers_status"};
    sc_core::sc_out<bool> apb_soft_reset{"apb_soft_reset"};

    SC_CTOR(CycleApb)
    {
        SC_METHOD(sequence);
        sensitive << apb_clk.pos() << apb_reset_n.neg();
        dont_initialize();
    }

private:
    bool pending_write_ = false;
    std::uint32_t pending_strobe_ = 0;
    std::uint32_t pending_addr_ = 0;
    std::uint32_t pending_wdata_ = 0;
    unsigned ready_count_ = 0;

    bool ready_ = true;
    bool pps_write_ = false;
    bool pps_commit_ = false;
    bool soft_reset_ = false;
    std::uint32_t pps_index_ = 0;
    std::uint32_t pps_wdata_ = 0;
    std::uint32_t rdata_ = 0;

    std::uint32_t follow_vsync_ = 0;
    std::uint32_t encode_command_ = 0;
    std::uint32_t command_toggle_ = 0;
    std::uint32_t timeout_count_ = 0;
    std::uint32_t pixels_per_cycle_ = 4;
    std::uint32_t slice_alignment_ = 0;
    std::uint32_t force_enable_ = 0;
    std::uint32_t qp_override_enable_ = 0;
    std::uint32_t qp_override_ = 0;
    std::uint32_t slices_per_line_ = 0;
    std::uint32_t slices_per_processor_ = 0;
    std::uint32_t slice_processor_count_ = 4;
    std::uint32_t clock_divider_ = 0;
    std::uint32_t output_mode_ = 7;
    std::uint32_t max_bits_per_group_ = 0;
    std::uint32_t trailing_bits_ = 0;
    std::uint32_t chunk_size_ = 0;
    std::uint32_t slice_buffer_depth_ = 0;

    std::uint32_t interrupt_enable_ = 0;
    std::uint32_t interrupt_clear_ = 0;
    std::uint32_t frame_interrupt_count_ = 0;
    std::uint32_t clear_frame_count_ = 0;
    std::uint32_t timer_autoreload_ = 0;
    std::uint32_t timer_reload_ = 0;
    std::uint32_t timer_enable_ = 0;
    std::uint32_t timer_interrupt_enable_ = 0;

    static bool strobe(std::uint32_t value, unsigned lane)
    {
        return ((value >> lane) & 1U) != 0U;
    }

    void reset_state()
    {
        pending_write_ = false;
        pending_strobe_ = 0;
        pending_addr_ = 0;
        pending_wdata_ = 0;
        ready_count_ = 0;
        ready_ = true;
        pps_write_ = false;
        pps_commit_ = false;
        soft_reset_ = false;
        pps_index_ = 0;
        pps_wdata_ = 0;
        rdata_ = 0;
        follow_vsync_ = 0;
        encode_command_ = 0;
        command_toggle_ = 0;
        timeout_count_ = 0;
        pixels_per_cycle_ = 4;
        slice_alignment_ = 0;
        force_enable_ = 0;
        qp_override_enable_ = 0;
        qp_override_ = 0;
        slices_per_line_ = 0;
        slices_per_processor_ = 0;
        slice_processor_count_ = 4;
        clock_divider_ = 0;
        output_mode_ = 7;
        max_bits_per_group_ = 0;
        trailing_bits_ = 0;
        chunk_size_ = 0;
        slice_buffer_depth_ = 0;
        interrupt_enable_ = 0;
        interrupt_clear_ = 0;
        frame_interrupt_count_ = 0;
        clear_frame_count_ = 0;
        timer_autoreload_ = 0;
        timer_reload_ = 0;
        timer_enable_ = 0;
        timer_interrupt_enable_ = 0;
    }

    void apply_write()
    {
        const auto data = pending_wdata_;
        switch (pending_addr_ & 0xfffU) {
        case 0x000:
            if (strobe(pending_strobe_, 0)) {
                encode_command_ = data & 0xfU;
                command_toggle_ ^= 1U;
            }
            break;
        case 0x008: if (strobe(pending_strobe_, 0)) pixels_per_cycle_ = data & 0x7U; break;
        case 0x00c: if (strobe(pending_strobe_, 0)) follow_vsync_ = data & 1U; break;
        case 0x010: if (strobe(pending_strobe_, 0)) timeout_count_ = data & 0xffU; break;
        case 0x020: if (strobe(pending_strobe_, 0)) clear_frame_count_ = data & 1U; break;
        case 0x024: if (strobe(pending_strobe_, 0)) force_enable_ = data & 1U; break;
        case 0x028:
            if (strobe(pending_strobe_, 1)) qp_override_enable_ = (data >> 8U) & 1U;
            if (strobe(pending_strobe_, 0)) qp_override_ = data & 0x1fU;
            break;
        case 0x02c:
            if (strobe(pending_strobe_, 1)) clock_divider_ = (clock_divider_ & 0xffU) | (data & 0x300U);
            if (strobe(pending_strobe_, 0)) clock_divider_ = (clock_divider_ & 0x300U) | (data & 0xffU);
            break;
        case 0x030: if (strobe(pending_strobe_, 0)) output_mode_ = data & 0x7U; break;
        case 0x034:
            if (strobe(pending_strobe_, 3)) {
                timer_enable_ = (data >> 31U) & 1U;
                timer_autoreload_ = (data >> 30U) & 1U;
                timer_interrupt_enable_ = (data >> 29U) & 1U;
            }
            if (strobe(pending_strobe_, 2)) timer_reload_ = (timer_reload_ & 0x00ffffU) | (data & 0xff0000U);
            if (strobe(pending_strobe_, 1)) timer_reload_ = (timer_reload_ & 0xff00ffU) | (data & 0x00ff00U);
            if (strobe(pending_strobe_, 0)) timer_reload_ = (timer_reload_ & 0xffff00U) | (data & 0x0000ffU);
            break;
        case 0x040: if (strobe(pending_strobe_, 0)) slice_alignment_ = data & 0x7U; break;
        case 0x044: if (strobe(pending_strobe_, 0)) slices_per_line_ = data & 0x1fU; break;
        case 0x048: if (strobe(pending_strobe_, 0)) slices_per_processor_ = data & 0xffU; break;
        case 0x04c: if (strobe(pending_strobe_, 0)) slice_processor_count_ = data & 0xfU; break;
        case 0x050:
            if (strobe(pending_strobe_, 1)) slice_buffer_depth_ = (slice_buffer_depth_ & 0xffU) | (data & 0x3f00U);
            if (strobe(pending_strobe_, 0)) slice_buffer_depth_ = (slice_buffer_depth_ & 0x3f00U) | (data & 0xffU);
            break;
        case 0x060: if (strobe(pending_strobe_, 0)) max_bits_per_group_ = data & 0xffU; break;
        case 0x064: if (strobe(pending_strobe_, 0)) trailing_bits_ = data & 1U; break;
        case 0x068:
            if (strobe(pending_strobe_, 1)) chunk_size_ = (chunk_size_ & 0xffU) | (data & 0xf00U);
            if (strobe(pending_strobe_, 0)) chunk_size_ = (chunk_size_ & 0xf00U) | (data & 0xffU);
            break;
        case 0x080: if (strobe(pending_strobe_, 0)) interrupt_enable_ = data & 0x7fU; break;
        case 0x08c: if (strobe(pending_strobe_, 0)) frame_interrupt_count_ = data & 0xffU; break;
        case 0x100:
            if (strobe(pending_strobe_, 0)) {
                pps_write_ = true;
                pps_wdata_ = data & 0xffU;
            }
            break;
        case 0x108: if (strobe(pending_strobe_, 0)) pps_commit_ = (data & 1U) != 0U; break;
        default: break;
        }
        soft_reset_ = (pending_addr_ & 0xfffU) == 0x000U && (data & 0xfU) == 2U;
    }

    void read_register()
    {
        rdata_ = 0;
        switch (apb_addr.read() & 0xfffU) {
        case 0x000: rdata_ = encode_command_; break;
        case 0x004: rdata_ = (cfg_dsc_encoder_status.read() >> 3U) & 1U; break;
        case 0x008: rdata_ = pixels_per_cycle_; break;
        case 0x010: rdata_ = timeout_count_; break;
        case 0x020: rdata_ = (cfg_dsc_interrupt_status.read() >> 14U) & 0xffU; break;
        case 0x024: rdata_ = force_enable_; break;
        case 0x02c: rdata_ = clock_divider_; break;
        case 0x030: rdata_ = output_mode_; break;
        case 0x040: rdata_ = slice_alignment_; break;
        case 0x044: rdata_ = slices_per_line_; break;
        case 0x048: rdata_ = slices_per_processor_; break;
        case 0x04c: rdata_ = slice_processor_count_; break;
        case 0x050: rdata_ = slice_buffer_depth_; break;
        case 0x060: rdata_ = max_bits_per_group_; break;
        case 0x064: rdata_ = trailing_bits_; break;
        case 0x068: rdata_ = chunk_size_; break;
        case 0x080: rdata_ = interrupt_enable_; interrupt_clear_ = 1; break;
        case 0x084: rdata_ = (cfg_dsc_interrupt_status.read() >> 7U) & 0x7fU; break;
        case 0x088: rdata_ = cfg_dsc_interrupt_status.read() & 0x7fU; break;
        case 0x08c: rdata_ = frame_interrupt_count_; break;
        case 0x0f8: rdata_ = (4096U << 16U) | (1U << 8U) | 4U; break;
        case 0x0fc: rdata_ = 0x00310205U; break;
        case 0x100: rdata_ = apb_pps_rdata.read() & 0xffU; break;
        case 0x104: rdata_ = pps_index_; break;
        default: break;
        }
    }

    void drive_outputs()
    {
        sc_dt::sc_bv<92> config;
        config = 0;
        config.range(91, 91) = follow_vsync_;
        config.range(90, 87) = encode_command_;
        config.range(86, 86) = command_toggle_;
        config.range(85, 78) = timeout_count_;
        config.range(77, 75) = pixels_per_cycle_;
        config.range(74, 72) = slice_alignment_;
        config.range(71, 71) = force_enable_;
        config.range(70, 70) = qp_override_enable_;
        config.range(69, 65) = qp_override_;
        config.range(64, 60) = slices_per_line_;
        config.range(59, 52) = slices_per_processor_;
        config.range(51, 48) = slice_processor_count_;
        config.range(47, 38) = clock_divider_;
        config.range(37, 35) = output_mode_;
        config.range(34, 27) = max_bits_per_group_;
        config.range(26, 26) = trailing_bits_;
        config.range(25, 14) = chunk_size_;
        config.range(13, 0) = slice_buffer_depth_;
        cfg_dsc_encoder.write(config);
        cfg_dsc_interrupt.write((interrupt_enable_ << 10U) | (interrupt_clear_ << 9U)
            | (frame_interrupt_count_ << 1U) | clear_frame_count_);
        cfg_dsc_timers_config.write((timer_autoreload_ << 26U) | (timer_reload_ << 2U)
            | (timer_enable_ << 1U) | timer_interrupt_enable_);
        apb_ready.write(ready_);
        apb_slave_error.write(false);
        apb_rdata.write(rdata_);
        apb_pps_write.write(pps_write_);
        apb_pps_index.write(pps_index_);
        apb_pps_wdata.write(pps_wdata_);
        apb_pps_commit.write(pps_commit_);
        apb_soft_reset.write(soft_reset_);
    }

    void sequence()
    {
        if (!apb_reset_n.read()) {
            reset_state();
            drive_outputs();
            return;
        }

        const bool previous_pps_write = pps_write_;
        const bool transaction_ready = ready_;
        pps_write_ = false;
        pps_commit_ = false;
        soft_reset_ = false;
        interrupt_clear_ = 0;
        clear_frame_count_ = 0;

        if (ready_count_ == 0) {
            ready_ = true;
            const bool read_setup = apb_select.read() && !apb_write.read() && !apb_enable.read();
            const bool write_enable = apb_select.read() && apb_write.read() && apb_enable.read();
            if ((read_setup || write_enable) && ((apb_addr.read() & 0xfffU) == 0x100U)) {
                ready_ = false;
                ready_count_ = 2;
            }
        } else {
            if (ready_count_ == 1)
                ready_ = true;
            --ready_count_;
        }

        if (pending_write_ && pending_addr_ == 0x104U && strobe(pending_strobe_, 0))
            pps_index_ = pending_wdata_ & 0x7fU;
        else if (previous_pps_write)
            pps_index_ = (pps_index_ + 1U) & 0x7fU;

        if (pending_write_)
            apply_write();

        if (apb_select.read() && !apb_write.read())
            read_register();

        // APB acceptance is based on READY sampled at the start of this edge.
        // PPS_DATA also lowers READY on this edge; using the newly computed
        // value here would incorrectly discard every PPS byte transaction.
        pending_write_ = apb_select.read() && apb_enable.read() && apb_write.read()
            && transaction_ready;
        pending_strobe_ = apb_strobe.read() & 0xfU;
        if (apb_select.read()) {
            pending_addr_ = apb_addr.read() & 0xfffU;
            pending_wdata_ = apb_wdata.read();
        }
        drive_outputs();
    }
};
