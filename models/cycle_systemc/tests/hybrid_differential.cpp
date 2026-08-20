#include "Vdsc_encoder.h"
#include "Vdsce_apb.h"
#include "cycle_apb.hpp"
#include "hybrid_top.hpp"

#include <systemc>

#include <algorithm>
#include <array>
#include <cctype>
#include <cstdint>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <iterator>
#include <limits>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

namespace {

struct Image {
    unsigned width = 0;
    unsigned height = 0;
    std::vector<std::uint8_t> rgb;
};

struct Outputs {
    sc_core::sc_signal<bool> apb_ready;
    sc_core::sc_signal<bool> apb_error;
    sc_core::sc_signal<bool> apb_int;
    sc_core::sc_signal<std::uint32_t> apb_rdata;
    sc_core::sc_signal<bool> axi_ready;
    sc_core::sc_signal<bool> axi_valid;
    sc_core::sc_signal<bool> axi_line;
    sc_core::sc_signal<bool> axi_frame;
    sc_core::sc_signal<sc_dt::sc_bv<192>> axi_data;
};

struct FirstDifference {
    bool present = false;
    std::uint64_t cycle = 0;
    std::string phase;
    std::string signal;
    std::string reference;
    std::string candidate;
};

struct EngineBoundaryCounts {
    std::uint64_t input_accept = 0;
    std::uint64_t pack_accept = 0;
    std::array<std::uint64_t, 4> partition_accept{};
    std::array<std::uint64_t, 4> partition_last{};
    std::array<std::uint64_t, 4> csc_accept{};
    std::array<std::uint64_t, 4> csc_last{};
    std::array<std::uint64_t, 4> slice_buffer_valid{};
    std::array<std::uint64_t, 4> slice_buffer_last{};
    std::array<std::uint64_t, 4> flatness_valid{};
    std::array<std::uint64_t, 4> flatness_last{};
    std::array<std::uint64_t, 4> predict_valid{};
    std::array<std::uint64_t, 4> predict_last{};
    std::uint64_t fmt_muxword_words = 0;
    std::uint64_t fmt_vlc_last_pulses = 0;
    std::uint64_t muxword_complete_pulses = 0;
    std::uint64_t muxword_complete_edges = 0;
    std::uint64_t muxword_complete_aligned = 0;
    std::uint8_t prev_muxword_complete = 0;
    std::array<std::uint64_t, 4> slice_output_accept{};
    std::array<std::uint64_t, 4> slice_output_last{};
    std::uint64_t mux_accept = 0;
    std::uint64_t mux_line = 0;
    std::uint64_t mux_frame = 0;
    std::uint64_t top_accept = 0;
};

std::string token(std::istream& input)
{
    std::string result;
    char character = 0;
    while (input.get(character)) {
        if (character == '#') {
            input.ignore(std::numeric_limits<std::streamsize>::max(), '\n');
            continue;
        }
        if (!std::isspace(static_cast<unsigned char>(character))) {
            result.push_back(character);
            break;
        }
    }
    while (input.get(character)) {
        if (std::isspace(static_cast<unsigned char>(character)))
            break;
        result.push_back(character);
    }
    return result;
}

Image read_ppm(const std::string& path)
{
    std::ifstream input(path, std::ios::binary);
    if (!input || token(input) != "P6")
        throw std::runtime_error("invalid P6 PPM input");
    Image image;
    image.width = static_cast<unsigned>(std::stoul(token(input)));
    image.height = static_cast<unsigned>(std::stoul(token(input)));
    if (token(input) != "255" || image.width == 0 || image.height == 0)
        throw std::runtime_error("unsupported PPM dimensions or bit depth");
    image.rgb.resize(static_cast<std::size_t>(image.width) * image.height * 3U);
    input.read(reinterpret_cast<char*>(image.rgb.data()), static_cast<std::streamsize>(image.rgb.size()));
    if (input.gcount() != static_cast<std::streamsize>(image.rgb.size()))
        throw std::runtime_error("truncated PPM input");
    return image;
}

std::vector<std::uint8_t> read_file(const std::string& path)
{
    std::ifstream input(path, std::ios::binary);
    if (!input)
        throw std::runtime_error("cannot read binary input: " + path);
    return {std::istreambuf_iterator<char>(input), std::istreambuf_iterator<char>()};
}

void write_file(const std::string& path, const std::vector<std::uint8_t>& bytes)
{
    std::ofstream output(path, std::ios::binary);
    if (!output)
        throw std::runtime_error("cannot write output: " + path);
    output.write(reinterpret_cast<const char*>(bytes.data()), static_cast<std::streamsize>(bytes.size()));
}

std::string json_escape(const std::string& value)
{
    std::ostringstream output;
    for (const char character : value) {
        switch (character) {
        case '\\': output << "\\\\"; break;
        case '"': output << "\\\""; break;
        case '\n': output << "\\n"; break;
        default: output << character; break;
        }
    }
    return output.str();
}

std::string bool_text(bool value) { return value ? "1" : "0"; }

std::string bv_text(const sc_dt::sc_bv<192>& value)
{
    return value.to_string(sc_dt::SC_HEX, false);
}

std::array<std::uint8_t, 24> bytes_of(const sc_dt::sc_bv<192>& value)
{
    std::array<std::uint8_t, 24> result{};
    for (unsigned byte = 0; byte < result.size(); ++byte) {
        for (unsigned bit = 0; bit < 8; ++bit) {
            if (value[byte * 8U + bit].to_bool())
                result[byte] |= static_cast<std::uint8_t>(1U << bit);
        }
    }
    return result;
}

sc_dt::sc_bv<192> pixel_beat(const Image& image, std::size_t first_pixel)
{
    sc_dt::sc_bv<192> result;
    result = 0;
    const auto pixels = static_cast<std::size_t>(image.width) * image.height;
    for (unsigned lane = 0; lane < 4 && first_pixel + lane < pixels; ++lane) {
        const auto source = (first_pixel + lane) * 3U;
        const std::array<std::uint16_t, 3> components{
            static_cast<std::uint16_t>(image.rgb[source + 2]) << 8U,
            static_cast<std::uint16_t>(image.rgb[source + 1]) << 8U,
            static_cast<std::uint16_t>(image.rgb[source]) << 8U};
        for (unsigned component = 0; component < components.size(); ++component) {
            const auto low = lane * 48U + component * 16U;
            result.range(low + 15U, low) = components[component];
        }
    }
    return result;
}

template <typename Model>
void bind_top(Model& model, sc_core::sc_signal<bool>& apb_clk,
    sc_core::sc_signal<bool>& apb_select, sc_core::sc_signal<bool>& apb_enable,
    sc_core::sc_signal<bool>& apb_write, sc_core::sc_signal<std::uint32_t>& apb_strobe,
    sc_core::sc_signal<std::uint32_t>& apb_protect, sc_core::sc_signal<std::uint32_t>& apb_addr,
    sc_core::sc_signal<std::uint32_t>& apb_wdata, sc_core::sc_signal<bool>& dsc_clk,
    sc_core::sc_signal<bool>& reset_n, sc_core::sc_signal<bool>& test_mode,
    sc_core::sc_signal<bool>& axi_clk, sc_core::sc_signal<bool>& axi_valid,
    sc_core::sc_signal<bool>& axi_line, sc_core::sc_signal<bool>& axi_frame,
    sc_core::sc_signal<sc_dt::sc_bv<192>>& axi_data, sc_core::sc_signal<bool>& axi_output_ready,
    Outputs& outputs)
{
    model.apb_clk(apb_clk);
    model.apb_select(apb_select);
    model.apb_enable(apb_enable);
    model.apb_write(apb_write);
    model.apb_strobe(apb_strobe);
    model.apb_protect(apb_protect);
    model.apb_addr(apb_addr);
    model.apb_wdata(apb_wdata);
    model.apb_ready(outputs.apb_ready);
    model.apb_slave_error(outputs.apb_error);
    model.apb_int(outputs.apb_int);
    model.apb_rdata(outputs.apb_rdata);
    model.dsc_clk(dsc_clk);
    model.async_reset_n(reset_n);
    model.async_test_mode(test_mode);
    model.axi_clk(axi_clk);
    model.axi_tvalid_in(axi_valid);
    model.axi_tready_in(outputs.axi_ready);
    model.axi_tline_in(axi_line);
    model.axi_tframe_in(axi_frame);
    model.axi_tdata_in(axi_data);
    model.axi_tvalid_out(outputs.axi_valid);
    model.axi_tready_out(axi_output_ready);
    model.axi_tline_out(outputs.axi_line);
    model.axi_tframe_out(outputs.axi_frame);
    model.axi_tdata_out(outputs.axi_data);
}

void compare_signal(FirstDifference& difference, std::uint64_t cycle, const std::string& phase,
    const std::string& name, const std::string& reference, const std::string& candidate)
{
    if (!difference.present && reference != candidate) {
        difference.present = true;
        difference.cycle = cycle;
        difference.phase = phase;
        difference.signal = name;
        difference.reference = reference;
        difference.candidate = candidate;
    }
}

void compare_outputs(FirstDifference& difference, std::uint64_t cycle, const std::string& phase,
    const Outputs& reference, const Outputs& candidate)
{
    compare_signal(difference, cycle, phase, "apb_ready", bool_text(reference.apb_ready.read()), bool_text(candidate.apb_ready.read()));
    compare_signal(difference, cycle, phase, "apb_slave_error", bool_text(reference.apb_error.read()), bool_text(candidate.apb_error.read()));
    compare_signal(difference, cycle, phase, "apb_int", bool_text(reference.apb_int.read()), bool_text(candidate.apb_int.read()));
    compare_signal(difference, cycle, phase, "apb_rdata", std::to_string(reference.apb_rdata.read()), std::to_string(candidate.apb_rdata.read()));
    compare_signal(difference, cycle, phase, "axi_tready_in", bool_text(reference.axi_ready.read()), bool_text(candidate.axi_ready.read()));
    compare_signal(difference, cycle, phase, "axi_tvalid_out", bool_text(reference.axi_valid.read()), bool_text(candidate.axi_valid.read()));
    compare_signal(difference, cycle, phase, "axi_tline_out", bool_text(reference.axi_line.read()), bool_text(candidate.axi_line.read()));
    compare_signal(difference, cycle, phase, "axi_tframe_out", bool_text(reference.axi_frame.read()), bool_text(candidate.axi_frame.read()));
    compare_signal(difference, cycle, phase, "axi_tdata_out", bv_text(reference.axi_data.read()), bv_text(candidate.axi_data.read()));
}

struct Simulation {
    sc_core::sc_signal<bool> apb_clk{"apb_clk"};
    sc_core::sc_signal<bool> apb_select{"apb_select"};
    sc_core::sc_signal<bool> apb_enable{"apb_enable"};
    sc_core::sc_signal<bool> apb_write{"apb_write"};
    sc_core::sc_signal<std::uint32_t> apb_strobe{"apb_strobe"};
    sc_core::sc_signal<std::uint32_t> apb_protect{"apb_protect"};
    sc_core::sc_signal<std::uint32_t> apb_addr{"apb_addr"};
    sc_core::sc_signal<std::uint32_t> apb_wdata{"apb_wdata"};
    sc_core::sc_signal<bool> dsc_clk{"dsc_clk"};
    sc_core::sc_signal<bool> reset_n{"reset_n"};
    sc_core::sc_signal<bool> test_mode{"test_mode"};
    sc_core::sc_signal<bool> axi_clk{"axi_clk"};
    sc_core::sc_signal<bool> axi_valid{"axi_valid"};
    sc_core::sc_signal<bool> axi_line{"axi_line"};
    sc_core::sc_signal<bool> axi_frame{"axi_frame"};
    sc_core::sc_signal<sc_dt::sc_bv<192>> axi_data{"axi_data"};
    sc_core::sc_signal<bool> axi_output_ready{"axi_output_ready"};

