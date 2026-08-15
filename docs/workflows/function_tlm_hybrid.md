# DSC 顶层 TLM 软件功能模型与混合仿真验证

## 结论

DSC 验证链必须从一个独立、位精确的软件 codec 开始，不能把 RTL 结构模型或占位 TLM 输出当作
golden。正确顺序是：

```text
权威 DSC vectors
    ↓ 精确码流比较
纯软件 DSC codec + 单顶层 TLM wrapper       ← 第一黄金基线
    ↓ 同帧、同 PPS、精确码流比较
数据流级 SystemC（可保留功能分块/队列）
    ↓ 逐模块替换并始终对同一黄金码流
SystemC + Verilator SystemC 混合模型
    ↓
全 Verilator / 修复后的 RTL
```

仓库已经补上单顶层 `DscFunctionTlm`、VESA C reference adapter 和四阶段差分门禁。VESA DSC
1.67 官方 CLI、进程内 C++ adapter、单顶层 TLM 已在 x86 的 RGB 4:4:4 双切片用例上逐字节一致。
这证明软件参考路径可以工作；由于公司压缩包没有输入帧、PPS 和期望码流，仍不能宣称公司当前
RTL 配置已通过 golden 验证。

## 原压缩包里有什么

已重新找到并解包 `dsc_cix_20260723.rar`，SHA-256 为
`58ee0c4532db91964ed366e86c53b2abc05b6dc4831ba287408a81b55c57ae79`。它只有 3 份 PDF 和 42 份
SystemVerilog：没有 DSC C/C++ 编码器、输入图片、PPS 文件、testbench 或期望 bitstream。因此当前
提到的“测试数据和参考答案”不在这份 RAR 内，需要公司另行提供或确认。

以下已有内容都不是黄金软件模型：

- `models/dataflow_systemc/dsc_tlm.hpp`：总线边界 TLM + 内部 SystemC 数据流骨架；输出带
  `algorithm_placeholder=true`；
- 旧的三模块 LT TLM 骨架没有执行 DSC 编码，已在拆仓时排除，避免与 golden 混淆。

## 官方 VESA 软件参考模型

