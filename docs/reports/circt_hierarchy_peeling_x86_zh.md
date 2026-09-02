# CIRCT 层次剥离与 SystemC 骨架 x86 验证报告

## 1. 目的

验证 CIRCT 是否能够从真实 `dsc_encoder` HW IR 按深度逐层剥离模块层次，并在不转换
frontier 以下 Comb、Seq、Memory 和 package helper 行为的情况下，生成结构正确且可编译的
SystemC 骨架。Verilator 不在本次验证范围内。

## 2. 环境

- 架构：Linux x86_64；
- SystemC：3.0.2；
- CIRCT fork 分支：`codex/systemc-backend`；
- 验证源码 revision：`1dc04c4e9`；
- 验证 Release：`systemc-backend-0.1.5`；
- Release 构建：GitHub Actions Ubuntu 24.04 x86_64，全部步骤通过；
- 输入：CIRCT Slang frontend 已展开的 `dsc_encoder` HW IR；
- 结构参考：UHDM `module_hierarchy.json`。

工具状态只能称为本任务已验证：本报告不推导其他 CIRCT backend 或其他 RTL 的可用性。

## 3. 过程

每个深度依次执行：

```text
hw-extract-hierarchy-slice
  → MLIR verifier
  → convert-hw-to-systemc=structure-only
  → ExportSystemC
  → C++ -fsyntax-only（SystemC headers）
  → manifest/HW/SystemC/UHDM 结构门禁
```

第一次真实设计复测发现，SV package 生成的顶层 `llhd.coroutine` 不属于任何 `hw.module`，
会残留在 structure-only 产物中。修复后，structure-only 收尾阶段只保留 SystemC 模块和必要
include；package function、LLHD coroutine 等行为 helper 不再泄漏到结构产物。对应 Lit 回归包含
一个顶层 `func.func` helper，验证它会被移除。

## 4. 结果

| depth | 保留模块定义 | frontier 模块 | 保留实例边 | SystemC 编译 | 结构门禁 |
|---:|---:|---:|---:|---|---|
| 0 | 1 | 1 | 0 | 通过 | 通过 |
| 1 | 8 | 7 | 7 | 通过 | 通过 |
| 2 | 16 | 8 | 31 | 通过 | 通过 |
| 3 | 27 | 11 | 43 | 通过 | 通过 |
| 4 | 47 | 20 | 66 | 通过 | 通过 |
| 5 | 50 | 3 | 89 | 通过 | 通过 |
| 6 | 50 | 0 | 89 | 通过 | 通过 |

depth 1 的七个直属实例为：

- `dsce_apb_inst` → `dsce_apb`；
- `dsce_command_inst` → `dsce_command`；
- `dsce_engine_inst` → `dsce_engine`；
- `dsce_interrupt_inst` → `dsce_interrupt`；
- `dsce_pps_inst` → `dsce_pps`；
- `dsce_reset_inst` → `dsce_reset`；
- `dsce_timers_inst` → `dsce_timers`。

以上实例名和定义名与 UHDM 参考逐项一致。depth 6 时 frontier 归零，50 个 CIRCT 参数特化后
模块定义和 89 条定义级实例边全部进入 SystemC 骨架。

开发构建的机器证据位于 `evidence/results/circt_hierarchy_peeling_x86/`。发布后二次验证没有使用
服务器工作区的 CIRCT，而是校验并解压 Release 压缩包，再用其中的三个工具重新执行 depth 0～6；
结果同样全部通过。Release 二次验证证据位于
`evidence/results/circt_hierarchy_peeling_release_0_1_5_x86/`。

## 5. 结论

当前 CIRCT fork 已能对真实 DSC 执行统一深度的层次剥离：未展开层的行为不会阻塞上层，展开层
的端口、实例、通道和绑定可以生成可编译 SystemC，并由 UHDM 辅助验证。这个结论只覆盖结构
和胶水连接，不表示 frontier 的算法、组合逻辑或时序逻辑已经实现。

可复用的 Linux x86_64 二进制发布于：
<https://github.com/chenaizhang/circt/releases/tag/systemc-backend-0.1.5>。

当前仍保留一个明确限制：同一模块定义的不同实例不能在同一次切片中设置不同深度。若后续需要
实例路径级非对称展开，必须先克隆共享模块定义并重写对应实例引用。
