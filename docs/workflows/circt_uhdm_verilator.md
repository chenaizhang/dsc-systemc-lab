# UHDM + CIRCT 分阶段 SystemC 与 Verilator 混合仿真流程

## 1. 适用目标

这条流程用于当前 DSC 路线：结构不能由大模型猜；先利用 UHDM 与 CIRCT 固化模块、
端口、实例、连线和 SSA 行为证据，再判断 CIRCT 的 SystemC 后端能走到哪一步。后端不能完成的
模块，使用 Verilator `--cc` 生成普通 C++ 叶子并通过 interop 内联；独立的完整 RTL 参考才使用
Verilator `--sc`。只有明确定位到局部 operation 缺口后，才允许 Agent 补 CIRCT pass 或局部
SystemC method。

它不把 Verilator 模型说成纯软件 function model，也不把“编译成功”说成“图像压缩功能正确”。

```mermaid
flowchart TD
    A["SV + Surelog/UHDM 证据"] --> B["CIRCT Slang frontend"]
    B --> C["HW/Comb/Seq/LLHD core IR"]
    C --> D["HW：module/port/instance/连线证据"]
    C --> E["Comb：组合 SSA"]
    C --> F["Seq/LLHD：状态、时钟、task/ref 证据"]
    D --> G["convert-hw-to-systemc"]
    E --> G
    F --> G
    G -->|"成功"| H["CIRCT 原生 SystemC"]
    G -->|"局部 operation 不支持"| I["Agent 局部 pass/方法补全"]
    G -->|"当前无法补齐"| J["Verilator-SystemC 黑盒"]
    H --> K["systemc-clang 层次/绑定检查"]
    I --> K
    J --> L["RTL/cycle-level 混合仿真"]
    K --> L
    L --> M["共享图像与寄存器 stimulus 差分"]
    M --> N["functional/TLM golden model"]
```

## 2. 输入与证据职责

| 证据 | 负责回答 | 不能证明 |
|---|---|---|
| Surelog 日志 | elaboration 是否干净、实例总数、最大深度 | 附带 JSON exporter 是否完整 |
| UHDM hierarchy JSON | exporter 实际导出的模块与调用关系 | generate scope 被漏掉时的完整层次 |
| CIRCT HW IR | 展开后的模块、端口类型、`hw.instance` 与 SSA | 原生 SystemC exporter 一定支持这些 operation |
| Verilator `--sc` | 完整 RTL 可生成独立 cycle-level SystemC 参考 | RTL 功能正确、与 golden 等价 |
| Verilator `--cc` | CIRCT 容器可调用叶子 C++ 成员和 `eval()` | packed 端口未经 ABI 统一时可以直接集成 |
| systemc-clang | Agent/原生 SystemC 的模块、端口、绑定、process 静态结构 | 运行时数据正确 |
| 共同 stimulus + golden | 最终输出是否一致 | 未覆盖输入空间上的普遍正确性 |

仓库中的 UHDM exporter 已补齐 generate scope 递归。本次权威 JSON 含 261 个 elaborated 实例、
3,243 个端口和 3,155 个具名绑定；CIRCT `hw.instance` 清单作为独立结构视角。生成器不得在这两个
证据之外臆造连接。

## 3. 五个阶段

### 3.1 全量 frontend

先按 `surelog.f` 原样解析所有源文件，目的是暴露输入包本身的问题。此阶段失败不会被静默过滤。

### 3.2 顶层可达 frontend

只有同时满足以下条件，才允许排除一个坏文件后继续：

1. 文件在原 filelist 中；
2. 其中定义出现在 UHDM definition 清单；
3. 该定义未出现在附带 JSON 的实例节点；
4. 排除原因写入机器报告。

当前唯一排除项是 `dsce_quant.sv`：它定义的 `dsce_qaunt` 未实例化，且使用未声明的
`tDSC_SAMPLE`、`kDSC_SAMPLE_INIT`。原始失败仍保留在 `01_frontend_all_sources.stderr.log`。

### 3.3 HW / Comb / Seq / LLHD 分区

成功生成 core IR 后，脚本逐个 `hw.module` 提取：

- 输入、输出和 aggregate 端口类型；
- `hw.instance` 的父模块、实例名和目标模块；
- `comb.*`、`seq.*`、`llhd.*` operation 计数；
- 结构-only、组合、时序和 LLHD 模块集合。

该清单同时写入 Agent context。Agent 只得到失败 operation 的受影响模块和允许动作，不得到
“可以改层次”的权限。

### 3.4 CIRCT 原生 SystemC

顺序执行：

```text
circt-verilog --ir-hw
circt-opt --canonicalize --symbol-dce
circt-opt --convert-hw-to-systemc="structure-only=true"
circt-translate --export-systemc
```

HW-only 先生成模块、端口、实例、信号、绑定和空 method，并执行 C++ 编译及运行时 elaboration。
随后再单独调用完整 `convert-hw-to-systemc` 测试 Comb/Seq。每一阶段都保存 argv、返回码、
stdout/stderr、产物哈希和大小；完整行为转换失败时分类首个非法 operation，绝不生成伪造行为。

### 3.5 Verilator 黑盒与混合计划

完整独立参考对配置中的顶层执行：

```text
verilator --sc --timing --trace ...
make -f V<module>.mk V<module>__ALL.a
```

供 CIRCT interop 使用的叶子必须先从 prepared IR 导出展平端口 SystemVerilog，再运行
`verilator --cc`。这保证 Verilator 成员名和 CIRCT SystemC 访问名一致。混合替换顺序由小到大；
每替换一级都必须重跑同一份输入并与 functional/TLM golden 比较，没有 stimulus 时只能报告
“黑盒可构建”。

## 4. 运行命令

所有真实 EDA 验证在 Ubuntu x86_64 执行：

```bash
dscflow circt run \
  --config configs/staged_circt.json \
  --input-root /path/to/verilog_dsc \
  --output-root .work/runs/staged-circt \
  --run-id x86-YYYYMMDD \
  --circt-root /path/to/circt \
  --circt-library-path /path/to/runtime-libraries
```

第一次运行会检查三个项目 Skill：`eda-tool-assistant`、`modeling-systemverilog` 和
`modeling-systemc-tlm`。若缺失，报告提供
`git clone --branch dev https://github.com/trv3wood/eda-sandbox.git ~/.codex/vendor/eda-sandbox`
安装命令；已有 Skill 时只记录缓存路径，不重新安装。

## 5. 产物

```text
run/
├── 00_input/             输入、UHDM 完整性与 Skill 证据
├── 01_tools/             工具路径、版本和哈希
├── 02_circt/             core IR、operation 清单和逐阶段日志
├── 03_verilator/         每个黑盒的头文件、库与编译日志
├── 04_agent_context/     受约束的局部修复输入
├── 05_hybrid/            混合替换顺序和下一门禁
└── report.json           顶层机器报告
```

## 6. 当前边界

VESA 顶层 C model、Function-TLM 和合成输入已经形成软件 golden；公司专用向量仍未提供。当前
HW 结构已完成验证，Comb/Seq 原生行为和分层子模块 function 仍是显式未完成项。后续先逐层细化
function，再从底层与 CIRCT 行为对齐，最后逐模块替换 Verilator 模型。

## 7. CIRCT 官方接口参考

- [HW-to-SystemC pass 列表](https://circt.llvm.org/docs/Passes/)
- [SystemC dialect 与 exporter](https://circt.llvm.org/docs/Dialects/SystemC/)
- [CIRCT firtool-1.155.0 release](https://github.com/llvm/circt/releases/tag/firtool-1.155.0)
