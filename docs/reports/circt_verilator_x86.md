# verilog_dsc：UHDM + CIRCT 分阶段 SystemC x86 实测报告

## 1. 目的

本报告回答老师提出的四个具体问题：

1. 真实 DSC SystemVerilog 能否通过 CIRCT frontend 得到 HW/Comb/Seq core IR；
2. 模块、端口、模块间实例连线和胶水逻辑能否进入 CIRCT 生态；
3. CIRCT 1.155.0 的原生 SystemC 转换实际停在哪一层、哪个 operation；
4. 原生转换失败时，Verilator-SystemC 能否作为整核或局部模块的 cycle-level 黑盒。

实测日期为 2026-08-15。所有 EDA 命令在 `10.203.255.52` 的 Ubuntu x86_64 环境执行，macOS
只用于编辑代码和同步结果。

## 2. 样本与工具

输入来自赖聪提供的 `verilog_dsc.7z`，包含 43 个 `.sv`、`surelog.f`、UHDM 数据库、层次
JSON、exporter 源码和 Surelog 日志。私有 RTL 和 UHDM 数据库不提交 Git。

| 项目 | 实测值 |
|---|---|
| 操作系统 | Ubuntu Linux x86_64 |
| CIRCT | firtool-1.155.0，LLVM 24git，Slang 11.0 |
| Verilator | 5.032 |
| SystemC | 3.0.2（pkg-config） |
| C++ | GCC 15.2.0 |
| GNU Make | 4.4.1 |
| 顶层 | `dsc_encoder` |
| UHDM hierarchy JSON SHA-256 | `1bec883721ce6d3cc2b530310c8df5e1d5bc420dc92eff42f42bbc1308d43558` |
| UHDM DB SHA-256 | `ab86b7d632ce790d1504dfb19cbf9524faa5c95ab774fb15f5229c7c48639af6` |

CIRCT 使用官方 x86 shared 包。由于该包运行时需要 `libz3.so.4`，服务器从 Ubuntu `libz3-4`
包中无 root 解压依赖，并通过 `LD_LIBRARY_PATH` 注入；不是修改或替换 CIRCT 二进制。

## 3. 过程

### 3.1 输入真实性检查

1. 对 filelist、UHDM JSON、Surelog 日志计算哈希；
2. 从 JSON 提取 definition、top、node、invocation；
3. 从 Surelog 日志提取 elaboration 统计；
4. 比较 JSON 节点数与 elaborated instance 数；
5. 原样跑一次全 filelist，再依据“定义存在但未实例化”的证据跑顶层可达 filelist。

### 3.2 CIRCT 分阶段探针

1. `circt-verilog --ir-hw` 生成 core IR；
2. 从 IR 提取 module、port、`hw.instance` 和 dialect operation；
3. `canonicalize + symbol-dce` 形成转换输入；
4. `convert-hw-to-systemc` 运行到首个失败；
5. 只有转换成功才执行 `export-systemc`。

### 3.3 Verilator 黑盒验证

分别以 `dsc_encoder`、`dsce_engine` 和 `dsce_apb` 为顶层生成 SystemC 包装的 C++ 模型，编译
`V<module>__ALL.a`，并与 CIRCT HW IR 的端口集合逐一比较。

## 4. 结果

### 4.1 UHDM 输入

| 检查项 | 结果 |
|---|---:|
| Surelog top modules | 1 |
| Surelog max instance depth | 9 |
| Surelog instances | 261 |
| Surelog leaf instances | 73 |
| Surelog fatal / syntax / error / warning | 0 / 0 / 0 / 0 |
| JSON definitions | 43 |
| JSON hierarchy nodes | 25 |
| JSON invocations | 24 |
| JSON 未表示的实例差额 | 236 |

结论：Surelog elaboration 本身成功，但附带 exporter 的 JSON 不完整。源码显示它只递归
`vpiModule`，generate scope 下的实例没有完整展开。因此这份 JSON 可作证据，不能单独作完整层次
golden。

### 4.2 CIRCT frontend 与 core IR

全 filelist 失败于 `dsce_quant.sv`：未声明 `tDSC_SAMPLE` 和 `kDSC_SAMPLE_INIT`。该文件定义的
模块名是 `dsce_qaunt`，没有被 `dsc_encoder` 实例化。保留原错误后排除该文件，顶层可达设计的
frontend 成功。

| core IR 项目 | 实测值 |
|---|---:|
| `hw.module` | 50 |
| `hw.instance` | 89 |
| 含 Comb 的模块 | 42 |
| `comb.*` operation | 15,346 |
| 含 Seq 的模块 | 36 |
| `seq.*` operation | 540 |
| 含 LLHD 的模块 | 9 |
| `llhd.*` operation | 589 |
| 原始 core IR 大小 | 1,936,280 bytes |
| normalize 后大小 | 1,336,320 bytes |

50 个模块多于 UHDM 的 43 个 definition，是因为 CIRCT 生成了 9 个参数特化，同时未保留未使用的
`dsce_qaunt` 和 `dsce_input_buffer`。CIRCT 找到 41 个与 UHDM 同名的可达 definition，且顶层
`dsc_encoder` 存在。

