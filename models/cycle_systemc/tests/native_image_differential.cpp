// Drive CIRCT's full-depth native SystemC encoder with the same image, PPS,
// APB setup, clock ratio, and AXI-stream convention as hybrid_differential.cpp.
#include "depth_6.systemc.hpp"

#include <algorithm>
#include <array>
#include <cctype>
#include <cstdint>
#include <cstdlib>
#include <fstream>
#include <iostream>
#include <iterator>
#include <limits>
#include <stdexcept>
#include <string>
#include <vector>

namespace {

std::string token(std::istream &input) {
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

struct Image {
  unsigned width = 0;
  unsigned height = 0;
  std::vector<std::uint8_t> rgb;
};

Image read_ppm(const std::string &path) {
  std::ifstream input(path, std::ios::binary);
  if (!input || token(input) != "P6")
    throw std::runtime_error("invalid P6 PPM input");
  Image image;
  image.width = static_cast<unsigned>(std::stoul(token(input)));
  image.height = static_cast<unsigned>(std::stoul(token(input)));
  if (token(input) != "255" || !image.width || !image.height)
    throw std::runtime_error("unsupported PPM dimensions or depth");
  image.rgb.resize(static_cast<size_t>(image.width) * image.height * 3);
  input.read(reinterpret_cast<char *>(image.rgb.data()), image.rgb.size());
  if (input.gcount() != static_cast<std::streamsize>(image.rgb.size()))
    throw std::runtime_error("truncated PPM input");
  return image;
}

std::vector<std::uint8_t> read_bytes(const std::string &path) {
  std::ifstream input(path, std::ios::binary);
  if (!input)
    throw std::runtime_error("cannot read reference: " + path);
  return {std::istreambuf_iterator<char>(input), std::istreambuf_iterator<char>()};
}

sc_dt::sc_biguint<192> pixel_beat(const Image &image, size_t first_pixel) {
  sc_dt::sc_biguint<192> result = 0;
  const size_t pixels = static_cast<size_t>(image.width) * image.height;
  for (unsigned lane = 0; lane < 4 && first_pixel + lane < pixels; ++lane) {
    const size_t source = (first_pixel + lane) * 3;
    const std::array<std::uint16_t, 3> components{
        static_cast<std::uint16_t>(image.rgb[source + 2] << 8),
        static_cast<std::uint16_t>(image.rgb[source + 1] << 8),
        static_cast<std::uint16_t>(image.rgb[source] << 8)};
    for (unsigned component = 0; component < 3; ++component) {
      const unsigned low = lane * 48 + component * 16;
      result.range(low + 15, low) = components[component];
    }
  }
  return result;
}

struct Simulation {
  sc_core::sc_signal<bool> apb_clk, apb_select, apb_enable, apb_write;
  sc_core::sc_signal<sc_dt::sc_uint<4>> apb_strobe;
  sc_core::sc_signal<sc_dt::sc_uint<3>> apb_protect;
  sc_core::sc_signal<sc_dt::sc_uint<12>> apb_addr;
  sc_core::sc_signal<sc_dt::sc_uint<32>> apb_wdata, apb_rdata;
  sc_core::sc_signal<bool> apb_ready, apb_slave_error, apb_int;
  sc_core::sc_signal<bool> dsc_clk, async_reset_n, async_test_mode, axi_clk;
  sc_core::sc_signal<bool> axi_tvalid_in, axi_tready_in, axi_tline_in;
  sc_core::sc_signal<bool> axi_tframe_in, axi_tvalid_out, axi_tready_out;
  sc_core::sc_signal<bool> axi_tline_out, axi_tframe_out;
  sc_core::sc_signal<sc_dt::sc_biguint<192>> axi_tdata_in, axi_tdata_out;
  std::array<sc_core::sc_signal<sc_dt::sc_uint<12>>, 18> bist_in, bist_out;
  dsc_encoder dut{"circt_native"};
  std::vector<std::uint8_t> bytes;
  std::uint64_t cycles = 0, accepted_pixels = 0, output_beats = 0;
  std::uint64_t line_markers = 0, frame_markers = 0;
  std::uint64_t pack_valid_cycles = 0, partition_valid_cycles = 0;
  std::uint64_t slice_valid_cycles = 0, mux_valid_cycles = 0;
  std::uint64_t slice_input_cycles = 0, convert_valid_cycles = 0;
  std::uint64_t buffer_valid_cycles = 0, flatness_valid_cycles = 0;
  std::uint64_t predict_valid_cycles = 0, format_valid_cycles = 0;
  unsigned dsc_clock_accumulator = 0;

  Simulation() {
    dut.apb_clk(apb_clk);
    dut.apb_select(apb_select);
    dut.apb_enable(apb_enable);
    dut.apb_write(apb_write);
    dut.apb_strobe(apb_strobe);
    dut.apb_protect(apb_protect);
    dut.apb_addr(apb_addr);
    dut.apb_wdata(apb_wdata);
    dut.apb_ready(apb_ready);
    dut.apb_slave_error(apb_slave_error);
    dut.apb_int(apb_int);
    dut.apb_rdata(apb_rdata);
    dut.dsc_clk(dsc_clk);
    dut.async_reset_n(async_reset_n);
    dut.async_test_mode(async_test_mode);
    dut.axi_clk(axi_clk);
    dut.axi_tvalid_in(axi_tvalid_in);
    dut.axi_tready_in(axi_tready_in);
    dut.axi_tline_in(axi_tline_in);
    dut.axi_tframe_in(axi_tframe_in);
    dut.axi_tdata_in(axi_tdata_in);
    dut.axi_tvalid_out(axi_tvalid_out);
    dut.axi_tready_out(axi_tready_out);
    dut.axi_tline_out(axi_tline_out);
    dut.axi_tframe_out(axi_tframe_out);
    dut.axi_tdata_out(axi_tdata_out);
#define BIND_BIST(I)                        \
    dut.bist_sram_in_##I(bist_in[I]);       \
    dut.bist_sram_out_##I(bist_out[I]);
    BIND_BIST(0) BIND_BIST(1) BIND_BIST(2) BIND_BIST(3)
        BIND_BIST(4) BIND_BIST(5) BIND_BIST(6) BIND_BIST(7)
            BIND_BIST(8) BIND_BIST(9) BIND_BIST(10) BIND_BIST(11)
                BIND_BIST(12) BIND_BIST(13) BIND_BIST(14) BIND_BIST(15)
                    BIND_BIST(16) BIND_BIST(17)
#undef BIND_BIST
    for (auto &signal : bist_in)
      signal.write(0);
  }

  void tick() {
    if (cycles % 100 == 0)
      std::cerr << "progress: cycles=" << cycles
                << " pixels=" << accepted_pixels
                << " output_beats=" << output_beats
                << " input_ready=" << axi_tready_in.read()
                << " command=" << dut.dsce_command_inst_cfg_dsc_encoder_encode_command.read()
                << " encoder_active=" << dut.dsce_command_inst_cfg_dsc_encoder_status_encoder_active_state.read()
                << " axi_enabled=" << dut.dsce_command_inst_axi_encoder_enable_state.read()
                << " dsc_enabled=" << dut.dsce_command_inst_dsc_encoder_enable_state.read()
                << " pack_valid_cycles=" << pack_valid_cycles
                << " partition_valid_cycles=" << partition_valid_cycles
                << " slice_input_cycles=" << slice_input_cycles
                << " convert_valid_cycles=" << convert_valid_cycles
                << " buffer_valid_cycles=" << buffer_valid_cycles
                << " flatness_valid_cycles=" << flatness_valid_cycles
                << " predict_valid_cycles=" << predict_valid_cycles
                << " format_valid_cycles=" << format_valid_cycles
                << " slice_valid_cycles=" << slice_valid_cycles
                << " mux_valid_cycles=" << mux_valid_cycles
                << " engine_output_valid=" << dut.dsce_engine_inst_axi_tvalid_out_state.read()
                << '\n';
    apb_clk.write(false);
    axi_clk.write(false);
    dsc_clk.write(false);
    sc_core::sc_start(sc_core::sc_time(1, sc_core::SC_NS));
    if (axi_tvalid_out.read() && axi_tready_out.read()) {
      const auto word = axi_tdata_out.read();
      for (unsigned byte = 0; byte < 24; ++byte)
        bytes.push_back(static_cast<std::uint8_t>(word.range(byte * 8 + 7, byte * 8).to_uint()));
      ++output_beats;
    }
    if (axi_tline_out.read())
      ++line_markers;
    if (axi_tframe_out.read())
      ++frame_markers;

    dsc_clock_accumulator += 3;
    const unsigned edges = dsc_clock_accumulator;
    dsc_clock_accumulator = 0;
    for (unsigned edge = 0; edge < edges; ++edge) {
      dsc_clk.write(true);
      sc_core::sc_start(sc_core::sc_time(1, sc_core::SC_NS));
      const auto &engine = dut.dsce_engine_inst;
      pack_valid_cycles += engine.dsce_pack_inst_axi_tvalid_out_state.read();
      partition_valid_cycles +=
          engine.dsce_partition_inst_axi_valid_out_state.read() != 0;
      slice_input_cycles += engine.gen_slice_0_dsce_slice_inst_axi_valid_in.read();
      const auto &slice = engine.gen_slice_0_dsce_slice_inst;
      convert_valid_cycles += slice.dsce_convert_inst_axi_valid_out_state.read();
      buffer_valid_cycles += slice.dsce_slice_buffer_inst_dsc_valid_out_state.read();
      flatness_valid_cycles +=
          slice.dsce_flatness_inst_dsc_group_valid_out_state.read();
      predict_valid_cycles +=
          slice.dsce_predict_inst_dsc_group_valid_out_state.read();
      format_valid_cycles += slice.dsce_format_inst_axi_tvalid_out_state.read();
      slice_valid_cycles +=
          engine.gen_slice_0_dsce_slice_inst_axi_tvalid_out_state.read();
      mux_valid_cycles += engine.dsce_slice_mux_inst_axi_tvalid_out_state.read();
      dsc_clk.write(false);
      sc_core::sc_start(sc_core::sc_time(1, sc_core::SC_NS));
    }
    apb_clk.write(true);
    axi_clk.write(true);
    sc_core::sc_start(sc_core::sc_time(1, sc_core::SC_NS));
    ++cycles;
  }

  void apb_write32(std::uint32_t address, std::uint32_t value) {
    apb_addr.write(address);
    apb_wdata.write(value);
    apb_strobe.write(0xf);
    apb_write.write(true);
    apb_select.write(true);
    apb_enable.write(false);
    tick();
    apb_enable.write(true);
    tick();
    apb_select.write(false);
    apb_enable.write(false);
    apb_write.write(false);
    tick();
  }
};

size_t first_mismatch(const std::vector<std::uint8_t> &left,
                      const std::vector<std::uint8_t> &right) {
  const size_t common = std::min(left.size(), right.size());
  for (size_t i = 0; i < common; ++i)
    if (left[i] != right[i])
      return i;
  return left.size() == right.size() ? std::numeric_limits<size_t>::max()
                                     : common;
}

} // namespace

unsigned idle_limit() {
  const char *value = std::getenv("DSCFLOW_NATIVE_IDLE_LIMIT");
  if (!value || !*value)
    return 4096;
  const unsigned parsed = static_cast<unsigned>(std::stoul(value));
  if (!parsed)
    throw std::runtime_error("DSCFLOW_NATIVE_IDLE_LIMIT must be positive");
  return parsed;
}

int sc_main(int argc, char **argv) {
  try {
    if (argc != 4) {
      std::cerr << "usage: native_image_differential INPUT.ppm REFERENCE.dsc OUTPUT.bin\n";
      return 2;
    }
    const auto image = read_ppm(argv[1]);
    const auto reference = read_bytes(argv[2]);
    if (reference.size() <= 132 ||
        std::string(reference.begin(), reference.begin() + 4) != "DSCF")
      throw std::runtime_error("reference lacks DSCF header and PPS");
    std::array<std::uint8_t, 128> pps{};
    std::copy_n(reference.begin() + 4, pps.size(), pps.begin());
    const std::vector<std::uint8_t> golden(reference.begin() + 132,
                                           reference.end());
    const unsigned picture_width = (pps[8] << 8) | pps[9];
    const unsigned picture_height = (pps[6] << 8) | pps[7];
    const unsigned slice_width = (pps[12] << 8) | pps[13];
    const unsigned chunk_size = (pps[14] << 8) | pps[15];
    if (picture_width != image.width || picture_height != image.height ||
        !slice_width)
      throw std::runtime_error("PPS dimensions do not match input image");

    Simulation simulation;
    simulation.apb_select.write(false);
    simulation.apb_enable.write(false);
    simulation.apb_write.write(false);
    simulation.apb_strobe.write(0);
    simulation.apb_protect.write(0);
    simulation.apb_addr.write(0);
    simulation.apb_wdata.write(0);
    simulation.async_test_mode.write(false);
    simulation.axi_tvalid_in.write(false);
    simulation.axi_tline_in.write(false);
    simulation.axi_tframe_in.write(false);
    simulation.axi_tdata_in.write(0);
    simulation.axi_tready_out.write(true);
    simulation.async_reset_n.write(false);
    for (unsigned i = 0; i < 4; ++i)
      simulation.tick();
    simulation.async_reset_n.write(true);
    for (unsigned i = 0; i < 16; ++i)
      simulation.tick();

    simulation.apb_write32(0x104, 0);
    for (std::uint8_t byte : pps)
      simulation.apb_write32(0x100, byte);
    simulation.apb_write32(0x108, 1);
    simulation.apb_write32(0x008, 4);
    simulation.apb_write32(0x030, 7);
    simulation.apb_write32(0x040, slice_width % 3 == 0 ? 7 : (1U << (slice_width % 3)) - 1);
    simulation.apb_write32(0x044, (image.width + slice_width - 1) / slice_width);
    simulation.apb_write32(0x048, 1);
    simulation.apb_write32(0x04c, std::min(4U, (image.width + slice_width - 1) / slice_width));
    simulation.apb_write32(0x050, std::max(1U, slice_width / 8));
    simulation.apb_write32(0x060, 48);
    simulation.apb_write32(0x064, 0);
    simulation.apb_write32(0x068, chunk_size);
    simulation.apb_write32(0x000, 3);
    for (unsigned i = 0; i < 16; ++i)
      simulation.tick();
    simulation.axi_tframe_in.write(true);
    simulation.tick();
    simulation.axi_tframe_in.write(false);

    unsigned ready_wait = 0;
    while (!simulation.axi_tready_in.read() && ready_wait++ < 1000)
      simulation.tick();
    std::cout << "startup: apb_ready=" << simulation.apb_ready.read()
              << " axi_ready=" << simulation.axi_tready_in.read()
              << " apb_int=" << simulation.apb_int.read()
              << " cycles=" << simulation.cycles << '\n';

    const size_t pixels = static_cast<size_t>(image.width) * image.height;
    for (size_t first = 0; first < pixels;) {
      if (first % image.width == 0) {
        simulation.axi_tvalid_in.write(false);
        simulation.axi_tline_in.write(true);
        simulation.tick();
        simulation.axi_tline_in.write(false);
      }
      unsigned wait = 0;
      while (!simulation.axi_tready_in.read() && wait++ < 4096)
        simulation.tick();
      if (!simulation.axi_tready_in.read()) {
        std::cout << "input_ready_timeout at_pixel=" << first
                  << " cycles=" << simulation.cycles << '\n';
        break;
      }
      simulation.axi_tdata_in.write(pixel_beat(image, first));
      simulation.axi_tvalid_in.write(true);
      simulation.tick();
      simulation.axi_tvalid_in.write(false);
      first += std::min<size_t>(4, pixels - first);
      simulation.accepted_pixels = first;
    }

    unsigned idle = 0;
    size_t previous_size = simulation.bytes.size();
    const unsigned maximum_idle = idle_limit();
    for (unsigned i = 0; i < 250000 && idle < maximum_idle; ++i) {
      simulation.tick();
      if (simulation.bytes.size() != previous_size) {
        previous_size = simulation.bytes.size();
        idle = 0;
      } else {
        ++idle;
      }
      if (simulation.bytes.size() >= golden.size() && idle >= 64)
        break;
    }
    std::ofstream output(argv[3], std::ios::binary);
    output.write(reinterpret_cast<const char *>(simulation.bytes.data()),
                 simulation.bytes.size());
    if (!output)
      throw std::runtime_error("cannot write output bitstream");
    const size_t mismatch = first_mismatch(simulation.bytes, golden);
    std::cout << "result: pixels_accepted=" << simulation.accepted_pixels
              << " cycles=" << simulation.cycles
              << " output_beats=" << simulation.output_beats
              << " pack_valid_cycles=" << simulation.pack_valid_cycles
              << " partition_valid_cycles=" << simulation.partition_valid_cycles
              << " slice_input_cycles=" << simulation.slice_input_cycles
              << " convert_valid_cycles=" << simulation.convert_valid_cycles
              << " buffer_valid_cycles=" << simulation.buffer_valid_cycles
              << " flatness_valid_cycles=" << simulation.flatness_valid_cycles
              << " predict_valid_cycles=" << simulation.predict_valid_cycles
              << " format_valid_cycles=" << simulation.format_valid_cycles
              << " slice_valid_cycles=" << simulation.slice_valid_cycles
              << " mux_valid_cycles=" << simulation.mux_valid_cycles
              << " line_markers=" << simulation.line_markers
              << " frame_markers=" << simulation.frame_markers
              << " output_bytes=" << simulation.bytes.size()
              << " golden_bytes=" << golden.size() << " first_mismatch=";
    if (mismatch == std::numeric_limits<size_t>::max())
      std::cout << "none\n";
    else
      std::cout << mismatch << '\n';
    return mismatch == std::numeric_limits<size_t>::max() ? 0 : 3;
  } catch (const std::exception &error) {
    std::cerr << error.what() << '\n';
    return 1;
  }
}