[VESA 官方公开标准页](https://vesa.org/vesa-standards/)提供 DSC 1.2b 标准及配套 C 源码。项目不复制
第三方源码，只提供带 SHA-256 校验的下载器：

```bash
./tools/fetch_vesa_dsc_model.sh third_party/vesa-dsc-model-20211213
```

固定版本为 `DSC_model_20211213`、reference model 1.67，压缩包 SHA-256 为
`f2339edb1d5603d2f3ca5fbb6ca089b18ff73c43088352fa7c3b59df03e3ee2c`。`VesaReferenceCodec` 直接
调用官方 `DSC_Encode`，不是让 LLM 根据 RTL 猜一份压缩算法。

## 新增单顶层 function TLM

文件：

```text
models/function_tlm/include/dsc_function_tlm.hpp
```

`DscFunctionTlm` 只有一个 `SC_MODULE`，外部接口与数据流级模型一致：

| 接口 | 类型 | 语义 |
|---|---|---|
| `apb` | 32-bit TLM target | APB 寄存器访问 |
| `pixel_stream_in` | 192-bit TLM target | AXI4-Stream 像素 beat |
| `bitstream_out` | 192-bit TLM initiator | AXI4-Stream 压缩码流 beat |

两个模型共享 `dsc_tlm_interface.hpp` 中的 `PixelStreamExtension` 和
`EncodedStreamExtension`，因此测试平台可以在不改事务类型的情况下替换模型。

function TLM 内部明确禁止：

- 子 `SC_MODULE`；
- `sc_fifo`；
- `SC_METHOD`、`SC_THREAD`、`SC_CTHREAD`；
- 时钟沿、逐拍握手状态机和 RTL 流水寄存器。

像素事务在普通 C++ 容器中组成一帧，帧结束时同步调用：

```cpp
SoftwareDscCodec::encode(const FrameRequest&)
```

这就是类似 QEMU 的功能抽象：事务触发一个普通软件函数，SystemC/TLM 只负责寄存器和数据流边界。

当前已验收的输入映射是 RGB 4:4:4：每个 48-bit pixel 的低、中、高 16-bit lane 分别为 B、G、R，
有效样本按用户手册要求左对齐。YCbCr、native 4:2:2/4:2:0 虽然官方 C model 支持，但项目 adapter
尚未完成对应 AXI lane 语义验收，会明确返回 `InvalidPps`，不会静默产生可疑码流。

## Golden 安全门禁

生产构造默认 `require_golden_codec=true`：

- 没有 codec：返回 `TLM_GENERIC_ERROR_RESPONSE`，不输出码流；
- codec 没有声明 `is_bit_exact_golden()==true`：拒绝执行，不输出码流；
- codec 返回失败或空码流：拒绝晋级；
- 只有已通过权威 vectors 的 codec 才能作为后续 SystemC/Verilator 的 reference。

测试中包含一个确定性 non-golden codec，只验证 socket、帧聚合、分块输出、延迟和门禁。它必须以
`require_golden_codec=false` 显式启用，所有输出仍标记 `algorithm_placeholder=true`，不能误用为 DSC
参考答案。

## 结果集与四阶段比较

统一结果格式为 `llm4eda-dsc-result-set`。每个用例必须记录：

- 用例 ID；
- 输入帧 SHA-256；
- PPS SHA-256；
- 状态；
- 完整输出码流 SHA-256；
- 可选完整码流十六进制，用于自动复核摘要。

检查当前状态：

```bash
dscflow golden status --case .
```

第一阶段，软件 codec 对权威向量：

```bash
dscflow golden compare \
  --stage software \
  --reference datasets/authoritative_vectors.results.json \
  --candidate datasets/software_function.results.json \
  --output .work/runs/dsc/software-comparison.json
```

只有公司向量比较通过并完成来源审查，才能给公司配置的软件结果设置
`producer.golden_qualified=true`。后续依次执行：

```bash
dscflow golden compare --stage dataflow \
  --reference datasets/software_function.results.json \
  --candidate datasets/dataflow_systemc.results.json

dscflow golden compare --stage hybrid \
  --reference datasets/software_function.results.json \
  --candidate datasets/hybrid_verilator.results.json

dscflow golden compare --stage rtl \
  --reference datasets/software_function.results.json \
  --candidate datasets/rtl_verilator.results.json
```

比较要求相同用例 ID、输入/PPS 摘要、状态和码流摘要完全相同。任一阶段失败，不能继续扩大替换
范围。

## 编译与接口测试

```bash
cmake -S models/function_tlm -B .work/build/function-tlm
cmake --build .work/build/function-tlm --parallel
ctest --test-dir .work/build/function-tlm --output-on-failure
```

带官方 reference adapter 的完整 x86 验证：

```bash
model_root=$(./tools/fetch_vesa_dsc_model.sh \
  third_party/vesa-dsc-model-20211213)
make -C "$model_root/source" clean all

cmake -S models/function_tlm \
  -B .work/build/function-tlm \
  -DDSCFLOW_ENABLE_VESA_CODEC=ON \
  -DVESA_DSC_MODEL_ROOT="$model_root"
cmake --build .work/build/function-tlm --parallel

./tools/run_dsc_reference_differential.py \
  --model-root "$model_root" \
  --adapter-test .work/build/function-tlm/vesa_reference_codec_contract \
  --work-dir .work/runs/vesa-differential \
  --report .work/runs/vesa-differential/report.json
```

脚本生成 192×108 确定性 RGB 图像，设置 8 bpc、8 bpp、两个 96×108 slice。VESA CLI 生成
`.dsc`，测试程序取出其中 PPS 和压缩 payload，再让普通 C++ adapter 与单顶层 TLM 各编码一次；
三路 payload 必须逐字节一致。

## 公司配置最终验收仍需材料

至少需要：

1. 公司实际输入图像或原始 pixel stream；
2. 与 RTL 寄存器配置完全一致的 128-byte PPS；
3. 公司认可的期望 bitstream；
4. 输出是否包含 PPS、slice padding 和拼接方式；
5. 计划支持的 bpc、RGB/YCbCr、slice 边界和 rate-control 边界用例。

拿到这些材料后直接复用现有 adapter、TLM 外部接口和差分格式，无需重新设计模型。
