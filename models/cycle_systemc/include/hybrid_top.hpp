#pragma once

#include <systemc>

#include "Vdsce_command.h"
#include "Vdsce_engine.h"
#include "Vdsce_engine___024root.h"
#include "Vdsce_engine_dsce_slice.h"
#include "Vdsce_interrupt.h"
#include "Vdsce_pps.h"
#include "Vdsce_reset.h"
#include "Vdsce_timers.h"

#include <cstdint>

// UHDM/CIRCT-constrained top-level wiring. ApbModel is replaceable; all other
// blocks remain explicit Verilator-SystemC black boxes in this milestone.
template <typename ApbModel>
struct HybridTop : sc_core::sc_module {
    struct EngineProbe {
        bool pack_valid = false;
        bool pack_ready = false;
        bool pack_line = false;
        std::uint8_t partition_valid = 0;
        std::uint8_t partition_last = 0;
        std::uint8_t slice_input_ready = 0;
        std::uint8_t csc_valid = 0;
        std::uint8_t csc_last = 0;
        std::uint8_t slice_buffer_valid = 0;
        std::uint8_t slice_buffer_last = 0;
        std::uint8_t flatness_valid = 0;
        std::uint8_t flatness_last = 0;
        std::uint8_t predict_valid = 0;
        std::uint8_t predict_last = 0;
        // Words emitted by the three dsce_muxword instances into the stream
        // builder (3-bit one-hot per substream, format-internal wire).
        std::uint8_t fmt_muxword_valid = 0;
        std::uint8_t slice_output_valid = 0;
        std::uint8_t slice_output_ready = 0;
        std::uint8_t slice_output_last = 0;
        bool mux_valid = false;
        bool mux_ready = false;
        bool mux_line = false;
        bool mux_frame = false;
    };

    sc_core::sc_in<bool> apb_clk{"apb_clk"};
    sc_core::sc_in<bool> apb_select{"apb_select"};
    sc_core::sc_in<bool> apb_enable{"apb_enable"};
    sc_core::sc_in<bool> apb_write{"apb_write"};
    sc_core::sc_in<std::uint32_t> apb_strobe{"apb_strobe"};
    sc_core::sc_in<std::uint32_t> apb_protect{"apb_protect"};
    sc_core::sc_in<std::uint32_t> apb_addr{"apb_addr"};
    sc_core::sc_in<std::uint32_t> apb_wdata{"apb_wdata"};
    sc_core::sc_out<bool> apb_ready{"apb_ready"};
    sc_core::sc_out<bool> apb_slave_error{"apb_slave_error"};
    sc_core::sc_out<bool> apb_int{"apb_int"};
    sc_core::sc_out<std::uint32_t> apb_rdata{"apb_rdata"};
    sc_core::sc_in<bool> dsc_clk{"dsc_clk"};
    sc_core::sc_in<bool> async_reset_n{"async_reset_n"};
    sc_core::sc_in<bool> async_test_mode{"async_test_mode"};
    sc_core::sc_in<bool> axi_clk{"axi_clk"};
    sc_core::sc_in<bool> axi_tvalid_in{"axi_tvalid_in"};
    sc_core::sc_out<bool> axi_tready_in{"axi_tready_in"};
    sc_core::sc_in<bool> axi_tline_in{"axi_tline_in"};
    sc_core::sc_in<bool> axi_tframe_in{"axi_tframe_in"};
    sc_core::sc_in<sc_dt::sc_bv<192>> axi_tdata_in{"axi_tdata_in"};
    sc_core::sc_out<bool> axi_tvalid_out{"axi_tvalid_out"};
    sc_core::sc_in<bool> axi_tready_out{"axi_tready_out"};
    sc_core::sc_out<bool> axi_tline_out{"axi_tline_out"};
    sc_core::sc_out<bool> axi_tframe_out{"axi_tframe_out"};
    sc_core::sc_out<sc_dt::sc_bv<192>> axi_tdata_out{"axi_tdata_out"};

    ApbModel* apb = nullptr;
    Vdsce_command* command = nullptr;
    Vdsce_engine* engine = nullptr;
    Vdsce_interrupt* interrupt = nullptr;
    Vdsce_pps* pps = nullptr;
    Vdsce_reset* reset = nullptr;
    Vdsce_timers* timers = nullptr;

