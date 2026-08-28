# CIRCT/Verilator 混合 SystemC 交接包验证报告

## 1. 目的

验证交接工程能否在全新的 x86_64 Linux 构建目录中，仅依赖随包源码和本机工具完成：

1. 从展平后的 SystemVerilog 重新生成 Verilator C++ 叶子模型；
2. 编译 CIRCT 导出的 SystemC 容器和模块间胶水逻辑；
3. 正确连接 packed 宽端口；
4. 避免空壳 CDC 原语破坏同步行为；
5. 完成链接、SystemC elaboration 和最小运行测试。

## 2. 构建方式

交接包不包含 `.a`、`.o` 或其他预编译目标。执行：

```bash
bash verify.sh . build /path/to/systemc/cmake
```

脚本依次执行 CMake configure、源码构建和 CTest，并将工具版本与日志写入
`verification/`。

## 3. x86 实测结果

| 检查项 | 结果 | 证据 |
|---|---|---|
| manifest 中选择的 Verilator 子模块从 SV 生成 | 通过 | `generated/source_manifest.json` 与 CMake build 日志 |
| CIRCT SystemC 容器编译 | 通过 | `mixed_systemc_smoke` 构建成功 |
| SystemC 与 Verilator 链接 | 通过 | `mixed_systemc_smoke` 链接成功 |
| packed 宽端口 ABI | 通过 | `circt_systemc_verilator_wide.h` 参与真实编译 |
| SystemC elaboration/零时间运行 | 通过 | `MIXED_SYSTEMC_SMOKE=PASS` |
| 单级、双级 CDC 同步延迟 | 通过 | `CDC_SHIM_TEST=PASS` |
| CTest | 2/2 通过 | `verification/ctest.log` |

CIRCT 还会把共享 packed 表达式物化为局部值，避免相同表达式树在多个使用点被递归展开，
从而控制生成头文件大小和 C++ 编译内存占用。

## 4. 结论与边界

该交接包已经达到“从源码可重建、可编译、可链接、可运行”的混合 SystemC 最小闭环，解决了
空壳同步器、packed ABI 不一致和跨操作系统预编译库不可复用三类问题。

本报告不等同于图像压缩算法功能正确性证明。当前包没有共享的正式图像 stimulus 与独立
golden 输出，因此没有执行端到端码流差分；后续仍需在同一输入下与独立软件 golden 以及完整
RTL/Verilator 参考逐周期比对。