这说明模块壳、端口、89 个实例操作，以及模块间连线与胶水逻辑使用的 SSA 值都已进入 CIRCT
core IR；但“进入 IR”不等于“已经发射成 SystemC C++”。

### 4.3 原生 SystemC 转换

`canonicalize + symbol-dce` 成功。随后 `convert-hw-to-systemc` 首先失败于：

```text
failed to legalize operation 'llhd.coroutine'
symbol: dsce_defs_pkg::dsce_min_sad4
```

这是 package task/ref 相关的 LLHD coroutine，发生在 Comb 或 Seq emission 之前。因此当前真实
DSC 设计的分阶段状态是：

| 阶段 | 状态 |
|---|---|
| SV frontend → core IR | 成功（可达设计） |
| HW module/port/instance/SSA 提取 | 成功 |
| Comb SSA 提取 | 成功 |
| Seq SSA 提取 | 成功 |
| LLHD → SystemC conversion | 失败于 `llhd.coroutine` |
| SystemC dialect 完整生成 | 未完成 |
| C++ emission | 因上一阶段失败而未运行 |

所以不能声称“CIRCT 已把这个 DSC 骨架和胶水逻辑生成可编译 SystemC”。准确说法是：结构和行为
证据已进入 CIRCT core IR，原生 HW→SystemC 全设计转换被 LLHD operation 挡住。

### 4.4 Verilator-SystemC 回退

| 模块 | 生成 | 静态库编译 | CIRCT/Verilator 端口集合 |
|---|---|---|---|
| `dsc_encoder` | 成功 | 成功 | 一致 |
| `dsce_engine` | 成功 | 成功 | 一致 |
| `dsce_apb` | 成功 | 成功 | 一致 |

三个模型均生成真实头文件和 `V<module>__ALL.a`。这证明可以把整核、engine 或 APB 模块作为
cycle-level SystemC 黑盒使用，也给出了由小到大的替换顺序：

```text
dsce_apb → dsce_engine → dsc_encoder
```

它不证明三个模型的 DSC 输出正确；Verilator 只是从同一份 RTL 生成仿真模型。

### 4.5 Skill 与 Agent 接口

x86 服务器已发现以下项目 Skill，路径均来自 `~/.codex/vendor/eda-sandbox/skills/`：

- `eda-tool-assistant`
- `modeling-systemverilog`
- `modeling-systemc-tlm`

流程生成的 `04_agent_context/context.json` 包含 module、port、instance、dialect 分区、失败
operation 和受影响模块。Agent 允许做三种局部动作：补 CIRCT conversion/emission pattern、抽取
SSA 后补局部 method、或把受影响模块换成 Verilator 黑盒；禁止改写层次和把 Agent 代码冒充
CIRCT 输出。

### 4.6 自动测试与 harness

服务器创建了独立 Python 虚拟环境，并安装 `pytest`、`jsonschema`、`uv` 和 EDA harness 所需的
`PyYAML`。最终验证结果：

| 验证 | 结果 |
|---|---|
| staged CIRCT 专项单元测试 | 6 passed |
| 相关 SystemC/CIRCT 回归 | 21 passed（包含上述 6 项） |
| 仓库全量 pytest | 63 passed, 2 skipped, 6 subtests passed |
| eda-harness 三组 checks | 全部 passed |
| eda-harness allowed-changes | passed，0 violation |

首次同步产生的 1,298 个 macOS AppleDouble `._*` 旁车文件仅位于服务器临时副本，清除后全量
测试通过；本机源码未因此修改。harness 还识别并从临时副本清除了误同步的 `.env`、本地编辑器
设置、缓存、egg-info、日志和波形文件，最终完整性门禁只剩任务允许路径。

## 5. 结论

1. 老师要求的“先利用 CIRCT 生态获得层次和行为 IR”已经真实跑通；不是 AI 读 SV 后声称转换。
2. 当前最先卡住的不是 `seq.to_clock`，而是 package task 产生的 `llhd.coroutine`。只有先处理或
   隔离该 operation，才能继续测 Comb/Seq 的原生 SystemC backend 覆盖率。
3. Verilator-SystemC 的整核和两个局部黑盒均可构建，端口与 CIRCT 结构一致，可作为混合仿真的
   现实回退。
4. 附带 UHDM JSON 漏了 generate scope，必须让赖聪修 exporter，或直接从 UHDM 数据库补遍历
   `vpiGenScope/vpiGenScopeArray` 后，才能做严格层次等价。
5. 当前压缩包没有图像输入、寄存器配置序列、参考压缩输出或官方 DSC C model，故最终数据差分
   没有执行。状态明确记录为 `not_run_no_shared_stimulus_in_verilog_dsc_bundle`。

## 6. 下一步门禁

开始功能验证前必须补齐同一套：输入图像/像素流、PPS/APB 配置、时钟复位约定、期望码流或解码
图像。验证顺序应为：

1. 用 SPEC 生成的单顶层 function/TLM SystemC 与官方/参考数据对齐；
2. 数据流级 SystemC 与 function/TLM golden 对齐；
3. 从 `dsce_apb` 开始逐模块替换为 Verilator-SystemC；
4. 每次替换都跑同一数据，定位首个输出分歧；
5. 只有全替换仍一致，才能说对应 RTL 通过这组功能回归。

机器报告入口：`evidence/results/circt_verilator_x86.json`。
