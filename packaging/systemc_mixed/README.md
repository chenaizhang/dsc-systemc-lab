# 可移植 SystemC 混合集成源码包

本工程不使用随包附带的预编译 `.a`。CMake 会在当前机器上重新运行 Verilator，使用
`generated/interop_<模块名>.sv` 为每个叶子模块生成普通 C++ 模型，再与 CIRCT 导出的
SystemC 容器一起编译和链接。

## 依赖

- x86_64 Linux；
- CMake 3.20 或更高版本；
- 支持 CMake package 的 Verilator；
- SystemC 的 CMake package 或 `pkg-config` 元数据；
- 支持 C++20 的编译器。

如果工具不在标准位置，可通过 `VERILATOR_ROOT` 和 `CMAKE_PREFIX_PATH` 提供安装根目录，
不要把机器私有路径写入本工程。

## 构建与测试

```bash
cmake -S . -B build -G Ninja \
  -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_PREFIX_PATH=/path/to/systemc/lib/cmake/SystemCLanguage
cmake --build build --parallel 2
ctest --test-dir build --output-on-failure
```

也可以执行包内脚本，它会把工具版本和三阶段日志保存到 `verification/`：

```bash
bash verify.sh . build /path/to/systemc/lib/cmake/SystemCLanguage
```

验收包括：

1. `cdc-shim`：验证单级和双级同步器的采样延迟；
2. `mixed-systemc-smoke`：重新生成所有 Verilator 叶子，编译、链接并零时间运行 CIRCT
   SystemC 容器，覆盖真实的跨工具端口 ABI。

## 生成目录

以下文件由交接包生成器提供：

```text
generated/interop_<模块名>.sv
generated/mixed_systemc.hpp
generated/interop_modules.cmake
tests/mixed_systemc_smoke.cpp
```

每个 `interop_<模块名>.sv` 都由 CIRCT 在 `hw-flatten-io` 后，将该叶子设为唯一 public
入口并执行 `symbol-dce`、LLHD/Seq lowering 后独立导出。Verilator 编译这些文件而不是
原始聚合端口 RTL，因此生成的 C++ 成员名与 SystemC 容器完全一致；packed struct/array
的 pack/unpack 由 CIRCT 生成的 HDL 连接表达式承担。
