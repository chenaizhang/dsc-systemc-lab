# 可移植 SystemC 混合集成交付整改

## 目标

把 DSC 的 SystemC 交付从“部分产物可生成”整改为可在全新 x86 Linux 目录从源码复现的工程：

1. CIRCT 和 Verilator frontend 均用有行为的同步器仿真 shim 替换交付 RTL 中的空壳 primitive；
2. Verilator interop 使用 CIRCT 展平后的 SystemVerilog 作为叶子模型输入，使 packed struct/array
   自动转换为与 SystemC 容器一致的标量 ABI；
3. 交付顶层 CMake 和 CTest，不把预编译 `.a` 当作跨平台依赖；
4. 在全新 x86 Linux 目录执行 configure、build、CDC 测试和混合模型 smoke test；
5. 重新生成只包含源码、构建脚本、必要 IR/证据和测试的 Linux 压缩包。

## 修改边界

- 私有参考 RTL 不修改；通过明确的 source overlay 替换空壳 primitive；
- UHDM 仍是层次、端口、实例和绑定参考，不承担行为正确性证明；
- CIRCT 展平 SystemVerilog只解决跨工具端口 ABI，不改变叶子模块功能；
- Verilator 模型只能证明与输入 RTL 行为一致，独立算法正确性仍需软件 golden；
- 正式 EDA 结论只来自 x86_64 服务器。

## 验收条件

- CDC shim 单级和双级同步延迟测试通过，且模型生成记录证明使用了 shim；
- CIRCT 生成的叶子 SystemVerilog端口与混合 SystemC 访问的成员完全一致；
- 不再出现 `cfg_dsc_encoder_follow_vsync` 等 packed ABI 成员缺失错误；
- 新交付目录不依赖包内 `.a`，CMake 在目标环境重新运行 Verilator 并编译全部模型；
- `cmake --build` 和 `ctest --output-on-failure` 在全新 x86 Linux 目录通过；
- 压缩包在 Linux 创建并完成解压、文件数、UTF-8 和 SHA-256 检查。

## 基线

- 公开流程仓库基线：`4a4eddd34257065ebdfde7b2451bacd239c01234`；
- CIRCT 修复分支基线：`7e316ee0ee11f2cb187b65260feff3f871370e69`；
- 当前环境没有 `eda-harness` 可执行文件，因此用干净 Git 状态和上述提交哈希锁定基线；
  最终仍执行项目原生测试和全新 x86 CMake/CTest 门禁。
