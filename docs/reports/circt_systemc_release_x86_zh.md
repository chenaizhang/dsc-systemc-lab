# CIRCT SystemC Linux x86_64 Release 0.1.5 验证报告

## 目的

验证定制 CIRCT 能否在干净 Linux x86_64 环境构建为可分发工具，并使用发布包而非开发构建，
对真实 `dsc_encoder` 执行逐层结构剥离、SystemC 导出、编译和 UHDM 对照。

## 输入与环境

- 源码分支：`codex/systemc-backend`
- 源码修订：`1dc04c4e9858d00d5820c417d64db26a6fd9322b`
- CI 环境：Ubuntu 24.04 x86_64
- 工具：Clang、CMake、Ninja、Verilator、SystemC
- CI 记录：<https://github.com/chenaizhang/circt/actions/runs/33615733872>
- Release：`systemc-backend-0.1.5`
- 实验机：Linux x86_64，SystemC 3.0.2

## 实测结果

| 检查项 | 结果 |
|---|---|
| `circt-verilog`、`circt-opt`、`circt-translate` 构建 | 通过 |
| HW-to-SystemC、SystemC dialect、ExportSystemC 回归 | 27/27 通过 |
| 标量端口 Verilator interop | 生成、编译、链接、运行通过 |
| packed struct/array 展平端口 interop | 生成、编译、链接、运行通过 |
| Release SHA-256 | 下载后本地校验通过 |
| Release 内容 | 三个工具、LICENSE、README、BUILD_INFO 齐全 |
| 层次剥离 pass | Release 中存在，能够直接调用 |
| `dsc_encoder` depth 0～6 | 逐级导出 SystemC 并通过 C++ 语法编译 |
| UHDM 顶层范围 | 7/7 个直属子模块名称和定义完全一致 |
| 完整结构 | 50 个特化模块、89 条实例边全部进入 SystemC 骨架 |

depth 0～6 的模块、frontier 和实例边数量依次为：

| depth | 模块 | frontier | 实例边 | 结果 |
|---:|---:|---:|---:|---|
| 0 | 1 | 1 | 0 | 通过 |
| 1 | 8 | 7 | 7 | 通过 |
| 2 | 16 | 8 | 31 | 通过 |
| 3 | 27 | 11 | 43 | 通过 |
| 4 | 47 | 20 | 66 | 通过 |
| 5 | 50 | 3 | 89 | 通过 |
| 6 | 50 | 0 | 89 | 通过 |

## 对旧问题的复查

- 顶层 package helper 泄漏：structure-only 收尾会移除模块外的行为 helper，真实设计不再被
  `llhd.coroutine` 阻塞。
- 只能一次性处理整个层次：新增按最大深度切片的 pass，边界模块自动变为可编译的行为插槽。
- 层次靠脚本猜测：新增 JSON manifest，并同时对照 HW IR、SystemC 和 UHDM。
- 只验证开发目录：本轮完整实验直接使用 Release 压缩包中的工具，排除了未发布补丁的影响。

depth 1 明确保留 `dsc_encoder` 及其 7 个直属子模块；depth 6 时 frontier 归零。每个深度均依次
通过切片后的 MLIR 校验、HW-to-SystemC structure-only 转换、SystemC IR 校验、ExportSystemC、
SystemC C++ 语法编译和结构门禁。

## 结论与边界

CIRCT SystemC 定制工具已达到 Linux x86_64 上可下载、可校验、可执行的交付状态；真实
`dsc_encoder` 的逐层剥离、结构范围检查、SystemC 生成和 C++ 编译门禁均已通过。

这里验证的是“CIRCT 能按层次拆分并生成可编译的 SystemC 结构”。frontier 的行为插槽仍是空壳，
本轮没有验证 Comb/Seq 行为、图像刺激或参考码流，不能据此宣称压缩算法输出正确。

## 交付

- Release：<https://github.com/chenaizhang/circt/releases/tag/systemc-backend-0.1.5>
- 源码分支：<https://github.com/chenaizhang/circt/tree/codex/systemc-backend>
- 调用流程：<https://github.com/chenaizhang/dsc-systemc-lab/blob/main/docs/handoffs/image_ip_systemc_pipeline_zh.md>
- 机器证据：`evidence/results/circt_hierarchy_peeling_release_0_1_5_x86/`
