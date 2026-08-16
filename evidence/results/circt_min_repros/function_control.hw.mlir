module {
  hw.module @function_control(in %lhs : i17, in %rhs : i17, out result : i17) {
    %0 = comb.icmp ult %lhs, %rhs : i17
    %1 = comb.mux %0, %lhs, %rhs : i17
    hw.output %1 : i17
  }
}
