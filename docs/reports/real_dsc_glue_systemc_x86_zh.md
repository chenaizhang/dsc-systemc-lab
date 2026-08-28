# 真实 DSC 胶水逻辑的 CIRCT→SystemC x86 实测报告

## 1. 测试目的

本次测试不使用玩具模块，而是直接回答真实 DSC RTL 中以下内容能否由当前 CIRCT fork 转成可编译、可运行的 SystemC：

- 模块层次、实例和模块间连线；
- 组合胶水逻辑；
- 寄存器、时钟边沿和复位；
- 上述内容同时存在时的端到端转换能力。

所有 EDA 命令均于 2026-08-25 在 Ubuntu x86_64 服务器执行。本机只用于整理测试代码和报告。

## 2. 测试环境与输入

| 项目 | 实测值 |
|---|---|
| CIRCT | LLVM 24git，`codex/systemc-backend` fork 构建 |
| Verilator | 5.032 |
| SystemC | 3.0.2 |
| 顶层 RTL | `dsc_encoder.sv` |
| 组合/层次样本 | `dsce_engine.sv`、`dsce_command.sv` |
| 时钟/复位样本 | `dsce_reset.sv` |
| 辅助样本 | `dsce_timers.sv`、`dsce_interrupt.sv`、`dsce_partition.sv` |

服务器证据根目录：

```text
/home/francis/Work/dsc-systemc-lab/.work/runs/staged-circt/real-glue-latest-20260825
/home/francis/Work/dsc-systemc-lab/.work/runs/staged-circt/real-glue-focused-20260825
```

## 3. 验证门禁

每个样本依次经过以下门禁：

```text
真实 SystemVerilog
  → circt-verilog 生成 HW/Comb/Seq/LLHD IR
  → CIRCT lowering
  → SystemC dialect
  → ExportSystemC 导出 C++
  → x86 SystemC C++ 编译
  → 运行时 elaboration 或 Verilator 差分
```

仅生成 IR 不记为“SystemC 可用”，仅通过 C++ 编译也不记为“语义正确”。

## 4. 实测结果

### 4.1 真实顶层 HW 骨架

`dsc_encoder` 使用 `convert-hw-to-systemc=structure-only=true` 后：

| 检查项 | 结果 |
|---|---:|
| `SC_MODULE` | 50 |
| `sc_signal` | 2,262 |
| ExportSystemC | 通过 |
| SystemC C++ 语法编译 | 通过 |

结论：真实设计的模块壳、端口、子模块成员、内部通道和绑定可以由 CIRCT 生成，不需要 LLM 猜连线。

### 4.2 含子模块、组合逻辑和时序逻辑的 `dsce_command`

该模块同时包含状态机、两个时钟域、异步复位、组合状态映射和 5 个同步子模块实例。

| 检查项 | 结果 |
|---|---:|
| `comb.*` | 194 |
| `seq.*` | 25 |
| `hw.instance` | 5 |
| HW/Comb/Seq→SystemC | 通过 |
| ExportSystemC | 通过 |
| SystemC C++ 编译 | 通过 |
| 运行时展开模块 | 6 |
| 运行时端口 | 56 |

生成代码中存在实际的子模块对象、`sc_signal`、构造函数端口绑定、`SC_METHOD`、组合表达式和寄存器状态更新。运行时 elaboration 成功，证明这些绑定不是只停留在文本中。

### 4.3 时钟、复位和寄存器的 `dsce_reset`

该模块包含三个时钟域、异步复位、软复位、8 级复位释放移位寄存器和测试模式组合选择。

| 检查项 | 结果 |
|---|---:|
| `comb.*` | 21 |
| `seq.*` | 7 |
| HW/Comb/Seq→SystemC | 通过 |
| ExportSystemC | 通过 |
| SystemC C++ 编译 | 通过 |
| 与 Verilator-RTL 差分 | 63/63 次一致 |

差分刺激覆盖：异步复位拉低与释放、三个时钟同步翻转、8 级复位释放、APB 软复位、软复位恢复和测试模式直通。该结果证明当前生成代码对这个真实模块的时钟/复位行为不仅语法正确，而且在所测序列上与原 RTL 一致。