    Outputs monolithic;
    Outputs split;
    Outputs replaced;
    Vdsc_encoder reference{"rtl_monolithic"};
    HybridTop<Vdsce_apb> split_top{"rtl_split"};
    HybridTop<CycleApb> replaced_top{"cycle_apb_replaced"};
    sc_core::sc_signal<std::uint32_t> bist_in[18];
    sc_core::sc_signal<std::uint32_t> bist_out[18];

    std::uint64_t cycles = 0;
    std::uint64_t dsc_cycles = 0;
    unsigned dsc_clock_numerator = 1;
    unsigned dsc_clock_denominator = 1;
    unsigned dsc_clock_accumulator = 0;
    FirstDifference split_difference;
    FirstDifference replacement_difference;
    std::vector<std::uint8_t> reference_bytes;
    std::vector<std::uint8_t> split_bytes;
    std::vector<std::uint8_t> replaced_bytes;
    std::uint64_t reference_line_markers = 0;
    std::uint64_t reference_frame_markers = 0;
    std::ofstream interface_trace;
    std::ofstream engine_trace;
    std::ofstream engine_dsc_trace;
    std::string last_trace_key;
    EngineBoundaryCounts engine_counts;

    Simulation(const std::string& trace_path, const std::string& engine_trace_path,
        const std::string& engine_dsc_trace_path,
        unsigned clock_numerator, unsigned clock_denominator)
        : dsc_clock_numerator(clock_numerator), dsc_clock_denominator(clock_denominator),
          interface_trace(trace_path), engine_trace(engine_trace_path), engine_dsc_trace(engine_dsc_trace_path)
    {
        if (!interface_trace || !engine_trace || !engine_dsc_trace
            || dsc_clock_numerator == 0 || dsc_clock_denominator == 0)
            throw std::runtime_error("cannot initialize traces or DSC clock ratio");
        interface_trace << "cycle,phase,split_status,split_bypass,split_axi_enable,split_dsc_enable,"
                           "hybrid_status,hybrid_bypass,hybrid_axi_enable,hybrid_dsc_enable,"
                           "input_ready,output_valid,output_line,output_frame,output_data\n";
        engine_trace << "axi_cycle,phase,input_valid,input_ready,pack_valid,pack_ready,pack_line,"
                        "partition_valid,partition_last,slice_input_ready,slice_output_valid,"
                        "slice_output_ready,slice_output_last,mux_valid,mux_ready,mux_line,mux_frame,"
                        "top_valid,top_ready,top_line,top_frame\n";
        engine_dsc_trace << "dsc_cycle,axi_cycle,phase,slice_buffer_valid,slice_buffer_last,"
                            "flatness_valid,flatness_last,predict_valid,predict_last\n";
        bind_top(reference, apb_clk, apb_select, apb_enable, apb_write, apb_strobe,
            apb_protect, apb_addr, apb_wdata, dsc_clk, reset_n, test_mode, axi_clk,
            axi_valid, axi_line, axi_frame, axi_data, axi_output_ready, monolithic);
        bind_top(split_top, apb_clk, apb_select, apb_enable, apb_write, apb_strobe,
            apb_protect, apb_addr, apb_wdata, dsc_clk, reset_n, test_mode, axi_clk,
            axi_valid, axi_line, axi_frame, axi_data, axi_output_ready, split);
        bind_top(replaced_top, apb_clk, apb_select, apb_enable, apb_write, apb_strobe,
            apb_protect, apb_addr, apb_wdata, dsc_clk, reset_n, test_mode, axi_clk,
            axi_valid, axi_line, axi_frame, axi_data, axi_output_ready, replaced);
        for (unsigned i = 0; i < 18; ++i) {
            bist_in[i].write(0);
            reference.bist_sram_in[i](bist_in[i]);
            reference.bist_sram_out[i](bist_out[i]);
        }
    }

