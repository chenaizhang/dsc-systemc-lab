# DSC 纯软件 Function Model 与单顶层 TLM x86 验证报告

## 1. 目的

落实老师提出的第一层验证基线：先得到一个不含 RTL 层次、时钟和流水线的纯软件 DSC model，
通过输入图像直接产生压缩码流；再用相同的 APB/AXI-Stream 事务边界包装成单顶层 TLM SystemC，
作为后续数据流级 SystemC 和 Verilator 混合替换的参考模型。

本报告回答三个问题：

1. 原压缩包是否包含纯软件 model、测试数据和参考答案；
2. 项目生成的 function model 是否真的执行 DSC，而不是 LLM 占位逻辑；
3. 普通 C++、单顶层 TLM 与官方参考程序的码流是否一致。

## 2. 输入材料审计

重新找到并解包了原文件 `dsc_cix_20260723.rar`：

| 项目 | 结果 |
|---|---|
| RAR SHA-256 | `58ee0c4532db91964ed366e86c53b2abc05b6dc4831ba287408a81b55c57ae79` |
| PDF | 3 份 |
| SystemVerilog | 42 份 |
| C/C++ 软件 codec | 0 |
| 输入图片/原始像素文件 | 0 |
| PPS 向量 | 0 |
| 期望 `.dsc`/golden bitstream | 0 |
| testbench | 0 |

所以原包包含 Spec 和完整 RTL，但没有老师所说的纯软件 model，也没有能直接逐字节比对的公司测试
数据或参考答案。此前文档里“原压缩包已不存在”的说法已经纠正；真正结论是“RAR 已找到，但里面
没有这些文件”。

## 3. 软件参考来源

[VESA 官方公开标准页](https://vesa.org/vesa-standards/)提供 DSC 1.2b 标准及配套 C source model。
本次固定使用：

| 项目 | 值 |
|---|---|
| 模型版本 | DSC reference model 1.67 |
| 发布包 | `DSC_model_20211213.zip` |
| SHA-256 | `f2339edb1d5603d2f3ca5fbb6ca089b18ff73c43088352fa7c3b59df03e3ee2c` |
| 获取方式 | `tools/fetch_vesa_dsc_model.sh` |
| 仓库策略 | 不复制第三方源码，只保存下载入口、版本和摘要 |

项目实现的 `VesaReferenceCodec` 直接调用官方 `DSC_Encode`。算法不是从 UHDM 层次生成，也不是
agent 看着 RTL 自行推理出来的；UHDM/systemc-clang 仍用于后续结构级模型，不能替代软件 golden。

## 4. 实现结构

```text
确定性 RGB 帧 + 128-byte PPS
        ├─→ VESA 官方 CLI ─────────────→ reference .dsc
        ├─→ VesaReferenceCodec::encode ─→ raw compressed payload
        └─→ DscFunctionTlm
              APB + pixel_stream_in
              同步调用同一普通 C++ codec
              bitstream_out ───────────→ raw compressed payload
```

相关文件：

- `function_tlm/include/dsc_function_tlm.hpp`：无内部层次的单顶层 TLM wrapper；
- `function_tlm/include/vesa_reference_codec.hpp`：普通 C++ codec 接口；
- `function_tlm/src/vesa_reference_codec.cpp`：PPS 解析、AXI pixel lane 到图像的映射、slice 编码和拼接；
- `function_tlm/tests/vesa_reference_codec_contract.cpp`：官方 CLI/C++/TLM 三路逐字节比较；
- `tools/run_dsc_reference_differential.py`：生成刺激、调用两套路径并输出 JSON 报告。

`DscFunctionTlm` 内部没有子 `SC_MODULE`、`sc_fifo`、`SC_METHOD`、`SC_THREAD`、`SC_CTHREAD` 或
时钟沿状态机。SystemC 只保留可替换的事务接口，压缩算法是一次完整帧级函数调用，符合老师所说的
“像 QEMU 一样的纯 function model”。

## 5. 测试过程

所有正式编译和运行均在服务器 `10.203.255.52` 的 x86_64 Linux 环境完成。

1. 下载官方 source model 并校验 SHA-256；
2. 用 GCC 15.2.0 编译 VESA 原始 C CLI；
3. 用 SystemC 3.0.2 编译项目普通 C++ adapter 和单顶层 TLM；
4. 生成 192×108 的确定性 RGB PPM；
5. 配置 DSC 1.2、RGB 4:4:4、8 bpc、8 bpp、slice 96×108，即每行两个 slice；
6. 官方 CLI 生成带 `DSCF` 头和 128-byte PPS 的 `.dsc`；
7. 测试程序取相同 PPS 和像素，分别调用 C++ adapter 与完整 TLM socket 路径；
8. 去掉官方文件的 4-byte `DSCF` 头和 128-byte PPS，对三路压缩 payload 逐字节比较。

## 6. 结果

| 检查 | 结果 |
|---|---|
| x86 架构 | `x86_64` |
| VESA 原始 C CLI 编译 | 通过 |
| 项目 adapter `-Werror` 编译 | 通过 |
| 原 function TLM contract | 1/1 通过 |
| VESA CLI 处理 slice | 2/2 通过 |
| 官方 `.dsc` 总长度 | 20,868 bytes |
| 其中压缩 payload | 20,736 bytes |
| 普通 C++ adapter vs 官方 CLI | 逐字节一致 |
| 单顶层 TLM vs 官方 CLI | 逐字节一致 |
| TLM `algorithm_placeholder` | `false` |
| DSC Python 门禁单测 | 6/6 通过 |
| 全仓 Python 回归 | 57 passed、2 skipped、6 subtests passed |
| 本次 Python Ruff | 通过 |

稳定证据保存在 `evidence/results/vesa_function_tlm_x86.json`。关键摘要：

- 输入 PPM SHA-256：`d54ae9b32d303a4e1423160bc88b5ca854c24e272385ca63bfbdf9c5bb48b7f3`
- 官方 `.dsc` SHA-256：`375488877108b8fcc830273423aa121ebaf19e16dbf3d3fc3b72215fc679f211`

## 7. 结论与边界

老师要求的纯软件 function model 和单顶层 TLM wrapper 已经落地，并在真实 x86 环境完成了官方
参考程序的位精确验证。对于已记录的 RGB 4:4:4 双切片配置，可以确认输出不是占位数据，也不需要
LLM 在运行时推理补代码。

但当前不能把这个单一配置扩大成“公司 RTL 已全部正确”：

- 原 RAR 没有公司输入/PPS/期望输出；
- 当前 adapter 已验收 RGB 4:4:4，YCbCr、native 4:2:2/4:2:0 的 AXI lane 映射尚未验收；
- 公司是否输出 PPS、如何做 slice padding/拼接，需要与实际测试平台一致。

因此下一步不是再造一个算法，而是让公司提供或确认至少一组实际输入、128-byte PPS 和期望码流。
通过后，把相同数据依次送入数据流 SystemC、混合 SystemC/Verilator、全 Verilator，逐模块替换并始终
比较最终完整码流；首次出现差异的替换模块就是重点排查对象。
