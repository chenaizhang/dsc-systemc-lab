# CIRCT 全层次行为 SystemC x86 验证报告

## 目的

验证定制 CIRCT 是否已经从“只生成 HW 层次骨架”推进到能够处理真实图像压缩 RTL 中的
Comb、基础 Seq、聚合反馈和存储，并输出可由 SystemC C++ 编译器接受的完整层次代码。

## 环境与输入

- 验证环境：Linux x86_64；
- CIRCT 分支：`codex/systemc-backend`；
- CIRCT revision：`fb0695bbcd33937d6e9c7cfc8a702065e997d708`；
- 输入：Slang frontend 已展开的 `dsc_encoder` HW IR；
- 模式：`DSCFLOW_SYSTEMC_MODE=behavior`；
- SystemC：3.0.1；
- 验证日期：2026-09-18。

## 本轮修复

### 聚合临时反馈

前端会把“先声明数组、随后逐元素完整赋值”的临时变量表示成反馈图。旧转换会把它当成真实
组合环，导致 SSA 支配错误或转换无法收敛。本轮新增位级依赖分析：只有证明所有输出位在一轮
更新中均不再依赖旧值时，才以零值断开临时反馈。部分更新保持不变，以免把 latch 或真实组合
环错误删除。

同时，常量下标的 `hw.array_inject` 改为只重建一个目标数组，避免旧动态实现为每个候选下标
构造整行数据所造成的二次方 IR 膨胀。

### Comb C++ 发射规模

ExportSystemC 会把 Comb SSA 递归打印为 C++ 表达式。存在扇出和重汇合时，即使每个 SSA 值只有
一个直接使用者，最终文本仍可能指数增长。本轮在 HW-to-SystemC 结束后把每个整数 Comb 结果
物化为一个有名字的 C++ 局部变量，使输出规模与 IR 规模近似线性。

## 验证过程

发布回归覆盖以下 35 项：

- 层次切片；
- 聚合转 Comb；
- HW-to-SystemC；
- LLHD timed process；
- Seq register-vector-to-memory；
- SystemC dialect；
- ExportSystemC。

此外分别编译并运行：

- 存储器 SystemC 测试；
- 寄存器、时钟和复位 SystemC 测试；
- `SC_THREAD + wait()` 测试；
- 标量及 packed 聚合端口的 Verilator interop 测试；
- 同时包含层次、Comb、Seq、复位和 memory 的小型端到端样本。

真实设计使用以下流程：

```text
dsc_encoder HW IR
  → 深度 6 层次切片
  → LLHD/Core 准备
  → 聚合转 Comb
  → HW/Comb/Seq 转 SystemC dialect
  → ExportSystemC
  → c++ -std=c++17 -fsyntax-only
```

在已安装 CIRCT 构建、SystemC 和输入 HW IR 的 x86 环境中，可按以下命令复现核心门禁：

```bash
export DSCFLOW_CIRCT_ROOT=/path/to/circt/build
export DSCFLOW_CIRCT_LIBRARY_PATH="$DSCFLOW_CIRCT_ROOT/lib"
export DSCFLOW_SYSTEMC_MODE=behavior

scripts/run_circt_hierarchy_peeling.sh \
  /path/to/dsc_encoder.hw.mlir dsc_encoder 6 \
  .work/dsc-depth-6
c++ -std=c++17 -x c++ -fsyntax-only \
  $(pkg-config --cflags systemc) \
  .work/dsc-depth-6/depth_6.systemc.hpp
cat .work/dsc-depth-6/depth_6.verification.json
```

发布回归命令为：

```bash
build/bin/llvm-lit -sv \
  test/Dialect/HW/extract-hierarchy-slice.mlir \
  test/Dialect/HW/hw-aggregate-to-comb.mlir \
  test/Conversion/HWToSystemC \
  test/Dialect/LLHD/Transforms/lower-timed-processes.mlir \
  test/Dialect/Seq/reg-of-vec-to-mem.mlir \
  test/Dialect/SystemC \
  test/Target/ExportSystemC
```

## 结果

| 检查项 | 结果 |
|---|---|
| 完整发布 Lit 集合 | 35/35 通过 |
| 仓库 Python 测试 | 49/49 通过 |
| 小型层次 Comb/Seq/Memory 运行 | 通过 |
| 内存运行 | 通过 |
| 寄存器/复位运行 | 通过 |
| `SC_THREAD + wait()` 运行 | 通过 |
| Verilator 标量及聚合混合运行 | 通过 |
| 真实设计保留模块 | 50 |
| 真实设计保留实例边 | 89 |
| 深度 6 frontier | 0 |
| 生成 SystemC 头文件 | 6,955,310 字节 |
| 生成 C++ 语法编译 | 通过 |
| 同 revision 干净 CI 构建 | [通过](https://github.com/chenaizhang/circt/actions/runs/35328105544) |
| CI 二进制包 SHA-256 校验及 x86 执行 | 通过 |
| CI 二进制包重跑真实设计深度 6 和 C++ 编译 | 通过 |
| CI 包与开发构建的生成头文件 SHA-256 | 一致：`00e38bd48f024882416b8e449cdc94dfd5da09f2d9973b35187980c00ea6dc77` |

## 结论与边界

真实 `dsc_encoder` 已经能够完成全层次行为转换并输出可编译 SystemC，不再局限于空的 HW
模块骨架。Comb、基础寄存器/时钟/复位、受支持存储和聚合胶水均有独立或端到端运行证据。

这仍不是图像压缩功能正确性的最终证明。当前尚未把真实图像测试数据送入本轮生成模型并与
参考码流比较，也没有完成每个模块的逐周期差分。转换日志中保留的前端顺序反馈警告必须通过
上述语义验证消除风险。因此准确结论是“转换和编译闭环完成，代表性行为通过”，而不是“完整
压缩算法已经与参考实现等价”。

机器可读证据位于 `evidence/results/circt_full_behavior_x86/`。
