# 原生 CIRCT SystemC 图像差分测试（x86）

## 目的

验证完整 `dsc_encoder` 经 CIRCT 的 HW/Comb/Seq 行为转换后，不仅能生成并编译 SystemC，
还能接收图像并输出与参考软件模型一致的 DSC 码流；如失败，用同输入 RTL 基线定位首个分叉。

## 输入和方法

- 环境：Linux x86_64、SystemC 3.0.1、CIRCT `fb0695bbcd33937d6e9c7cfc8a702065e997d708`；
- 使用 `96×16` RGB PPM，1 个 96 像素宽 slice；VESA DSC C 参考模型和仓库适配器对
  1536 字节码流逐字节自检通过；
- 复测既有 `192×108` 图像：VESA 参考载荷为 20,736 字节，同输入 RTL 基线输出
  20,304 字节，不等于参考答案；
- 原生 SystemC 和 Verilator-SystemC RTL 基线使用同一 PPS/APB 写序列、3:1 DSC/AXI
  时钟比、帧/行标记和四像素一拍输入；
- 前端输入以 `dsc_support_primitives.sv` 中有寄存器和存储行为的仿真原语代替原文件表的
  空壳原语；跳过未实例化且不能解析的 `dsce_quant.sv`。本次 HW IR 中包含
  `seq.firreg` 和 `seq.firmem`，不能再把空壳原语当成功能验证输入。

生成的 HW IR SHA-256 为
`a7b6b6114ede3429baff8129318813022ad99918f9cc2a0e3147f68be0d9c355`。
深度 6 转换保留 50 个模块、89 条实例边、0 个 frontier，结构验证通过；SystemC 头文件
6,960,190 字节，SHA-256 为
`3d0b20f923b2970da22ee793459e00fb477e8d8059306006b1a4930d547c32a9`，
C++ 编译通过。独立的发布标签构建也已[完成且通过](https://github.com/chenaizhang/circt/actions/runs/35331143893)。

## 结果

| 检查项 | 原生 CIRCT SystemC | 同 RTL 的 Verilator-SystemC | VESA 参考 |
|---|---:|---:|---:|
| `96×16` 输入像素 | 1536 个全部接收 | 1536 个全部接收 | 1536 个 |
| 最终有效载荷 | **0 字节** | 1536 字节 | 1536 字节 |
| 与参考首差异 | 第 0 字节 | 第 24 字节 | 无 |
| 第一拍输出 | 1980 周期内没有 | 第 611 个 AXI 周期 | 不适用 |

原生模型运行正常退出，不是编译错误、SystemC 启动失败或运行超时。顶层命令为 `3`，
`encoder_active=1`，AXI/DSC 编码使能均为 `1`。以 DSC 时钟边沿采样，直到第 957 个
AXI 周期，数据流各级 valid 计数为：

```text
pack 1152 → partition 1149 → slice 输入 1149 → convert 1140
→ slice buffer 285 → flatness 278 → predict 277
→ format 输出 0 → slice 输出 0 → mux 输出 0
```

这些计数是 3:1 时钟下的采样次数，不是独立事务数。RTL 基线的 pack、partition、
convert 接收各约 384 拍，predict 有 256 个有效周期，format/mux 后能够出码流。
因此已排除“测试没有输入”“命令未启动”“顶层层次/连线缺失”以及“pack 或 partition
完全不工作”。**首个已观测到的缺失 valid 边界在 predict 之后、format 输出之前**；
这尚不能唯一指认是 rate、VLC、format 的哪个具体算子或哪个时序条件。

## 从源码重复转换的稳定性

另一次用同一前端命令、同一 RTL filelist 和原语 shim 重新生成 HW IR，得到不同的
SHA-256：`9264c9ae870b42c8cd521a833cfc91a18b9d81ae6da375a6a7d9f1654ba8d7c9`。
对比可见少数 `llhd.wait` 事件列表及其后继参数顺序变了。该 IR 在
`dsce_stream_fifo` 的转换阶段报错：`systemc.convert` 试图产生 `!seq.clock`，
`seq.to_clock` 未能合法化。原始 HW IR 可以通过同一转换流程。

因此当前存在两个独立门禁：固定已验证 IR 的行为模型能编译但图像输出错误；从源码
重新抽取 IR 的转换也尚不稳定。不能把一次生成成功当作稳定的源码重建能力。
复现脚本实跑验证：新抽取 IR 路径以退出码 `1` 停在上述转换错误；固定已验证 IR
路径重现相同的 SystemC 头文件 SHA-256，收完 1536 像素后输出仍为 0，差分退出码为 `3`。

## 结论与后续

本轮把原先的“尚未做真实图像差分”变成了一个**确定失败**：CIRCT 当前可完成
全层次转换与 C++ 编译，但还不能宣称所得完整 `dsc_encoder` 行为模型功能正确。
同输入 RTL 确实有输出，故零输出属于原生转换路径新增的行为偏差；同时 RTL 输出本身
也与 VESA golden 不完全一致，不能把 RTL 当作独立算法 golden。

下一步应在 `predict → rate/decision/VLC → format` 之间增加逐周期端口对照，保存首次
不同的 IR SSA 值、时钟/复位和使能条件，缩成最小 CIRCT 回归后再修对应 pass 或 emitter。
`192×108` 原生模型的整帧码流比较尚未执行：较小的合法图像已经在第一个输出预期点
明确失败，先修复这一处再跑大图更有效。不要把本报告的结构/编译通过写成语义通过。

复现脚本：

```bash
export DSCFLOW_CIRCT_ROOT=/path/to/circt-systemc-release
export DSCFLOW_VESA_ROOT=/path/to/DSC_model_20211213
export DSCFLOW_NATIVE_IDLE_LIMIT=1024
scripts/run_native_image_differential_x86.sh
```

若要固定某次输入 IR、只复测后续 CIRCT 行为和图像差分，可额外设置
`DSCFLOW_NATIVE_HW_IR=/path/to/dsc_encoder.hw.mlir`；留空时脚本会从 SV 重新生成。
两种门禁必须分别报告，固定 IR 不能替代源码重建测试。

脚本要求 x86 环境、私有 RTL filelist、VESA 参考程序、已构建的适配器与 SystemC；
失败时非零退出，日志和输出保存在 `.work/runs/native-image-differential/`。
机器可读结果见 [`validation.json`](../../evidence/results/circt_native_image_x86/validation.json)。
