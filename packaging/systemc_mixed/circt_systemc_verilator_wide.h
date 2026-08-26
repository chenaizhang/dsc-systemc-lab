#pragma once

#include <systemc.h>
#include <verilated.h>

#include <algorithm>
#include <cstddef>

namespace circt_systemc {

template <std::size_t Words, typename SystemCValue>
void assign_wide(VlWide<Words> &destination, const SystemCValue &source) {
  const std::size_t source_width = static_cast<std::size_t>(source.length());
  for (std::size_t word = 0; word < Words; ++word) {
    const std::size_t low = word * 32;
    const std::size_t high = std::min(low + 31, source_width - 1U);
    destination[word] = source.range(high, low).to_uint();
  }
}

template <std::size_t Width, std::size_t Words>
sc_dt::sc_biguint<Width> read_wide(const VlWide<Words> &source) {
  sc_dt::sc_biguint<Width> destination = 0;
  for (std::size_t word = 0; word < Words; ++word) {
    const std::size_t low = word * 32;
    const std::size_t high = std::min(low + 31, Width - 1U);
    destination.range(high, low) = source[word];
  }
  return destination;
}

} // namespace circt_systemc
