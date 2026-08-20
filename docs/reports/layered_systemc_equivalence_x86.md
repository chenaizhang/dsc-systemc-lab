# 分层 Function 与 CIRCT SystemC 验证报告

## 1. 目的

本轮把工作拆成两条并行、最后汇合的路线：

1. 结构/功能参考线：UHDM 固化 RTL 层次，先验证无内部层次的顶层 Function-TLM，再把顶层功能按
   SystemC 模块层次逐层拆成子模块 function。
2. CIRCT 行为线：把 HW、Comb、Seq 分开处理；HW 只负责模块、端口、实例、信号和绑定，Comb/Seq
   再分别补组合与时序行为。

两条线的共同门禁是：语法可编译、结构与 UHDM 一致、相同输入的语义结果一致。编译成功不代替
功能正确。

## 2. 落地内容

### 2.1 UHDM 权威结构

`dscflow layered prepare` 同时读取模块端口表和完整 UHDM hierarchy JSON，生成：

- 261 个 elaborated 实例；
- 3,155 个具名端口绑定；
- 43 个模块定义的代表性子模块布局；
- generate scope 到合法且唯一 SystemC 名称的映射；
- 带 `DscFunctionSlot` 的层次化 SystemC 参考骨架；
- 按深度展开的 function 填充与语义对比计划。

生成骨架在 x86 上通过 SystemC C++ 编译、运行时 elaboration 和 systemc-clang。运行时观察到 261
个模块、3,243 个端口，与 UHDM 期望逐项一致；systemc-clang 对 43 个模块类型均返回 0。

### 2.2 CIRCT HW-only 后端

CIRCT fork 的 `convert-hw-to-systemc` 新增 `structure-only=true`：

```text
HW module/port/instance/SSA connection
  → systemc.module / input / output / signal
  → systemc.instance.decl / bind_port
  → 空 innerLogic SC_METHOD
  → SystemC C++
```

同时修复了三项 exporter 问题：

- 私有模块的 `sym_visibility` 被打印两次；
- 子模块实例没有传入 SystemC 实例名，导致无默认构造函数；
- 父模块先于子模块发射，以及 generate 实例名含点号，导致非法 C++。

真实 DSC 的结果为：

| 门禁 | 结果 |
|---|---:|
| CIRCT 模块定义 | 50 |
| 定义级 `hw.instance` | 89 |
| 生成 `SC_MODULE` | 50 |
| 生成子模块声明 | 89 |
| SystemC C++ 语法编译 | 通过 |
| SystemC 运行时 elaboration | 通过 |
| elaborated 模块实例 | 261 |
| 代表性 systemc-clang 目标 | 4/4 通过 |

CIRCT 的 50 个模块包含 9 个参数特化类型；UHDM 保留 43 个原始定义。两边定义级子模块边数均为
89，运行时展开后均为 261 个模块，因此 HW 骨架已形成可编译、可运行的闭环。CIRCT 把 aggregate
端口展开为标量端口，所以其运行时端口对象为 12,955 个，不能直接与 UHDM 的 3,243 个复合端口
做数量相等判断。

systemc-clang 直接读取完整 48 万字节头文件会超时。流程现在先按目标模块计算依赖闭包并生成精简
分析头文件；`dsce_apb`、`dsce_bpvector`、参数特化模块和 SRAM 特化模块均分析通过。完整层次由
运行时探针覆盖，而不是用静态工具超时结果代替。

### 2.3 Comb / Seq 状态

真实 core IR 已成功提取：

| 分区 | operation | 涉及模块 | 原生 SystemC 完成 |
|---|---:|---:|---|
| Comb | 16,412 | 42 | 否 |
| Seq | 540 | 36 | 否 |
| LLHD | 433 | 8 | 否 |

完整 `convert-hw-to-systemc` 当前首先停在 aggregate 的 `hw.bitcast`。因此这不是 HW 骨架失败；HW
已经单独成功，失败属于行为 lowering 入口。下一步应先补 aggregate bitcast，再按首个新失败依次
补 Comb emission 和 Seq/LLHD lowering。

### 2.4 Function 逐层细化

顶层 VESA Function-TLM 已在共享合成向量上与官方命令行模型逐字节一致，所以深度 0 为已验证。
当前更深层次不能诚实标为完成：

| 深度 | 实例数 | 已验证 function | 缺失 |
|---:|---:|---:|---:|
| 0 | 1 | 1 | 0 |
| 1 | 7 | 0 | 7 |
| 2 | 24 | 0 | 24 |
| 3 | 45 | 0 | 45 |
| 4 | 92 | 0 | 92 |
| 5 | 92 | 0 | 92 |

已有的 `CycleApb` 是 cycle-level SystemC，不是纯 function reference；流程已修正，今后不会因为它
编译和差分通过就把对应 function 标成完成。每个生成的 `DscFunctionSlot` 只是注入点，必须用父层
function 或对应 Comb/Seq 实现跑同输入差分后才能转成 `verified`。

## 3. 可复现入口

正式验证只在 x86 环境运行：

```bash
bash scripts/run_layered_equivalence_verification.sh
```

该命令依次执行 UHDM SystemC 结构验证、CIRCT HW/Comb/Seq 分阶段探针、Verilator 黑盒构建，并生成
路径脱敏的机器报告 `evidence/results/layered_systemc_equivalence_x86.json`。

## 4. 结论

- HW 可以生成 SystemC：真实 DSC 已通过转换、发射、C++ 编译和运行时 elaboration，261 个实例与
  UHDM 一致。
- Comb/Seq 还没有生成完整可执行行为：当前首个缺口是 `hw.bitcast`，后续 operation 必须按错误
  顺序继续补齐。
- 顶层 Function-TLM 已验证；逐层 function 拆解的框架、状态机和差分接口已经落地，但深度 1～5
  的模块行为尚缺少可验证实现。
- Verilator 的顶层、engine 和 APB SystemC 模型均可构建，可在 Comb/Seq 未完成时作为 cycle-level
  黑盒和差分参考；它不替代独立的 function golden。
