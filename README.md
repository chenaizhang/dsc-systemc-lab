# DSC SystemC Lab

当前路线：

```text
规格 + 参考 RTL
  ├─ VESA C model → 单顶层 Function-TLM → 软件 golden
  ├─ Surelog/UHDM → 层次、端口、实例、连接结构合同
  ├─ CIRCT HW/Comb/Seq → 能转换多少就保留多少
  ├─ Verilator --sc → 完整 RTL cycle-level 独立参考
  └─ Verilator --cc → CIRCT SystemC 容器中的叶子 interop
                         ↓
             Agent 补全 cycle SystemC
                         ↓
              同输入逐拍/逐字节差分
```

## 当前真实状态

| 项目 | 状态 | 可以声称什么 |
|---|---|---|
| VESA C adapter + 顶层 Function-TLM | x86 已通过 | 合成 RGB 用例与 VESA CLI 逐字节一致 |
| 公司测试数据 | 缺失 | 不能声称公司 DSC 配置已功能验证 |
| UHDM 层次 | x86 完整通过 | 261 实例、3,243 端口和 3,155 具名绑定形成权威结构参考 |
| CIRCT core IR | x86 已生成 | HW/Comb/Seq/LLHD 分析入口有效 |
| CIRCT HW SystemC | x86 完整通过 | 50 个 `SC_MODULE`、89 条定义级实例边，运行时展开 261 实例 |
| CIRCT Comb/Seq SystemC | 未闭环 | LLHD 聚合降级已越过 `hw.bitcast`；当前首错为 `sim.fmt.literal` |
| CIRCT + Verilator 混合 SystemC | x86 源码构建通过 | 引擎容器、5 个叶子、192 位 packed ABI、CDC shim 均通过编译和 smoke test |
| 分层 Function SystemC | 深度 1 已验证 | 顶层与 7 个直属子模块通过事务级和 VESA golden 差分；深度 2～5 待验证 |
| Verilator-SystemC | x86 已跑单体及 7 模块网络 | 共享 stimulus 下，拆分结构与单体逐周期一致 |
| Agent cycle SystemC | `CycleApb` 已真实替换 | 与 Verilator APB 网络逐周期一致；其余模块仍为黑盒 |
| RTL vs VESA golden | 功能门禁失败 | 安全 overlay 后三路输出 20,232 字节，golden 为 20,736 字节；首差异 byte 254 |

## 仓库结构

```text
configs/                 UHDM、CIRCT、分层 function 流程配置和模型边界
datasets/                五阶段结果集约定；目前无公司向量
docs/                    中文流程和历史 x86 实测报告
evidence/                精简保留的 UHDM 结构与机器报告
inputs/private/          本地 RTL、PDF、文本；Git 默认忽略
models/function_tlm/     无内部层次的纯软件 DSC + TLM wrapper
models/cycle_systemc/    拆分 Verilator 网络、CycleApb 和缺失原语仿真 shim
models/dataflow_systemc/ 有内部 SC_MODULE 层次的占位数据流模型
src/dscflow/             UHDM-Agent、CIRCT/Verilator、golden 门禁代码
tasks/                   可独立开启的新任务工作包
tests/                   不依赖商业工具的快速回归
third_party/             VESA reference model；Git 默认忽略
tools/                   UHDM exporter、VESA 下载与差分工具
```

后续实施任务及验收条件见 [TASKS.md](TASKS.md)。

## 快速开始

本地只做代码阅读和编辑；按项目约定，正式编译、CIRCT、Verilator、SystemC 和差分均在 x86
服务器运行。

```bash
python3 -m venv .venv
. .venv/bin/activate
python tools/check_assets.py
bash scripts/run_python_tests.sh
dscflow skills
```

### CIRCT 按层次剥离

当前主线允许只展开指定深度的 RTL 层次。边界以下行为不会进入 Comb/Seq lowering，因而
`seq.firmem`、内部大数组或尚未支持的操作不会阻塞上层 SystemC 骨架：

```bash
make hierarchy-x86 \
  CORE_IR=/path/to/dsc_encoder.hw.mlir \
  TOP=dsc_encoder \
  DEPTH=1 \
  UHDM_JSON=evidence/uhdm/module_hierarchy.json
```

