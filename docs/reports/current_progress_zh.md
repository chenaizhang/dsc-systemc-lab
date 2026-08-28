# 当前落地进度与阻塞项

## 已完成

1. 顶层软件参考：VESA C model、C++ adapter、Function-TLM 在 x86 上输出一致。
2. UHDM 权威结构：261 个实例、3,243 个端口、3,155 个具名绑定；运行时探针和 43 个
   systemc-clang 目标全部通过。
3. 分层 Function 框架：从 UHDM 生成同构 SystemC module、channel、绑定和 `DscFunctionSlot`，并按
   深度生成填充/差分计划。
4. CIRCT HW-only：fork 新增 `structure-only=true`，真实 DSC 生成 50 个 `SC_MODULE`、89 条定义级
   实例边，C++ 编译和运行时 elaboration 通过，展开后同样为 261 个实例。
5. CIRCT 静态分析：代表性普通模块、参数特化模块和 SRAM 特化模块经依赖闭包裁剪后通过
   systemc-clang。
6. CIRCT 行为清单：提取 Comb 16,412、Seq 540、LLHD 433 个 operation，并保存每一阶段机器证据。
7. Verilator 兜底：`dsc_encoder`、`dsce_engine`、`dsce_apb` 的 SystemC/C++ 模型均可构建。
8. 混合差分基础：单体 Verilator、拆分网络和 `CycleApb` 替换网络已有逐周期差分能力。
9. 深度 1 Function：7 个直属模块均已有 transaction-level SystemC function，并与扁平 Function-TLM
   及官方 VESA 向量完成 x86 字节级差分。
10. CIRCT 行为推进：6 个 timed process、4 个 combinational process 已降到 Core；原
    `hw.bitcast` 首错已消除，新首错为 `sim.fmt.literal`。
11. 完整顶层混合模型：CIRCT 生成 `dsc_encoder` 顶层 SystemC 胶水，UHDM 核对的 7 个直属
    子模块全部通过 Verilator interop 从源码构建；x86 C++ 编译、链接及 CTest 2/2 通过。

## 尚未完成

1. 深度 2～5 的模块级 function model 尚未逐层实现和验证；顶层与深度 1 已通过。
2. CIRCT 完整 Comb/Seq 行为尚未发射为可运行 SystemC；当前被仿真诊断操作
   `sim.fmt.literal`/`sim.print` 阻塞。
3. 因 Comb/Seq 尚未形成 candidate，底层 function 与 CIRCT 行为的逐模块语义对齐尚未开始。
4. 参考 RTL 与 VESA golden 仍存在最终码流差异，format/stream 的 line-last/flush 路径仍需修正。

完整顶层混合模型通过的是结构、ABI、编译链接和最小运行门禁，不包含独立图像 golden 差分；
它与“全原生 Comb/Seq 已完成”是两件不同的事。

## 为什么这些项不能标成完成

- `DscFunctionSlot` 是行为注入点，不是 function 实现。
- `CycleApb` 是 cycle-level 模型，不是独立的纯 function reference。
- HW 骨架能编译只证明结构闭环，不证明 Comb/Seq 或图像压缩语义。
- Verilator 忠实执行现有 RTL，RTL 中的功能错误也会保留，因此不能替代 VESA golden。

## 下一顺序

```text
实现 sim.fmt.literal / sim.print 的 SystemC lowering
  → 重新运行完整转换并记录下一个 Comb/Seq emission 缺口
  → 从深度 2 开始逐层实现 function 合同与模型
  → 每层与父级 function 做端到端同输入差分
  → 自底向上把 function 与 CIRCT Comb/Seq SystemC 对齐
  → 逐模块替换 Verilator 黑盒
  → 最终与 VESA golden 比较完整压缩输出
```

完整数字和复现命令见 `docs/reports/layered_systemc_equivalence_x86.md`。
