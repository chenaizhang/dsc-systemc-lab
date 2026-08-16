// stdout.h
#ifndef STDOUT_H
#define STDOUT_H

#include <systemc.h>

SC_MODULE(function_control) {
  sc_in<sc_uint<17>> lhs;
  sc_in<sc_uint<17>> rhs;
  sc_out<sc_uint<17>> result;

  SC_CTOR(function_control) {
    SC_METHOD(innerLogic);
    sensitive << lhs << rhs;
  }

  void innerLogic() {

    <<UNSUPPORTED OPERATION (systemc.convert)>>

    <<UNSUPPORTED OPERATION (systemc.convert)>>

    <<UNSUPPORTED OPERATION (comb.icmp)>>

    <<UNSUPPORTED OPERATION (comb.mux)>>

    <<UNSUPPORTED OPERATION (systemc.convert)>>
    result.write(<<INVALID VALUE TO INLINE (%6 = systemc.convert %5 : (i17) -> !systemc.uint<17>)>>);
  }
};

#endif // STDOUT_H
