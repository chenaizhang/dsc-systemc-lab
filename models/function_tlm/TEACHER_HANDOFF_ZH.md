# DSC 纯软件 Function Model 教师交付说明

## 交付结论

本目录交付的是老师要求的第一层黄金参考模型：

- 输入：完整 RGB 4:4:4 图像帧与 128-byte DSC PPS；
- 处理：普通 C++ 函数直接调用 VESA DSC 1.67 C reference algorithm；
- 输出：完整 DSC compressed payload；
- SystemC 形态：外部保留 APB/AXI-Stream 兼容的 TLM-2.0 socket，内部没有 RTL 模块层次、时钟、
  `SC_METHOD`、`SC_THREAD` 或流水线状态机；
- 验证：VESA 官方 CLI、普通 C++ adapter、单顶层 TLM 三条路径在 x86 上逐字节一致。

这部分不是由 UHDM/CIRCT 转换出来的。UHDM 和 systemc-clang 用于后续数据流/结构模型；纯软件
function model 应独立于 RTL 层次，作为后续 SystemC 与 Verilator 混合仿真的 reference。

## 代码入口

| 文件 | 作用 |
|---|---|
| `include/dsc_function_tlm.hpp` | 单顶层 TLM wrapper、寄存器状态、帧聚合和 golden 门禁 |
| `include/vesa_reference_codec.hpp` | 普通 C++ 软件 codec 接口 |
| `src/vesa_reference_codec.cpp` | PPS 解析、像素 lane 映射、调用 `DSC_Encode`、slice 拼接 |
| `../systemc/dsc_tlm_interface.hpp` | function/dataflow SystemC 共用的 TLM transaction 类型 |
| `tests/vesa_reference_codec_contract.cpp` | VESA CLI、C++ adapter、TLM wrapper 三路逐字节测试 |
| `tests/dsc_function_tlm_contract.cpp` | TLM socket、错误门禁和无内部层次检查 |
| `run_x86_verify.sh` | 下载、编译和完整差分验证的一键入口 |
| `contract.json` | 模型合同和当前已验收范围 |
| `x86_reference_differential.json` | 稳定的 x86 位精确测试证据 |

项目根目录下还包含：

- `tools/fetch_vesa_dsc_model.sh`：从 VESA 公开下载区取得固定版本并校验 SHA-256；
- `tools/run_dsc_reference_differential.py`：生成确定性测试帧并输出 JSON 报告；
- `docs/zh-CN/reports/DSC_FUNCTION_TLM_X86_VERIFICATION.md`：完整中文验证报告。

## 一键验证

依赖：Linux x86_64、GCC/G++、CMake、Python 3、curl、unzip、SystemC 2.3.3 或 3.x。

在交付包根目录执行：

```bash
./models/function_tlm/run_x86_verify.sh
```

默认生成：

```text
third_party/vesa-dsc-model-20211213/  第三方 VESA 源码与编译产物
.work/build/function-tlm/             项目编译产物
.work/runs/vesa-differential/         测试输入、参考码流和 JSON 结果
```

成功标准：

```text
100% tests passed
PASS bytes=20736
"pass": true
```

## 已验证范围

- DSC 1.2；
- RGB 4:4:4；
- 8 bits/component；
- 8 bits/pixel；
- 192×108；
- 两个 96×108 slice；
- 每次 4 pixels 的输入事务；
- CBR payload 的逐字节比较。

当前 YCbCr、simple/native 4:2:2、native 4:2:0 会返回明确错误，不会输出未经验证的码流。

## 仍需公司提供

原始 `dsc_cix_20260723.rar` 只有 3 份 PDF 和 42 个 SystemVerilog 文件，没有输入帧、PPS、期望
bitstream 或软件 model。因此公司配置的最终 golden 资格还需要：

1. 实际输入帧或 pixel stream；
2. 实际 128-byte PPS；
3. 公司认可的期望 bitstream；
4. PPS 是否随输出发送、slice padding 和拼接规则。

拿到这些材料后，不需要重写模型，只需把用例加入现有差分流程，再依次验证数据流 SystemC、混合
SystemC/Verilator 和全 Verilator RTL。
