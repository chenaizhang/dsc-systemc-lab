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
6. CIRCT 行为清单：提取 Comb 16,412、Seq 540、LLHD 433 个 operation，保留首个失败
   `hw.bitcast` 的机器证据。
7. Verilator 兜底：`dsc_encoder`、`dsce_engine`、`dsce_apb` 的 SystemC/C++ 模型均可构建。
8. 混合差分基础：单体 Verilator、拆分网络和 `CycleApb` 替换网络已有逐周期差分能力。

## 尚未完成

1. 深度 1～5 的模块级 function model 尚未逐层实现和验证；当前仅顶层 function 通过。
2. CIRCT 完整 Comb/Seq 行为尚未发射为可运行 SystemC；当前先被 aggregate `hw.bitcast` 阻塞。
3. 因 Comb/Seq 尚未形成 candidate，底层 function 与 CIRCT 行为的逐模块语义对齐尚未开始。
4. 参考 RTL 与 VESA golden 仍存在最终码流差异，format/stream 的 line-last/flush 路径仍需修正。

## 为什么这些项不能标成完成

- `DscFunctionSlot` 是行为注入点，不是 function 实现。
- `CycleApb` 是 cycle-level 模型，不是独立的纯 function reference。
- HW 骨架能编译只证明结构闭环，不证明 Comb/Seq 或图像压缩语义。
- Verilator 忠实执行现有 RTL，RTL 中的功能错误也会保留，因此不能替代 VESA golden。

## 下一顺序

```text
修复 CIRCT aggregate hw.bitcast
  → 重新运行完整转换并记录下一个 Comb/Seq 缺口
  → 同时实现深度 1 的 7 个 function 合同与模型
  → 每层与父级 function 做端到端同输入差分
  → 自底向上把 function 与 CIRCT Comb/Seq SystemC 对齐
  → 逐模块替换 Verilator 黑盒
  → 最终与 VESA golden 比较完整压缩输出
```

完整数字和复现命令见 `docs/reports/layered_systemc_equivalence_x86.md`。