输出目录包含切片 HW IR、manifest、SystemC dialect、可编译 C++ 头文件和结构验证 JSON。
详细语义与验收规则见
[`docs/workflows/circt_hierarchy_peeling_zh.md`](docs/workflows/circt_hierarchy_peeling_zh.md)。

生成 UHDM 约束和逐模块完整 SV 提示包：

```bash
dscflow uhdm-systemc prepare \
  --config configs/uhdm_agent.json \
  --output-dir .work/runs/uhdm-agent/dsc_encoder
```

重新跑 CIRCT/Verilator 分阶段探针：

```bash
dscflow circt run \
  --config configs/staged_circt.json \
  --output-root .work/runs/staged-circt
```

从私有 RTL 生成不含预编译库的可移植混合 SystemC 工程，并立即执行 CMake/CTest：

```bash
bash scripts/build_portable_dsc_mixed_project.sh \
  inputs/private/rtl /path/to/circt/build /tmp/dsc-portable-build \
  /path/to/systemc/cmake
```

将同一套 UHDM、CIRCT 和 Verilator 内联流程复用到新的图像 IP，请使用
[中文交接说明](docs/handoffs/image_ip_systemc_pipeline_zh.md)和
`configs/image_ip_template.json`，正式验证仍在 x86 服务器执行。

生成 UHDM 层次化 FunctionSlot 骨架和逐层语义计划：

```bash
dscflow layered prepare \
  --config configs/layered_equivalence.json \
  --output-dir .work/runs/layered-equivalence
```

在 x86 上执行结构、HW-only、Comb/Seq、Verilator 和报告汇总的完整门禁：

```bash
bash scripts/run_layered_equivalence_verification.sh
```

重新跑 VESA C、C++ adapter 和单顶层 TLM 三路差分：

```bash
./models/function_tlm/run_x86_verify.sh
```

重建单体/拆分/混合三路差分验证（仅限 x86）：

```bash
bash scripts/run_hybrid_differential_verification.sh
```

分层 SystemC 结果见
[中文完整报告](docs/reports/layered_systemc_equivalence_x86.md)；历史混合差分结果见
[混合差分报告](docs/reports/hybrid_differential_x86.md)；可分发 CIRCT 工具的构建和混合回归结果见
[CIRCT SystemC Release 验证报告](docs/reports/circt_systemc_release_x86_zh.md)；最新版 interop、
`structure-only`、`seq.firmem` 和全局 aggregate 的定向复测见
[CIRCT interop 回归复测报告](docs/reports/circt_interop_regression_retest_x86_zh.md)。

当前 format/stream 排障已经把原来的多个确认项压缩为一个资料请求：提供正式 last/flush 实现，
或一个 slice 连续两行的正确 VCS 边界波形。详见
[最小资料请求](docs/blockers/format_stream_contract_questions_zh.md)。

## 结果边界

- `models/function_tlm` 才是纯软件 golden 候选；它没有内部 RTL/SystemC 层次。
- `models/dataflow_systemc` 目前算法是占位实现，不能用于判断压缩码流正确性。
- UHDM/systemc-clang 只验证结构，不能替代共享输入功能差分。
- Verilator 模型来自同一份参考 RTL，可作 cycle-level 对照，但不等同于独立算法 golden。
- 当前参考 RTL 缺少专有同步器和 SRAM 行为；仿真 shim 可启动功能路径，但不能证明专有原语精确等价。

完整 `dsc_encoder` 顶层混合模型已在 x86 服务器通过源码重建门禁。流程用 UHDM 强制核对
`dsce_reset`、`dsce_apb`、`dsce_timers`、`dsce_interrupt`、`dsce_pps`、`dsce_command` 和
`dsce_engine` 七个直属子模块，CIRCT 生成顶层 SystemC 胶水，七个子模块由 Verilator 内联；
C++ 编译、链接、elaboration smoke test 与 CDC shim 测试均通过。该结果证明完整顶层可构建运行，
但不等同于图像码流已经与独立 golden 一致。
