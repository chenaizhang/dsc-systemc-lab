# 当前 SystemC 工作交接说明

## 1. 交接结论

当前成果不是一个已经通过图像功能验证的 DSC SystemC 产品模型，而是一套可复现的
CIRCT SystemC 后端、完整顶层生成模型、RTL 对照模型和差分定位方法。

接手时必须区分三件事：

| 能力 | 当前状态 | 可以说明什么 |
|---|---|---|
| 定制 CIRCT Release | Linux x86_64 CI、回归和真实设计生成通过 | 工具可用于继续开发 |
| 完整 `dsc_encoder` 原生 SystemC | 50 模块、89 实例，C++ 编译通过 | 层次和代码生成闭环 |
| 图像行为 | 96×16 输入输出 0 字节 | **功能未通过，不能用于算法结果** |

相同 96×16 输入下，Verilator-SystemC RTL 基线输出 1536 字节，VESA 参考也是
1536 字节，但 RTL 从第 24 字节起已经与参考不同。因此：

- CIRCT 原生模型的“零输出”是转换路径新增的偏差；
- RTL 自身仍有功能差异，Verilator 只能作为 cycle-level 行为基线，不能代替独立 golden；
- 首个已定位的断流区间是 `predict` 之后、`format` 输出之前。

## 2. 仓库和固定版本

- 项目仓库：<https://github.com/chenaizhang/dsc-systemc-lab>
- 本次交接提交：`0444181`
- CIRCT fork：<https://github.com/chenaizhang/circt/tree/codex/systemc-backend>
- CIRCT revision：`fb0695bbcd33937d6e9c7cfc8a702065e997d708`
- Linux x86_64 Release：<https://github.com/chenaizhang/circt/releases/tag/systemc-backend-0.1.6>
- Release 标签 CI：<https://github.com/chenaizhang/circt/actions/runs/35331143893>

由私有 RTL 派生的 HW IR 和 6.9 MB SystemC 头文件不进入公开仓库，使用内部 Linux 打包的
`dsc-systemc-current-handoff-20260919-linux-x86_64.tar.gz` 传递。
本次实测包 SHA-256 为
`0bd9792067e6d4c523c8391caefc9e7c7c018b58697401bb8976b94da0b3dfb1`。

## 3. 交接包内容

```text
dsc-systemc-current-handoff-20260919-linux-x86_64/
├── README_ZH.md
├── CMakeLists.txt
├── SHA256SUMS
├── generated/
│   └── depth_6.systemc.hpp
├── ir/
│   └── dsc_encoder.hw.mlir
├── tests/
│   ├── native_image_differential.cpp
│   └── data/
│       ├── deterministic_rgb.ppm
│       └── deterministic_rgb.dsc
├── scripts/
│   └── verify_known_status.sh
├── evidence/
│   └── validation.json
└── reports/
    └── circt_native_image_differential_x86_zh.md
```

固定产物哈希：

- HW IR：`a7b6b6114ede3429baff8129318813022ad99918f9cc2a0e3147f68be0d9c355`；
- SystemC：`3d0b20f923b2970da22ee793459e00fb477e8d8059306006b1a4930d547c32a9`。

## 4. 接手人先做什么

仅支持 Linux x86_64 正式验证。先安装 CMake、C++17 编译器、pkg-config 和 SystemC 3.x，
然后执行：

```bash
tar -xzf dsc-systemc-current-handoff-20260919-linux-x86_64.tar.gz
cd dsc-systemc-current-handoff-20260919-linux-x86_64
sha256sum -c SHA256SUMS
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build --parallel 2
```

这一步成功只代表现有 SystemC 可以在接手机器重新编译。要复现当前已知行为状态，再执行：

```bash
bash scripts/verify_known_status.sh build
```

脚本预期原生模型收完 1536 像素、输出 0 字节，并把这个**已知功能失败**判为复现成功。
如果模型输出不再为 0，说明行为发生变化，应重新与 RTL 和 VESA 参考比较，不能继续沿用旧结论。

## 5. 从源码重新生成

公开仓库中的主入口为：

```bash
export DSCFLOW_CIRCT_ROOT=/path/to/circt-systemc-release
export DSCFLOW_VESA_ROOT=/path/to/DSC_model_20211213
scripts/run_native_image_differential_x86.sh
```

不设置 `DSCFLOW_NATIVE_HW_IR` 时，脚本从 SV 重新生成 HW IR。当前这一模式会在
`dsce_stream_fifo` 的 `seq.to_clock` 合法化失败；不同抽取结果中观察到少数 `llhd.wait`
事件和后继参数次序变化。

只复测已经固定的 IR 时：

```bash
export DSCFLOW_NATIVE_HW_IR=/path/to/dsc_encoder.hw.mlir
scripts/run_native_image_differential_x86.sh
```

固定 IR 路径会生成相同 SystemC 哈希并复现 format 前断流。两个门禁必须分别保留：

1. SV → HW IR → SystemC 的重建稳定性；
2. 固定 IR → SystemC 的逐周期语义正确性。

## 6. 下一步开发顺序

1. 对 `predict → rate/decision/VLC → format` 增加逐周期 RTL/SystemC 端口差分；
2. 找到第一个不同的 valid、ready、last、状态寄存器或 SSA 值；
3. 把差异缩成最小 CIRCT 测试，修 conversion/pass/emitter；
4. 修复 `seq.to_clock` 重建不稳定问题；
5. 先重跑 96×16，再跑 192×108；
6. 原生 SystemC 与 RTL 逐周期一致后，再以 VESA golden 判断算法功能。

详细证据见：

- `docs/reports/circt_native_image_differential_x86_zh.md`；
- `evidence/results/circt_native_image_x86/validation.json`；
- `docs/reports/current_progress_zh.md`。

## 7. 不要误用的内容

- 旧的 6,955,310 字节头文件来自常零同步器/RAM 空壳，只能验证结构和编译；
- `.a` 静态库不能跨系统传递，接手方必须从源码重建；
- UHDM 对比只证明层次，不证明行为；
- C++ 编译通过不证明 cycle-level 语义；
- 与 Verilator 一致不证明 RTL 与 VESA golden 一致。
