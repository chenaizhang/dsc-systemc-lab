# CIRCT SystemC Linux x86_64 Release 验证报告

## 目的

验证定制 CIRCT 能否在干净 Linux x86_64 环境构建为可分发工具，并复查交接中曾发现的
Verilator interop、packed 聚合端口和 SystemC 编译问题。

## 输入与环境

- 源码分支：`codex/systemc-backend`
- 源码修订：`547f06ebe6aa5ebef507ee78089310049118e656`
- CI 环境：Ubuntu 24.04 x86_64
- 工具：Clang、CMake、Ninja、Verilator、SystemC
- CI 记录：<https://github.com/chenaizhang/circt/actions/runs/33087269020>

## 实测结果

| 检查项 | 结果 |
|---|---|
| `circt-verilog`、`circt-opt`、`circt-translate` 构建 | 通过 |
| HW-to-SystemC、SystemC dialect、ExportSystemC 回归 | 27/27 通过 |
| 标量端口 Verilator interop | 生成、编译、链接、运行通过 |
| packed struct/array 展平端口 interop | 生成、编译、链接、运行通过 |
| Release SHA-256 | 下载后本地校验通过 |
| Release 内容 | 三个工具、LICENSE、README、BUILD_INFO 齐全 |

混合仿真日志最终输出：

```text
verilated mixed SystemC scalar and aggregate tests: PASS
```

## 对旧问题的复查

- packed ABI 不匹配：已在引擎级交接包和 CIRCT Release 的聚合端口测试中通过。
- SystemC 只能导出顶层空壳：当前门禁会把导出的容器与 Verilator 叶子实际编译链接并运行。
- CDC 空壳：DSC 流程已强制使用可执行 shim，并有单级、双级脉冲测试；该测试属于 DSC 项目证据，不是 CIRCT 通用 Release 的语义。
- 顶层范围误标：流程现在用 UHDM 强制检查 `conversion_top=dsc_encoder`，且 7 个直属子模块与选择的 interop 模块完全一致。

## 结论与边界

CIRCT SystemC 定制工具已达到 Linux x86_64 上可下载、可校验、可执行的交付状态，
相关 SystemC 回归和 Verilator 混合样例均通过。

这不等于完整私有 `dsc_encoder` 已经转换和图像数据差分通过。当前内网 x86 服务器
无网络响应，且私有 RTL 不上传公开 CI，因此完整 encoder 门禁仍需服务器恢复后执行。

## 交付

- Release：<https://github.com/chenaizhang/circt/releases/tag/systemc-backend-0.1.3>
- 源码分支：<https://github.com/chenaizhang/circt/tree/codex/systemc-backend>
- 调用流程：<https://github.com/chenaizhang/dsc-systemc-lab/blob/main/docs/handoffs/image_ip_systemc_pipeline_zh.md>