    void record_engine_boundary(const std::string& phase)
    {
        const auto probe = split_top.engine_probe();
        if (axi_valid.read() && split.axi_ready.read())
            ++engine_counts.input_accept;
        if (probe.pack_valid && probe.pack_ready)
            ++engine_counts.pack_accept;
        for (unsigned index = 0; index < 4; ++index) {
            const auto mask = static_cast<std::uint8_t>(1U << index);
            if ((probe.partition_valid & mask) && (probe.slice_input_ready & mask))
                ++engine_counts.partition_accept[index];
            if ((probe.partition_valid & mask) && (probe.slice_input_ready & mask)
                && (probe.partition_last & mask))
                ++engine_counts.partition_last[index];
            if ((probe.csc_valid & mask) && (probe.slice_input_ready & mask))
                ++engine_counts.csc_accept[index];
            if ((probe.csc_valid & mask) && (probe.slice_input_ready & mask) && (probe.csc_last & mask))
                ++engine_counts.csc_last[index];
            if ((probe.slice_output_valid & mask) && (probe.slice_output_ready & mask))
                ++engine_counts.slice_output_accept[index];
            if ((probe.slice_output_valid & mask) && (probe.slice_output_ready & mask)
                && (probe.slice_output_last & mask))
                ++engine_counts.slice_output_last[index];
        }
        if (probe.mux_valid && probe.mux_ready)
            ++engine_counts.mux_accept;
        if (probe.mux_line)
            ++engine_counts.mux_line;
        if (probe.mux_frame)
            ++engine_counts.mux_frame;
        if (split.axi_valid.read() && axi_output_ready.read())
            ++engine_counts.top_accept;

        const auto active = (axi_valid.read() && split.axi_ready.read())
            || (probe.pack_valid && probe.pack_ready)
            || (probe.partition_valid & probe.slice_input_ready) || probe.partition_last
            || (probe.slice_output_valid & probe.slice_output_ready) || probe.slice_output_last
            || (probe.mux_valid && probe.mux_ready) || probe.mux_line || probe.mux_frame
            || (split.axi_valid.read() && axi_output_ready.read())
            || split.axi_line.read() || split.axi_frame.read();
        if (active) {
            engine_trace << cycles << ',' << phase << ',' << axi_valid.read() << ','
                         << split.axi_ready.read() << ',' << probe.pack_valid << ','
                         << probe.pack_ready << ',' << probe.pack_line << ','
                         << static_cast<unsigned>(probe.partition_valid) << ','
                         << static_cast<unsigned>(probe.partition_last) << ','
                         << static_cast<unsigned>(probe.slice_input_ready) << ','
                         << static_cast<unsigned>(probe.slice_output_valid) << ','
                         << static_cast<unsigned>(probe.slice_output_ready) << ','
                         << static_cast<unsigned>(probe.slice_output_last) << ','
                         << probe.mux_valid << ',' << probe.mux_ready << ',' << probe.mux_line << ',' << probe.mux_frame << ','
                         << split.axi_valid.read() << ',' << axi_output_ready.read() << ','
                         << split.axi_line.read() << ',' << split.axi_frame.read() << '\n';
        }
    }