    SC_HAS_PROCESS(HybridTop);
    explicit HybridTop(sc_core::sc_module_name name) : sc_core::sc_module(name)
    {
        SC_METHOD(update_bypass);
        sensitive << cfg_encoder_status_;

        apb = new ApbModel("dsce_apb_inst");
        apb->apb_clk(apb_clk);
        apb->apb_reset_n(apb_reset_n_);
        apb->apb_select(apb_select);
        apb->apb_enable(apb_enable);
        apb->apb_write(apb_write);
        apb->apb_strobe(apb_strobe);
        apb->apb_protect(apb_protect);
        apb->apb_addr(apb_addr);
        apb->apb_wdata(apb_wdata);
        apb->apb_ready(apb_ready);
        apb->apb_slave_error(apb_slave_error);
        apb->apb_rdata(apb_rdata);
        apb->apb_pps_write(apb_pps_write_);
        apb->apb_pps_index(apb_pps_index_);
        apb->apb_pps_wdata(apb_pps_wdata_);
        apb->apb_pps_commit(apb_pps_commit_);
        apb->apb_pps_rdata(apb_pps_rdata_);
        apb->cfg_dsc_encoder(cfg_encoder_);
        apb->cfg_dsc_encoder_status(cfg_encoder_status_);
        apb->cfg_dsc_interrupt(cfg_interrupt_);
        apb->cfg_dsc_interrupt_status(cfg_interrupt_status_);
        apb->cfg_dsc_timers_config(cfg_timers_);
        apb->cfg_dsc_timers_status(cfg_timers_status_);
        apb->apb_soft_reset(apb_soft_reset_);

        command = new Vdsce_command("dsce_command_inst");
        command->axi_clk(axi_clk);
        command->axi_reset_n(axi_reset_n_);
        command->dsc_clk(dsc_clk);
        command->dsc_reset_n(dsc_reset_n_);
        command->axi_tframe_in(axi_tframe_in);
        command->cfg_dsc_encoder(cfg_encoder_);
        command->axi_pps_refresh(axi_pps_refresh_);
        command->axi_pps_refresh_complete(axi_pps_refresh_complete_);
        command->cfg_dsc_encoder_status(cfg_encoder_status_);
        command->apb_one_usec_tick(apb_timer_tick_);
        command->axi_encoder_enable(axi_encoder_enable_);
        command->axi_pps_update(axi_pps_update_);
        command->axi_new_frame(axi_new_frame_);
        command->dsc_encoder_enable(dsc_encoder_enable_);
        command->dsc_pps_update(dsc_pps_update_);
        command->dsc_new_frame(dsc_new_frame_);

        engine = new Vdsce_engine("dsce_engine_inst");
        engine->dsc_clk(dsc_clk);
        engine->dsc_reset_n(dsc_reset_n_);
        engine->dsc_encoder_enable(dsc_encoder_enable_);
        engine->cfg_bypass_enable(bypass_enable_);
        for (unsigned i = 0; i < 4; ++i)
            engine->cfg_dsc_slice_status[i](slice_status_[i]);
        engine->apb_clk(apb_clk);
        engine->apb_reset_n(apb_reset_n_);
        engine->cfg_dsc_encoder(cfg_encoder_);
        engine->axi_encoder_enable(axi_encoder_enable_);
        engine->axi_pps_update(axi_pps_update_);
        engine->dsc_pps_update(dsc_pps_update_);
        engine->axi_new_frame(axi_new_frame_);
        engine->dsc_new_frame(dsc_new_frame_);
        engine->cfg_pps(cfg_pps_);
        engine->cfg_rcps(cfg_rcps_);
        engine->axi_clk(axi_clk);
        engine->axi_reset_n(axi_reset_n_);
        engine->axi_tvalid_in(axi_tvalid_in);
        engine->axi_tready_in(axi_tready_in);
        engine->axi_tline_in(axi_tline_in);
        engine->axi_tframe_in(axi_tframe_in);
        engine->axi_tdata_in(axi_tdata_in);
        engine->axi_tvalid_out(axi_tvalid_out);
        engine->axi_tready_out(axi_tready_out);
        engine->axi_tline_out(axi_tline_out);
        engine->axi_tframe_out(axi_tframe_out);
        engine->axi_tdata_out(axi_tdata_out);
        for (unsigned i = 0; i < 16; ++i) {
            engine_bist_in_[i].write(0);
            engine->bist_sram_in[i](engine_bist_in_[i]);
            engine->bist_sram_out[i](engine_bist_out_[i]);
        }

        interrupt = new Vdsce_interrupt("dsce_interrupt_inst");
        interrupt->apb_clk(apb_clk);
        interrupt->apb_reset_n(apb_reset_n_);
        interrupt->cfg_dsc_interrupt(cfg_interrupt_);
        interrupt->cfg_dsc_interrupt_status(cfg_interrupt_status_);
        interrupt->cfg_dsc_encoder_status(cfg_encoder_status_);
        for (unsigned i = 0; i < 4; ++i)
            interrupt->cfg_dsc_slice_status[i](slice_status_[i]);
        interrupt->cfg_dsc_timers_status(cfg_timers_status_);
        interrupt->apb_int(apb_int);

        pps = new Vdsce_pps("dsce_pps_inst");
        pps->apb_clk(apb_clk);
        pps->apb_reset_n(apb_reset_n_);
        pps->apb_pps_write(apb_pps_write_);
        pps->apb_pps_index(apb_pps_index_);
        pps->apb_pps_wdata(apb_pps_wdata_);
        pps->apb_pps_commit(apb_pps_commit_);
        pps->apb_pps_rdata(apb_pps_rdata_);
        pps->axi_clk(axi_clk);
        pps->axi_reset_n(axi_reset_n_);
        pps->axi_pps_refresh(axi_pps_refresh_);
        pps->axi_pps_refresh_complete(axi_pps_refresh_complete_);
        pps->cfg_pps(cfg_pps_);
        pps->cfg_rcps(cfg_rcps_);
        for (unsigned i = 0; i < 2; ++i) {
            pps_bist_in_[i].write(0);
            pps->bist_sram_in[i](pps_bist_in_[i]);
            pps->bist_sram_out[i](pps_bist_out_[i]);
        }

        reset = new Vdsce_reset("dsce_reset_inst");
        reset->apb_clk(apb_clk);
        reset->axi_clk(axi_clk);
        reset->dsc_clk(dsc_clk);
        reset->async_reset_n(async_reset_n);
        reset->apb_soft_reset(apb_soft_reset_);
        reset->async_test_mode(async_test_mode);
        reset->apb_reset_n(apb_reset_n_);
        reset->axi_reset_n(axi_reset_n_);
        reset->dsc_reset_n(dsc_reset_n_);

        timers = new Vdsce_timers("dsce_timers_inst");
        timers->apb_clk(apb_clk);
        timers->apb_reset_n(apb_reset_n_);
        timers->apb_timer_tick(apb_timer_tick_);
        timers->cfg_dsc_timers_config(cfg_timers_);
        timers->cfg_dsc_timers_status(cfg_timers_status_);
    }

