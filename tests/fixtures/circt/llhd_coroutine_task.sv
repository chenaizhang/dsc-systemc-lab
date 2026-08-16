package llhd_coroutine_task_pkg;
  task automatic choose_min(
      input  logic [16:0] lhs,
      input  logic [16:0] rhs,
      output logic [16:0] result
  );
    result = (lhs < rhs) ? lhs : rhs;
  endtask
endpackage

module llhd_coroutine_task(
    input  logic [16:0] lhs,
    input  logic [16:0] rhs,
    output logic [16:0] result
);
  always_comb begin
    llhd_coroutine_task_pkg::choose_min(lhs, rhs, result);
  end
endmodule