    void record_dsc_boundary(const std::string& phase)
    {
        const auto probe = split_top.engine_probe();
        for (unsigned index = 0; index < 4; ++index) {
            const auto mask = static_cast<std::uint8_t>(1U << index);
            if (probe.slice_buffer_valid & mask) ++engine_counts.slice_buffer_valid[index];
            if ((probe.slice_buffer_valid & mask) && (probe.slice_buffer_last & mask))
                ++engine_counts.slice_buffer_last[index];
            if (probe.flatness_valid & mask) ++engine_counts.flatness_valid[index];
            if ((probe.flatness_valid & mask) && (probe.flatness_last & mask))
                ++engine_counts.flatness_last[index];
            if (probe.predict_valid & mask) ++engine_counts.predict_valid[index];
            if ((probe.predict_valid & mask) && (probe.predict_last & mask))
                ++engine_counts.predict_last[index];
        }
        // Count the muxword-to-builder words across the three substreams.
        for (unsigned bit = 0; bit < 3; ++bit) {
            if ((probe.fmt_muxword_valid >> bit) & 1U)
                ++engine_counts.fmt_muxword_words;
            if ((probe.fmt_vlc_last >> bit) & 1U)
                ++engine_counts.fmt_vlc_last_pulses;
            if ((probe.muxword_complete >> bit) & 1U)
                ++engine_counts.muxword_complete_pulses;
            auto rising = static_cast<unsigned>(
                (probe.muxword_complete & ~engine_counts.prev_muxword_complete) >> bit) & 1U;
            engine_counts.muxword_complete_edges += rising;
            auto aligned = static_cast<unsigned>(
                (probe.muxword_complete & probe.fmt_muxword_valid) >> bit) & 1U;
            engine_counts.muxword_complete_aligned += aligned;
        }
        engine_counts.prev_muxword_complete = probe.muxword_complete;
        if (probe.slice_buffer_valid || probe.slice_buffer_last || probe.flatness_valid
            || probe.flatness_last || probe.predict_valid || probe.predict_last) {
            engine_dsc_trace << dsc_cycles << ',' << cycles << ',' << phase << ','
                             << static_cast<unsigned>(probe.slice_buffer_valid) << ','
                             << static_cast<unsigned>(probe.slice_buffer_last) << ','
                             << static_cast<unsigned>(probe.flatness_valid) << ','
                             << static_cast<unsigned>(probe.flatness_last) << ','
                             << static_cast<unsigned>(probe.predict_valid) << ','
                             << static_cast<unsigned>(probe.predict_last) << '\n';
        }
    }

