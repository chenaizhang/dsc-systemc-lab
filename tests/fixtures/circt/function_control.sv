package function_control_pkg;
  function automatic logic [16:0] choose_min(
      input logic [16:0] lhs,
      input logic [16:0] rhs
  );
    choose_min = (lhs < rhs) ? lhs : rhs;
  endfunction
endpackage

module function_control(
    input  logic [16:0] lhs,
    input  logic [16:0] rhs,
    output logic [16:0] result
);
  assign result = function_control_pkg::choose_min(lhs, rhs);
endmodule
