module {
  llhd.coroutine private @"llhd_coroutine_task_pkg::choose_min"(%arg0: i17, %arg1: i17, %arg2: !llhd.ref<i17>) {
    %0 = llhd.constant_time <0ns, 0d, 1e>
    %1 = comb.icmp ult %arg0, %arg1 : i17
    %2 = comb.mux %1, %arg0, %arg1 : i17
    llhd.drv %arg2, %2 after %0 : i17
    llhd.return
  }
  hw.module @llhd_coroutine_task(in %lhs : i17, in %rhs : i17, out result : i17) {
    %c0_i17 = hw.constant 0 : i17
    %result = llhd.sig %c0_i17 : i17
    %0 = llhd.prb %result : i17
    llhd.combinational {
      llhd.call_coroutine @"llhd_coroutine_task_pkg::choose_min"(%lhs, %rhs, %result) : (i17, i17, !llhd.ref<i17>) -> ()
      llhd.yield
    }
    hw.output %0 : i17
  }
}