    ~HybridTop() override
    {
        delete apb;
        delete command;
        delete engine;
        delete interrupt;
        delete pps;
        delete reset;
        delete timers;
    }

    std::uint32_t encoder_status() const { return cfg_encoder_status_.read(); }
    std::uint32_t encoder_command() const
    {
        return cfg_encoder_.read().range(90, 87).to_uint();
    }
    bool command_toggle() const { return cfg_encoder_.read()[86].to_bool(); }
    bool apb_reset_released() const { return apb_reset_n_.read(); }
    bool bypass_enabled() const { return bypass_enable_.read(); }
    bool axi_encoder_enabled() const { return axi_encoder_enable_.read(); }
    bool dsc_encoder_enabled() const { return dsc_encoder_enable_.read(); }
    bool pps_refresh_pending() const { return axi_pps_refresh_.read(); }
    bool pps_update_pending() const { return axi_pps_update_.read(); }
    bool new_frame_pending() const { return axi_new_frame_.read(); }
    sc_dt::sc_bv<296> pps_config() const { return cfg_pps_.read(); }
    EngineProbe engine_probe() const
    {
        EngineProbe probe;
        const auto* root = engine->rootp;
        probe.pack_valid = root->dsce_engine__DOT__i_valid_pack;
        probe.pack_ready = root->dsce_engine__DOT__i_ready_pack;
        probe.pack_line = root->dsce_engine__DOT__i_line_pack;
        probe.partition_valid = root->dsce_engine__DOT__i_valid_part;
        probe.partition_last = root->dsce_engine__DOT__i_last_part;
        probe.slice_output_valid = root->dsce_engine__DOT__i_axi_ready;
        probe.slice_output_ready = root->dsce_engine__DOT__i_axi_accept;
        probe.mux_valid = root->dsce_engine__DOT__i_axi_tvalid_mux;
        probe.mux_ready = root->dsce_engine__DOT__dsce_slice_mux_inst__DOT__i_ready_in;
        probe.mux_line = root->dsce_engine__DOT__i_axi_tline_mux;
        probe.mux_frame = root->dsce_engine__DOT__i_axi_tframe_mux;
        const Vdsce_engine_dsce_slice* slices[4] = {
            root->__PVT__dsce_engine__DOT__gen_slice__BRA__0__KET____DOT__dsce_slice_inst,
            root->__PVT__dsce_engine__DOT__gen_slice__BRA__1__KET____DOT__dsce_slice_inst,
            root->__PVT__dsce_engine__DOT__gen_slice__BRA__2__KET____DOT__dsce_slice_inst,
            root->__PVT__dsce_engine__DOT__gen_slice__BRA__3__KET____DOT__dsce_slice_inst};
        for (unsigned index = 0; index < 4; ++index) {
            probe.slice_input_ready |= static_cast<std::uint8_t>(slices[index]->axi_ready_in) << index;
            probe.slice_output_last |= static_cast<std::uint8_t>(slices[index]->axi_last_out) << index;
            probe.csc_valid |= static_cast<std::uint8_t>(slices[index]->i_valid_csc) << index;
            probe.csc_last |= static_cast<std::uint8_t>(slices[index]->i_last_csc) << index;
            probe.slice_buffer_valid |= static_cast<std::uint8_t>(slices[index]->i_valid_slb) << index;
            probe.slice_buffer_last |= static_cast<std::uint8_t>(slices[index]->i_last_slb) << index;
            probe.flatness_valid |= static_cast<std::uint8_t>(slices[index]->i_valid_fd) << index;
            probe.flatness_last |= static_cast<std::uint8_t>(slices[index]->i_last_fd) << index;
            probe.predict_valid |= static_cast<std::uint8_t>(slices[index]->i_valid_pd) << index;
            probe.predict_last |= static_cast<std::uint8_t>(slices[index]->i_last_pd) << index;
            // Words from the three muxword instances into the stream builder
            // (flattened public signal inside dsce_format_inst).
            probe.fmt_muxword_valid |=
                static_cast<std::uint8_t>(slices[index]->dsce_format_inst__DOT__i_valid_mw);
        }
        return probe;
    }

private:
    sc_core::sc_signal<bool> apb_reset_n_{"apb_reset_n_internal"};
    sc_core::sc_signal<bool> axi_reset_n_{"axi_reset_n_internal"};
    sc_core::sc_signal<bool> dsc_reset_n_{"dsc_reset_n_internal"};
    sc_core::sc_signal<bool> apb_soft_reset_{"apb_soft_reset_internal"};
    sc_core::sc_signal<bool> apb_pps_write_{"apb_pps_write_internal"};
    sc_core::sc_signal<bool> apb_pps_commit_{"apb_pps_commit_internal"};
    sc_core::sc_signal<std::uint32_t> apb_pps_index_{"apb_pps_index_internal"};
    sc_core::sc_signal<std::uint32_t> apb_pps_wdata_{"apb_pps_wdata_internal"};
    sc_core::sc_signal<std::uint32_t> apb_pps_rdata_{"apb_pps_rdata_internal"};
    sc_core::sc_signal<sc_dt::sc_bv<92>> cfg_encoder_{"cfg_encoder"};
    sc_core::sc_signal<std::uint32_t> cfg_encoder_status_{"cfg_encoder_status"};
    sc_core::sc_signal<std::uint32_t> cfg_interrupt_{"cfg_interrupt"};
    sc_core::sc_signal<std::uint32_t> cfg_interrupt_status_{"cfg_interrupt_status"};
    sc_core::sc_signal<std::uint32_t> cfg_timers_{"cfg_timers"};
    sc_core::sc_signal<std::uint32_t> cfg_timers_status_{"cfg_timers_status"};
    sc_core::sc_signal<bool> apb_timer_tick_{"apb_timer_tick"};
    sc_core::sc_signal<bool> axi_pps_refresh_{"axi_pps_refresh"};
    sc_core::sc_signal<bool> axi_pps_refresh_complete_{"axi_pps_refresh_complete"};
    sc_core::sc_signal<bool> axi_encoder_enable_{"axi_encoder_enable"};
    sc_core::sc_signal<bool> axi_pps_update_{"axi_pps_update"};
    sc_core::sc_signal<bool> axi_new_frame_{"axi_new_frame"};
    sc_core::sc_signal<bool> dsc_encoder_enable_{"dsc_encoder_enable"};
    sc_core::sc_signal<bool> dsc_pps_update_{"dsc_pps_update"};
    sc_core::sc_signal<bool> dsc_new_frame_{"dsc_new_frame"};
    sc_core::sc_signal<bool> bypass_enable_{"bypass_enable"};
    sc_core::sc_signal<bool> slice_status_[4];
    sc_core::sc_signal<std::uint32_t> engine_bist_in_[16];
    sc_core::sc_signal<std::uint32_t> engine_bist_out_[16];
    sc_core::sc_signal<std::uint32_t> pps_bist_in_[2];
    sc_core::sc_signal<std::uint32_t> pps_bist_out_[2];
    sc_core::sc_signal<sc_dt::sc_bv<296>> cfg_pps_{"cfg_pps"};
    sc_core::sc_signal<sc_dt::sc_bv<400>> cfg_rcps_{"cfg_rcps"};

    void update_bypass()
    {
        bypass_enable_.write(((cfg_encoder_status_.read() >> 3U) & 1U) == 0U);
    }
};
