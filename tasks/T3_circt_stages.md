# T3：CIRCT 分阶段定位

## 目标

确认当前 CIRCT 版本在真实 DSC 上能完成 HW、Comb、Seq 的哪一段，不再笼统写“转换失败”。

## 工作

1. 执行 `dscflow circt run --config configs/staged_circt.json ...`。
2. 保存 frontend core IR、规范化 IR、各 pass 输出和 stderr。
3. 对首个不支持 operation 生成最小复现。
4. HW 可转换时把其结构作为 SystemC 骨架候选；Comb/Seq 失败分别处理。
5. 同时构建 `dsc_encoder`、`dsce_engine`、`dsce_apb` 的 Verilator `--sc` 模型。

## 验收

- 报告列出每阶段状态、首个失败 op、工具版本和复现命令；
- CIRCT/Verilator 端口集合自动比对；
- 不把 Verilator 生成模型说成 CIRCT 原生 SystemC。

## 当前进度

- 真实 DSC 的 SV frontend → HW/Comb/Seq/LLHD core IR 已通过。
- `convert-hw-to-systemc` 首先失败于 package task 产生的 `llhd.coroutine`。
- `tests/fixtures/circt/llhd_coroutine_task.sv` 已把问题缩成一个 task 和一次调用；CIRCT 1.155.0
  稳定复现相同 conversion 错误。
- 将等价 task 改成 function 后，HW→SystemC dialect conversion 成功，随后 C++ emission 失败于
  `systemc.convert`、`comb.icmp`、`comb.mux`；对照用例为
  `tests/fixtures/circt/function_control.sv`。
- 可复现入口为 `scripts/run_circt_min_repros.sh`，日志位于
  `evidence/results/circt_min_repros/`。
- 尚未实现 CIRCT conversion/emission patch；在 patch 完成前，原生 cycle SystemC 不能闭环，
  Verilator-SystemC 仍是可执行黑盒。