### 4.4 其他真实模块

| 模块 | 特征 | 转换/导出/编译 | 结果 |
|---|---|---|---|
| `dsce_timers` | 组合映射、计数器、异步复位 | 全通过 | 基础组合及时序逻辑可用 |
| `dsce_interrupt` | 同步子模块、组合聚合、寄存器 | 转换失败 | 时序反馈值出现 SSA 支配关系错误 |
| `dsce_partition` | 聚合数据、循环、寄存器 | 转换失败 | `comb.concat` 输入总宽 33 位，结果错误标成 48 位 |
| `dsce_engine` | 8 个直属数据通路子模块和组合胶水 | 骨架通过，完整转换失败 | 深层 `dsce_bpvector` 的聚合 `hw.bitcast` 无法直接合法化 |

### 4.5 完整顶层的正确分阶段流程

完整顶层先执行 LLHD 清理和 timed-process→Seq lowering，再执行 HW→SystemC。此流程中原始 `hw.bitcast` 不再是首错，但转换输入仍未成为合法 IR：

- 9 处 `comb.concat` 位宽不一致；
- 22 处 SSA 值在定义前被使用；
- timed process 已消除，仅余 8 个零时间 `llhd.constant_time`。

代表性错误包括：

```text
comb.concat 输入总宽 499 位，结果类型却是 i216
comb.concat 输入总宽 26 位，结果类型却是 i32
comb.extract 使用了在当前 block 后方才定义的反馈值
```

因此，当前完整 DSC 不是卡在 ExportSystemC，也不是缺 SystemC 库，而是进入 HW→SystemC 前的 Core IR 已被 LLHD/聚合 lowering 生成成位宽或 SSA 顺序不合法的形式。

### 4.6 真实 Verilator 内嵌路径

对 `dsce_engine` 的 8 个直属实例运行 `systemc-wrap-verilated-instances`，8 个 `hw.instance` 均能被自动替换成 `systemc.interop.verilated`。但后续 HW→SystemC 会展开结构体/数组端口，interop 操作仍保留展开前的端口列表，验证时报：

```text
systemc.interop.verilated expected 37 operands but got 26
```

这说明旧的“先插入 interop、后做数组端口 flatten”顺序会失配。修复点已放在 CIRCT 的调用边界：把 interop 包装安排到端口 flatten 之后；调用方通过 `prepared-input` 明确告知 HW→SystemC 不再重复预处理。这样可以保证 interop 的输入、输出、名称和类型与 Verilator flatten ABI 一致。

## 5. 本轮 CIRCT 修复后的复测

在上述基线之后，fork 中落地了三项修复，并重新在同一台 x86 服务器复测：

- HW→SystemC 不再把混排的输出端口当成输入参数索引；新增了混排端口回归用例。
- 顺序寄存器先物化为 SystemC state signal，再进入 `systemc.func`，切断了寄存器反馈造成的伪 SSA 支配错误。
- ExportSystemC 对宽位 `sc_bv` 的 concat、mux、extract 放开内联；新增了 768 位聚合组合回归用例。
- 对宽位聚合结果增加 `systemc.cpp.variable` 临时量和显式位段赋值，避免重复内联导致代码指数膨胀，并规避 SystemC `sc_concatref/sc_subref` 的重载歧义。
- Verilator interop 增加了 `prepared-input` 阶段：先 flatten/aggregate lowering，再插入 interop；显式选择内部模块时将其 RTL body 替换为 `hw.module.extern`，避免重复翻译。
- 新增数组端口 interop 回归：以 `flatten-arrays=true` 完成端口标量化后再插入 interop，x86 上通过 operand 数量、SystemC lowering 和 FileCheck。
- HW→SystemC 的内部聚合准备改为两轮 `aggregate-to-comb → convert-bitcasts`，避免第二轮聚合物化重新插回 `hw.bitcast`；转换失败时附带输出首个 SSA 依赖环中的 operation。
- HW→SystemC 拓扑排序将 `hw.instance` 视为层次/通道边界，允许合法的模块互连反馈由 `sc_signal` 承载，不再把顶层实例环误判为父模块组合环。

复测结果：

