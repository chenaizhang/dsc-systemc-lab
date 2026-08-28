# CIRCT SystemC Linux x86_64 Release 验证报告

## 目的

验证定制 CIRCT 能否在干净 Linux x86_64 环境构建为可分发工具，并复查交接中曾发现的
Verilator interop、packed 聚合端口和 SystemC 编译问题。

## 输入与环境

- 源码分支：`codex/systemc-backend`
- 源码修订：`5fff1f154467ade9a004d00284e76e78e7c09b02`
- CI 环境：Ubuntu 24.04 x86_64
- 工具：Clang、CMake、Ninja、Verilator、SystemC
- CI 记录：<https://github.com/chenaizhang/circt/actions/runs/33152804209>

## 实测结果

| 检查项 | 结果 |
|---|---|
| `circt-verilog`、`circt-opt`、`circt-translate` 构建 | 通过 |
| HW-to-SystemC、SystemC dialect、ExportSystemC 回归 | 27/27 通过 |
| 标量端口 Verilator interop | 生成、编译、链接、运行通过 |
| packed struct/array 展平端口 interop | 生成、编译、链接、运行通过 |
| Release SHA-256 | 下载后本地校验通过 |
| Release 内容 | 三个工具、LICENSE、README、BUILD_INFO 齐全 |
| 完整 `dsc_encoder` 混合 SystemC | x86 源码重建、编译、链接和运行通过 |
| UHDM 顶层范围 | 7/7 个直属子模块与 interop 选择完全一致 |
| DSC CTest | 2/2 通过（顶层 smoke、CDC shim） |

混合仿真日志最终输出：

```text
verilated mixed SystemC scalar and aggregate tests: PASS
```

## 对旧问题的复查

- packed ABI 不匹配：已在引擎级交接包和 CIRCT Release 的聚合端口测试中通过。
- SystemC 只能导出顶层空壳：当前门禁会把导出的容器与 Verilator 叶子实际编译链接并运行。
- CDC 空壳：DSC 流程已强制使用可执行 shim，并有单级、双级脉冲测试；该测试属于 DSC 项目证据，不是 CIRCT 通用 Release 的语义。
- 顶层范围误标：流程现在用 UHDM 强制检查 `conversion_top=dsc_encoder`，且 7 个直属子模块与选择的 interop 模块完全一致。

完整顶层实测使用 `dsc_encoder` 作为容器，不再以 `dsce_engine` 冒充 encoder。生成头文件包含唯一的
`SC_MODULE(dsc_encoder)`，并实例化 `Vdsce_reset`、`Vdsce_apb`、`Vdsce_timers`、
`Vdsce_interrupt`、`Vdsce_pps`、`Vdsce_command` 和 `Vdsce_engine`。生成头文件约 80 KiB；
所有 Verilator 模型均由交接包的 CMake 在目标机从源码重新生成，没有复用跨平台 `.a`。

本轮还修复了两个真实顶层才会触发的 CIRCT 问题：

1. Verilator interop 是 `SC_METHOD` 中的可执行更新，不应像原生 `hw.instance` 一样跳过输入依赖排序；
2. 多次使用的一位 packed 表达式必须物化为原生 `bool`，不能先变成 `sc_bv<1>` 再生成非法的
   `bool(sc_bv<1>)`。

## 结论与边界

CIRCT SystemC 定制工具已达到 Linux x86_64 上可下载、可校验、可执行的交付状态；完整私有
`dsc_encoder` 的结构范围检查、SystemC 生成、C++ 编译链接和运行门禁也已通过。

这里验证的是“完整顶层混合模型可构建、可 elaboration、CDC shim 可运行”。测试包没有共享的
图像刺激与独立参考码流，因此本轮没有执行图像功能差分，不能据此宣称压缩算法输出正确。

## 交付

- Release：<https://github.com/chenaizhang/circt/releases/tag/systemc-backend-0.1.4>
- 源码分支：<https://github.com/chenaizhang/circt/tree/codex/systemc-backend>
- 调用流程：<https://github.com/chenaizhang/dsc-systemc-lab/blob/main/docs/handoffs/image_ip_systemc_pipeline_zh.md>
