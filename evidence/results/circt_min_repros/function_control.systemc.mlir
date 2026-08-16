module {
  emitc.include <"systemc.h">
  systemc.module @function_control (%lhs: !systemc.in<!systemc.uint<17>>, %rhs: !systemc.in<!systemc.uint<17>>, %result: !systemc.out<!systemc.uint<17>>) {
    systemc.ctor {
      systemc.method %innerLogic
      systemc.sensitive %lhs, %rhs : !systemc.in<!systemc.uint<17>>, !systemc.in<!systemc.uint<17>>
    }
    %innerLogic = systemc.func {
      %0 = systemc.signal.read %lhs : !systemc.in<!systemc.uint<17>>
      %1 = systemc.convert %0 : (!systemc.uint<17>) -> i17
      %2 = systemc.signal.read %rhs : !systemc.in<!systemc.uint<17>>
      %3 = systemc.convert %2 : (!systemc.uint<17>) -> i17
      %4 = comb.icmp ult %1, %3 : i17
      %5 = comb.mux %4, %1, %3 : i17
      %6 = systemc.convert %5 : (i17) -> !systemc.uint<17>
      systemc.signal.write %result, %6 : !systemc.out<!systemc.uint<17>>
    }
  }
}
