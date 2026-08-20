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
- fork 已新增 `convert-hw-to-systemc="structure-only=true"`，只转换模块、端口、实例、信号、绑定和
  空 `SC_METHOD`。
- 真实 DSC HW 骨架生成 50 个模块定义和 89 条定义级实例边；SystemC C++ 编译、运行时
  elaboration 均通过，展开为 261 个实例，与 UHDM 相同。
- 完整行为转换首个失败已推进到 aggregate `hw.bitcast`；Comb 16,412、Seq 540、LLHD 433 个
  operation 均已分区保存。
- `scripts/run_circt_min_repros.sh` 现在把 HW-only 成功作为硬门禁，并保留完整转换的实际返回码，
  不再把旧版本的固定失败文本当成验收条件。
- 原生 cycle SystemC 行为仍未闭环，Verilator-SystemC 继续作为可执行黑盒。