| 门禁 | 结果 |
|---|---:|
| `dsce_reset` 转换、导出、C++ 编译 | 通过 |
| `dsce_command` 转换、导出、C++ 编译 | 通过 |
| `dsce_interrupt` 转换、导出、C++ 编译 | 通过 |
| `dsce_timers` 转换、导出、C++ 编译 | 通过 |
| `dsce_partition` HW→SystemC 转换、导出、C++ 编译 | 通过 |
| 数组端口 Verilator interop（显式预处理后） | 通过 |
| `dsce_reset` 最新生成代码与 Verilator 差分 | 63/63 通过 |
| `dsce_command` 最新生成代码运行时展开 | 6 个模块、56 个端口 |

`dsce_partition` 已使用最新 ExportSystemC 完成导出和 C++ 语法编译。完整 `dsc_encoder`/`dsce_engine` 在正确的 LLHD→聚合预处理顺序下已不再出现 `hw.bitcast` 首错，顶层实例之间的结构反馈也已越过拓扑排序；当前唯一首错是 `dsce_bpvector` 中由 `comb.mux`/`comb.add` 构成的未切断依赖环。新的诊断会列出环内 operation，便于继续修复 LLHD 时序状态识别。

## 6. 结论

当前结论不是“全都能解决”，而是：

1. **HW 结构可以解决。**真实顶层已生成 50 个可编译 `SC_MODULE` 和 2,262 个通道声明。
2. **基础组合胶水、寄存器、时钟和复位可以解决。**`dsce_command` 完成带 5 个子模块的编译与运行时展开；`dsce_reset` 完成 63 次 Verilator 差分。
3. **完整 DSC 数据通路尚不能解决。**聚合 concat 位宽、数组端口 ABI 数量错配、顶层实例互连反馈和大部分时序伪支配问题已在 fork 修复；正确预处理后 `hw.bitcast` 已清零，剩余工作集中在 `dsce_bpvector` 的时序反馈环。
4. **ExportSystemC 的基础 Comb emitter 已覆盖本轮宽位胶水。**`dsce_partition` 和独立 768 位回归均已导出并通过 C++ 语法编译。

## 7. CIRCT 后续修复顺序

1. 根据新增 SCC operation 诊断，修复 `dsce_bpvector` 的 LLHD clocked-signal→`seq.compreg` 状态切分；若确认是 RTL 纯组合环，则将该模块显式切换为 Verilator interop 黑盒。
2. 将真实 `dsce_engine` 的预处理固定为 `LLHD lowering → flatten-arrays=true → aggregate/bitcast lowering → interop`，再完成混合仿真。
3. 保持宽位临时量/位段赋值回归，防止后续 emitter 改动重新引入 `sc_concatref/sc_subref` 重载问题。
4. 为 `dsce_reset`、`dsce_command`、`dsce_interrupt`、`dsce_partition` 和 aggregate interop 保留 CIRCT 回归测试。
5. 上述门禁通过后，再重跑完整 `dsc_encoder` 的 ExportSystemC、C++ 编译和逐周期差分。

本报告不声称图像压缩最终输出已通过；本轮只验证 CIRCT 对真实层次、胶水逻辑、组合逻辑和时序逻辑的生成能力。

## 8. 2026-08-28 完整顶层混合模型复测

后续复测没有继续强行把 `dsce_bpvector` 全部原生转换，而是按本报告既定兜底策略，将
`dsc_encoder` 的七个 UHDM 直属子模块作为 Verilator interop 边界，保留 CIRCT 生成的顶层
SystemC 模块、信号和胶水逻辑。本轮额外修复了 interop 可执行更新的依赖排序，以及一位共享
packed 表达式被错误物化为 `sc_bv<1>` 的问题。

最终 `dsc_encoder` 完整混合模型在 x86_64 Linux 上从源码重新生成七个 Verilator 子模型，
SystemC C++ 编译、链接、elaboration smoke test 和 CDC shim 均通过（CTest 2/2）。因此上文
“完整数据通路尚不能解决”仍仅指**全原生 Comb/Seq SystemC**；不再代表完整顶层混合模型不能
构建。图像输入与独立 golden 码流差分仍未在这项编译门禁中执行。
