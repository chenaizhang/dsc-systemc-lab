#include "depth_3.systemc.hpp"

#include <array>
#include <iostream>

int sc_main(int argc, char **argv) {
  sc_signal<bool> clk;
  sc_signal<bool> reset_n;
  sc_signal<sc_uint<8>> input;
  sc_signal<sc_uint<8>> output;

  hierarchy_top dut("dut");
  dut.clk(clk);
  dut.reset_n(reset_n);
  dut.a(input);
  dut.y(output);

  auto pulse = [&] {
    clk.write(true);
    sc_start(1, SC_NS);
    clk.write(false);
    sc_start(1, SC_NS);
  };

  clk.write(false);
  reset_n.write(false);
  input.write(0);
  sc_start(SC_ZERO_TIME);
  pulse();

  reset_n.write(true);
  constexpr std::array<unsigned, 8> samples = {11, 22, 33, 44,
                                                55, 66, 77, 88};
  for (size_t index = 0; index < samples.size(); ++index) {
    input.write(samples[index]);
    pulse();
    if (index >= 4 && output.read() != samples[index - 4]) {
      std::cerr << "memory sequence mismatch at sample " << index << ": got "
                << output.read() << ", expected " << samples[index - 4]
                << "\n";
      return 1;
    }
  }

  std::cout << "HIERARCHY_COMB_SEQ_MEMORY_RUNTIME_OK\n";
  return 0;
}