    void capture(const Outputs& outputs, std::vector<std::uint8_t>& bytes)
    {
        if (outputs.axi_valid.read() && axi_output_ready.read()) {
            const auto word = bytes_of(outputs.axi_data.read());
            bytes.insert(bytes.end(), word.begin(), word.end());
        }
    }

    void tick(const std::string& phase)
    {
        apb_clk.write(false);
        axi_clk.write(false);
        dsc_clk.write(false);
        sc_core::sc_start(sc_core::sc_time(1, sc_core::SC_NS));
        capture(monolithic, reference_bytes);
        capture(split, split_bytes);
        capture(replaced, replaced_bytes);
        if (monolithic.axi_line.read())
            ++reference_line_markers;
        if (monolithic.axi_frame.read())
            ++reference_frame_markers;

        dsc_clock_accumulator += dsc_clock_numerator;
        const auto dsc_edges = dsc_clock_accumulator / dsc_clock_denominator;
        dsc_clock_accumulator %= dsc_clock_denominator;
        for (unsigned edge = 0; edge < dsc_edges; ++edge) {
            dsc_clk.write(true);
            sc_core::sc_start(sc_core::sc_time(1, sc_core::SC_NS));
            ++dsc_cycles;
            record_dsc_boundary(phase);
            dsc_clk.write(false);
            sc_core::sc_start(sc_core::sc_time(1, sc_core::SC_NS));
        }

        apb_clk.write(true);
        axi_clk.write(true);
        sc_core::sc_start(sc_core::sc_time(1, sc_core::SC_NS));
        ++cycles;
        record_engine_boundary(phase);
        compare_outputs(split_difference, cycles, phase, monolithic, split);
        compare_outputs(replacement_difference, cycles, phase, split, replaced);
        std::ostringstream trace_key;
        trace_key << split_top.encoder_status() << split_top.bypass_enabled()
                  << split_top.axi_encoder_enabled() << split_top.dsc_encoder_enabled()
                  << replaced_top.encoder_status() << replaced_top.bypass_enabled()
                  << replaced_top.axi_encoder_enabled() << replaced_top.dsc_encoder_enabled()
                  << monolithic.axi_ready.read() << monolithic.axi_valid.read()
                  << monolithic.axi_line.read() << monolithic.axi_frame.read();
        if (trace_key.str() != last_trace_key || monolithic.axi_valid.read()
            || monolithic.axi_line.read() || monolithic.axi_frame.read()) {
            interface_trace << cycles << ',' << phase << ','
                            << split_top.encoder_status() << ',' << split_top.bypass_enabled() << ','
                            << split_top.axi_encoder_enabled() << ',' << split_top.dsc_encoder_enabled() << ','
                            << replaced_top.encoder_status() << ',' << replaced_top.bypass_enabled() << ','
                            << replaced_top.axi_encoder_enabled() << ',' << replaced_top.dsc_encoder_enabled() << ','
                            << monolithic.axi_ready.read() << ',' << monolithic.axi_valid.read() << ','
                            << monolithic.axi_line.read() << ',' << monolithic.axi_frame.read() << ','
                            << bv_text(monolithic.axi_data.read()) << '\n';
            last_trace_key = trace_key.str();
        }
    }

    void apb_write32(std::uint32_t address, std::uint32_t value)
    {
        apb_addr.write(address);
        apb_wdata.write(value);
        apb_strobe.write(0xf);
        apb_write.write(true);
        apb_select.write(true);
        apb_enable.write(false);
        tick("apb_setup");
        apb_enable.write(true);
        tick("apb_enable");
        apb_select.write(false);
        apb_enable.write(false);
        apb_write.write(false);
        tick("apb_complete");
    }
};

std::size_t first_mismatch(const std::vector<std::uint8_t>& left,
    const std::vector<std::uint8_t>& right)
{
    const auto common = std::min(left.size(), right.size());
    for (std::size_t index = 0; index < common; ++index) {
        if (left[index] != right[index])
            return index;
    }
    return left.size() == right.size() ? std::numeric_limits<std::size_t>::max() : common;
}

void write_difference(std::ostream& output, const FirstDifference& difference)
{
    if (!difference.present) {
        output << "null";
        return;
    }
    output << "{\"cycle\":" << difference.cycle
           << ",\"phase\":\"" << json_escape(difference.phase)
           << "\",\"signal\":\"" << json_escape(difference.signal)
           << "\",\"reference\":\"" << json_escape(difference.reference)
           << "\",\"candidate\":\"" << json_escape(difference.candidate) << "\"}";
}

} // namespace

