# DSC SystemC Lab

当前路线：

```text
规格 + 参考 RTL
  ├─ VESA C model → 单顶层 Function-TLM → 软件 golden
  ├─ Surelog/UHDM → 层次、端口、实例、连接结构合同
  ├─ CIRCT HW/Comb/Seq → 能转换多少就保留多少
  └─ Verilator --sc → cycle-level 参考与暂时的黑盒替换
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
| UHDM 层次 | 已有结构证据 | 可约束模块、端口、实例和大部分连接 |
| CIRCT core IR | x86 已生成 | HW/Comb/Seq/LLHD 分析入口有效 |
| CIRCT 原生 SystemC | 未闭环 | 卡在 `llhd.coroutine`，不能说已生成完整 SC |
| Verilator-SystemC | x86 已跑单体及 7 模块网络 | 共享 stimulus 下，拆分结构与单体逐周期一致 |
| Agent cycle SystemC | `CycleApb` 已真实替换 | 与 Verilator APB 网络逐周期一致；其余模块仍为黑盒 |
| RTL vs VESA golden | 功能门禁失败 | 三路 RTL/cycle 输出 7,104 字节，golden 为 20,736 字节 |

## 仓库结构

```text
configs/                 两条主流程配置和模型边界
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

重新跑 VESA C、C++ adapter 和单顶层 TLM 三路差分：

```bash
./models/function_tlm/run_x86_verify.sh
```

重建单体/拆分/混合三路差分验证（仅限 x86）：

```bash
bash scripts/run_hybrid_differential_verification.sh
```

结果解读见 [中文完整报告](docs/reports/hybrid_differential_x86.md)。

## 结果边界

- `models/function_tlm` 才是纯软件 golden 候选；它没有内部 RTL/SystemC 层次。
- `models/dataflow_systemc` 目前算法是占位实现，不能用于判断压缩码流正确性。
- UHDM/systemc-clang 只验证结构，不能替代共享输入功能差分。
- Verilator 模型来自同一份参考 RTL，可作 cycle-level 对照，但不等同于独立算法 golden。
- 当前参考 RTL 缺少专有同步器和 SRAM 行为；仿真 shim 可启动功能路径，但不能证明专有原语精确等价。