int sc_main(int argc, char** argv)
{
    try {
        if (argc != 7) {
            std::cerr << "usage: hybrid_differential INPUT.ppm REFERENCE.dsc OUTPUT_DIR RUNTIME.json DSC_CLOCK_NUMERATOR DSC_CLOCK_DENOMINATOR\n";
            return 2;
        }
        const auto image = read_ppm(argv[1]);
        const auto dsc = read_file(argv[2]);
        if (dsc.size() <= 132 || std::string(dsc.begin(), dsc.begin() + 4) != "DSCF")
            throw std::runtime_error("reference does not contain DSCF + 128-byte PPS");
        const std::array<std::uint8_t, 128> pps = [&] {
            std::array<std::uint8_t, 128> value{};
            std::copy_n(dsc.begin() + 4, value.size(), value.begin());
            return value;
        }();
        const std::vector<std::uint8_t> golden(dsc.begin() + 132, dsc.end());
        const unsigned picture_width = (static_cast<unsigned>(pps[8]) << 8U) | pps[9];
        const unsigned picture_height = (static_cast<unsigned>(pps[6]) << 8U) | pps[7];
        const unsigned slice_width = (static_cast<unsigned>(pps[12]) << 8U) | pps[13];
        const unsigned chunk_size = (static_cast<unsigned>(pps[14]) << 8U) | pps[15];
        if (picture_width != image.width || picture_height != image.height || slice_width == 0)
            throw std::runtime_error("PPS dimensions do not match the PPM input");

        const std::string output_dir = argv[3];
        const auto dsc_clock_numerator = static_cast<unsigned>(std::stoul(argv[5]));
        const auto dsc_clock_denominator = static_cast<unsigned>(std::stoul(argv[6]));
        Simulation simulation{output_dir + "/module_interface_trace.csv",
            output_dir + "/engine_boundary_trace.csv", output_dir + "/engine_dsc_boundary_trace.csv",
            dsc_clock_numerator, dsc_clock_denominator};
        simulation.apb_select.write(false);
        simulation.apb_enable.write(false);
        simulation.apb_write.write(false);
        simulation.apb_strobe.write(0);
        simulation.apb_protect.write(0);
        simulation.apb_addr.write(0);
        simulation.apb_wdata.write(0);
        simulation.test_mode.write(false);
        simulation.axi_valid.write(false);
        simulation.axi_line.write(false);
        simulation.axi_frame.write(false);
        simulation.axi_data.write(0);
        simulation.axi_output_ready.write(true);
        simulation.reset_n.write(false);
        for (unsigned i = 0; i < 4; ++i)
            simulation.tick("reset_asserted");
        simulation.reset_n.write(true);
        for (unsigned i = 0; i < 16; ++i)
            simulation.tick("reset_release");

        simulation.apb_write32(0x104, 0);
        for (const auto byte : pps)
            simulation.apb_write32(0x100, byte);
        simulation.apb_write32(0x108, 1);
        simulation.apb_write32(0x008, 4);
        simulation.apb_write32(0x030, 7);
        simulation.apb_write32(0x040, (slice_width % 3U) == 0U ? 7U : ((1U << (slice_width % 3U)) - 1U));
        simulation.apb_write32(0x044, (picture_width + slice_width - 1U) / slice_width);
        simulation.apb_write32(0x048, 1);
        simulation.apb_write32(0x04c, std::min(4U, (picture_width + slice_width - 1U) / slice_width));
        simulation.apb_write32(0x050, std::max(1U, slice_width / 8U));
        simulation.apb_write32(0x060, 48);
        simulation.apb_write32(0x064, 0);
        simulation.apb_write32(0x068, chunk_size);
        simulation.apb_write32(0x000, 3);
        std::cout << "after_apb_writes reset_n=" << simulation.split_top.apb_reset_released()
                  << " command=" << simulation.split_top.encoder_command()
                  << " toggle=" << simulation.split_top.command_toggle() << '\n';

        // The command bit crosses from APB into the AXI clock domain through a
        // two-stage toggle synchronizer.  Presenting the frame marker in the
        // very next cycle races that synchronizer and leaves the command state
        // machine waiting for a frame which has already passed.  Allow the
        // command to become visible before sending the common frame stimulus.
        for (unsigned wait = 0; wait < 16; ++wait)
            simulation.tick("command_sync");
        std::cout << "after_command_sync status=" << simulation.split_top.encoder_status()
                  << " bypass=" << simulation.split_top.bypass_enabled()
                  << " axi_enable=" << simulation.split_top.axi_encoder_enabled()
                  << " dsc_enable=" << simulation.split_top.dsc_encoder_enabled() << '\n';

        simulation.axi_frame.write(true);
        simulation.tick("frame_marker");
        simulation.axi_frame.write(false);
        for (unsigned wait = 0; wait < 1000 && !(simulation.split_top.axi_encoder_enabled()
                 && simulation.split_top.dsc_encoder_enabled()
                 && simulation.replaced_top.axi_encoder_enabled()
                 && simulation.replaced_top.dsc_encoder_enabled()
                 && simulation.monolithic.axi_ready.read()
                 && simulation.split.axi_ready.read() && simulation.replaced.axi_ready.read()); ++wait)
            simulation.tick("wait_encoder_ready");
        std::cout << "after_frame_marker status=" << simulation.split_top.encoder_status()
                  << " bypass=" << simulation.split_top.bypass_enabled()
                  << " axi_enable=" << simulation.split_top.axi_encoder_enabled()
                  << " dsc_enable=" << simulation.split_top.dsc_encoder_enabled()
                  << " pps_refresh=" << simulation.split_top.pps_refresh_pending()
                  << " pps_update=" << simulation.split_top.pps_update_pending()
                  << " new_frame=" << simulation.split_top.new_frame_pending() << '\n';
        const auto split_pps = simulation.split_top.pps_config();
        const auto replaced_pps = simulation.replaced_top.pps_config();
        std::cout << "pps split(height,width,slice_h,slice_w,chunk)="
                  << split_pps.range(257, 242).to_uint() << ','
                  << split_pps.range(241, 226).to_uint() << ','
                  << split_pps.range(225, 210).to_uint() << ','
                  << split_pps.range(209, 194).to_uint() << ','
                  << split_pps.range(193, 178).to_uint()
                  << " replacement_equal=" << (split_pps == replaced_pps) << '\n';
        if (!(simulation.split_top.axi_encoder_enabled()
                && simulation.split_top.dsc_encoder_enabled()
                && simulation.replaced_top.axi_encoder_enabled()
                && simulation.replaced_top.dsc_encoder_enabled()))
            throw std::runtime_error("encoder did not leave frame/PPS startup states");
        const auto startup_status = simulation.split_top.encoder_status();
        const bool startup_pps_equal = split_pps == replaced_pps;

        const auto pixels = static_cast<std::size_t>(image.width) * image.height;
        for (std::size_t first = 0; first < pixels;) {
            if (first % image.width == 0) {
                simulation.axi_valid.write(false);
                simulation.axi_line.write(true);
                simulation.tick("line_marker");
                simulation.axi_line.write(false);
            }
            unsigned wait = 0;
            while (!(simulation.monolithic.axi_ready.read() && simulation.split.axi_ready.read()
                       && simulation.replaced.axi_ready.read())) {
                if (++wait > 100000)
                    throw std::runtime_error("input ready timeout");
                simulation.tick("input_backpressure");
            }
            simulation.axi_data.write(pixel_beat(image, first));
            simulation.axi_valid.write(true);
            simulation.tick("pixel_transfer");
            simulation.axi_valid.write(false);
            first += std::min<std::size_t>(4, pixels - first);
        }

        const auto target_words = (golden.size() + 23U) / 24U;
        bool drain_target_reached = false;
        bool drain_quiescent = false;
        std::size_t previous_output_bytes = simulation.reference_bytes.size();
        unsigned idle_drain_cycles = 0;
        for (unsigned wait = 0; wait < 250000; ++wait) {
            simulation.tick("output_drain");
            if (simulation.reference_bytes.size() != previous_output_bytes) {
                previous_output_bytes = simulation.reference_bytes.size();
                idle_drain_cycles = 0;
            } else if (++idle_drain_cycles >= 4096) {
                drain_quiescent = true;
                break;
            }
            if (simulation.reference_bytes.size() >= target_words * 24U
                && simulation.split_bytes.size() >= target_words * 24U
                && simulation.replaced_bytes.size() >= target_words * 24U) {
                drain_target_reached = true;
            }
        }

        write_file(output_dir + "/golden_payload.bin", golden);
        write_file(output_dir + "/rtl_monolithic.bin", simulation.reference_bytes);
        write_file(output_dir + "/rtl_split.bin", simulation.split_bytes);
        write_file(output_dir + "/hybrid_cycle_apb.bin", simulation.replaced_bytes);

        const auto mono_golden = first_mismatch(simulation.reference_bytes, golden);
        const auto split_mono = first_mismatch(simulation.reference_bytes, simulation.split_bytes);
        const auto replace_split = first_mismatch(simulation.split_bytes, simulation.replaced_bytes);
        std::ofstream report(argv[4]);
        report << "{\n  \"format\": \"dsc-hybrid-differential-runtime-v1\",\n"
               << "  \"cycles\": " << simulation.cycles << ",\n"
               << "  \"clocking\": {\"axi_cycles\": " << simulation.cycles
               << ", \"dsc_cycles\": " << simulation.dsc_cycles
               << ", \"dsc_to_axi\": \"" << dsc_clock_numerator << ':' << dsc_clock_denominator << "\"},\n"
               << "  \"input\": {\"width\": " << image.width << ", \"height\": " << image.height << "},\n"
               << "  \"setup\": {\"command\": " << simulation.split_top.encoder_command()
               << ", \"startup_status\": " << startup_status
               << ", \"pps_height\": " << split_pps.range(257, 242).to_uint()
               << ", \"pps_width\": " << split_pps.range(241, 226).to_uint()
               << ", \"pps_slice_height\": " << split_pps.range(225, 210).to_uint()
               << ", \"pps_slice_width\": " << split_pps.range(209, 194).to_uint()
               << ", \"pps_chunk_size\": " << split_pps.range(193, 178).to_uint()
               << ", \"replacement_pps_equal\": " << (startup_pps_equal ? "true" : "false") << "},\n"
               << "  \"drain_target_reached\": " << (drain_target_reached ? "true" : "false") << ",\n"
               << "  \"drain_quiescent\": " << (drain_quiescent ? "true" : "false") << ",\n"
               << "  \"module_interface_trace\": \"" << json_escape(output_dir + "/module_interface_trace.csv") << "\",\n"
               << "  \"engine_boundary_trace\": \"" << json_escape(output_dir + "/engine_boundary_trace.csv") << "\",\n"
               << "  \"engine_dsc_boundary_trace\": \"" << json_escape(output_dir + "/engine_dsc_boundary_trace.csv") << "\",\n"
               << "  \"engine_boundaries\": {\"input_accept\": " << simulation.engine_counts.input_accept
               << ", \"pack_accept\": " << simulation.engine_counts.pack_accept
               << ", \"partition_accept\": [" << simulation.engine_counts.partition_accept[0] << ','
               << simulation.engine_counts.partition_accept[1] << ',' << simulation.engine_counts.partition_accept[2]
               << ',' << simulation.engine_counts.partition_accept[3] << "], \"partition_last\": ["
               << simulation.engine_counts.partition_last[0] << ',' << simulation.engine_counts.partition_last[1]
               << ',' << simulation.engine_counts.partition_last[2] << ',' << simulation.engine_counts.partition_last[3]
               << "], \"csc_accept\": [" << simulation.engine_counts.csc_accept[0] << ','
               << simulation.engine_counts.csc_accept[1] << ',' << simulation.engine_counts.csc_accept[2]
               << ',' << simulation.engine_counts.csc_accept[3] << "], \"csc_last\": ["
               << simulation.engine_counts.csc_last[0] << ',' << simulation.engine_counts.csc_last[1]
               << ',' << simulation.engine_counts.csc_last[2] << ',' << simulation.engine_counts.csc_last[3]
               << "], \"slice_buffer_valid\": [" << simulation.engine_counts.slice_buffer_valid[0] << ','
               << simulation.engine_counts.slice_buffer_valid[1] << ',' << simulation.engine_counts.slice_buffer_valid[2]
               << ',' << simulation.engine_counts.slice_buffer_valid[3] << "], \"slice_buffer_last\": ["
               << simulation.engine_counts.slice_buffer_last[0] << ',' << simulation.engine_counts.slice_buffer_last[1]
               << ',' << simulation.engine_counts.slice_buffer_last[2] << ',' << simulation.engine_counts.slice_buffer_last[3]
               << "], \"flatness_valid\": [" << simulation.engine_counts.flatness_valid[0] << ','
               << simulation.engine_counts.flatness_valid[1] << ',' << simulation.engine_counts.flatness_valid[2]
               << ',' << simulation.engine_counts.flatness_valid[3] << "], \"flatness_last\": ["
               << simulation.engine_counts.flatness_last[0] << ',' << simulation.engine_counts.flatness_last[1]
               << ',' << simulation.engine_counts.flatness_last[2] << ',' << simulation.engine_counts.flatness_last[3]
               << "], \"predict_valid\": [" << simulation.engine_counts.predict_valid[0] << ','
               << simulation.engine_counts.predict_valid[1] << ',' << simulation.engine_counts.predict_valid[2]
               << ',' << simulation.engine_counts.predict_valid[3] << "], \"predict_last\": ["
               << simulation.engine_counts.predict_last[0] << ',' << simulation.engine_counts.predict_last[1]
               << ',' << simulation.engine_counts.predict_last[2] << ',' << simulation.engine_counts.predict_last[3]
               << "], \"slice_output_accept\": [" << simulation.engine_counts.slice_output_accept[0] << ','
               << simulation.engine_counts.slice_output_accept[1] << ',' << simulation.engine_counts.slice_output_accept[2]
               << ',' << simulation.engine_counts.slice_output_accept[3] << "], \"slice_output_last\": ["
               << simulation.engine_counts.slice_output_last[0] << ',' << simulation.engine_counts.slice_output_last[1]
               << ',' << simulation.engine_counts.slice_output_last[2] << ',' << simulation.engine_counts.slice_output_last[3]
               << "], \"fmt_muxword_words\": " << simulation.engine_counts.fmt_muxword_words
               << ", \"fmt_vlc_last_pulses\": " << simulation.engine_counts.fmt_vlc_last_pulses
               << ", \"muxword_complete_pulses\": " << simulation.engine_counts.muxword_complete_pulses
               << ", \"muxword_complete_edges\": " << simulation.engine_counts.muxword_complete_edges
               << ", \"muxword_complete_aligned\": " << simulation.engine_counts.muxword_complete_aligned
               << ", \"mux_accept\": " << simulation.engine_counts.mux_accept
               << ", \"mux_line\": " << simulation.engine_counts.mux_line
               << ", \"mux_frame\": " << simulation.engine_counts.mux_frame
               << ", \"top_accept\": " << simulation.engine_counts.top_accept << "},\n"
               << "  \"output_sidebands\": {\"line_markers\": " << simulation.reference_line_markers
               << ", \"frame_markers\": " << simulation.reference_frame_markers << "},\n"
               << "  \"bytes\": {\"golden\": " << golden.size()
               << ", \"rtl_monolithic\": " << simulation.reference_bytes.size()
               << ", \"rtl_split\": " << simulation.split_bytes.size()
               << ", \"hybrid_cycle_apb\": " << simulation.replaced_bytes.size() << "},\n"
               << "  \"bitstream_first_mismatch\": {\"rtl_vs_golden\": ";
        if (mono_golden == std::numeric_limits<std::size_t>::max()) report << "null"; else report << mono_golden;
        report << ", \"split_vs_rtl\": ";
        if (split_mono == std::numeric_limits<std::size_t>::max()) report << "null"; else report << split_mono;
        report << ", \"hybrid_vs_split\": ";
        if (replace_split == std::numeric_limits<std::size_t>::max()) report << "null"; else report << replace_split;
        report << "},\n  \"cycle_first_difference\": {\"split_vs_rtl\": ";
        write_difference(report, simulation.split_difference);
        report << ", \"hybrid_vs_split\": ";
        write_difference(report, simulation.replacement_difference);
        report << "}\n}\n";

        std::cout << "cycles=" << simulation.cycles
                  << " golden=" << golden.size()
                  << " rtl=" << simulation.reference_bytes.size()
                  << " split=" << simulation.split_bytes.size()
                  << " hybrid=" << simulation.replaced_bytes.size() << '\n';
        return 0;
    } catch (const std::exception& error) {
        std::cerr << error.what() << '\n';
        return 1;
    }
}
