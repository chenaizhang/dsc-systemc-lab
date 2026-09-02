# 图像 IP 的 UHDM、CIRCT 与 Verilator-SystemC 复用说明

## 1. 交接目标

这套流程用于把第二个图像 IP 更快地整理成可验证的 SystemC：

1. CIRCT 解析 SystemVerilog，保留 HW/Comb/Seq/LLHD 中间表示；
2. UHDM 独立提取层次、实例、端口和绑定，辅助检查 CIRCT 生成结构；
3. CIRCT 能原生转换的模块生成 SystemC；
4. 暂时不能原生转换的叶子模块由 Verilator 生成 C++ 模型，并通过
   `systemc.interop.verilated` 内联到 CIRCT 生成的 SystemC 容器；
5. 使用同一输入做结构检查、编译门禁和逐周期差分。

UHDM 是结构参考，不负责生成行为，也不能替代功能差分。Verilator 模型忠实执行输入 RTL，
因此可作为 cycle-level 对照，但不能证明 RTL 算法本身正确。

## 2. 仓库

- 流程、脚本和中文文档：<https://github.com/chenaizhang/dsc-systemc-lab>
- CIRCT SystemC 修复分支：<https://github.com/chenaizhang/circt/tree/codex/systemc-backend>
- Linux x86_64 已验证二进制：<https://github.com/chenaizhang/circt/releases/tag/systemc-backend-0.1.5>
- 项目 Skill 来源：<https://github.com/trv3wood/eda-sandbox/tree/dev>

由专有 RTL 派生的 Verilator/CIRCT 模型不进入公开仓库，应通过内部文件渠道传递。

## 3. 输入目录约定

建议把第二个 IP 整理为以下形式：

```text
image_ip/
├── surelog.f
├── uhdm_module_hierarchy.json
├── build/surelog/slpp_all/surelog.log
├── rtl/*.sv
└── include/*
```

`surelog.f` 中的源文件路径相对于输入目录。UHDM JSON 必须包含一个 design，并提供模块定义、
顶层节点和递归子实例；Surelog 日志用于核对展开后的实例数及错误数。

如果交付包包含只有接口、没有仿真行为的工艺 primitive，必须在 `frontend.source_overrides`
中显式指定仿真替代源。例如同步器空壳不能直接交给 Verilator，否则跨时钟脉冲不会传播。
替代源同时用于 CIRCT frontend 和 Verilator reference，确保两条路径看到同一份可执行行为。

从模板复制配置：

```bash
cp configs/image_ip_template.json configs/image_ip_local.json
```

至少修改以下字段：

- `top`：顶层模块名；
- `inputs`：filelist、UHDM JSON 和 Surelog 日志的相对路径；
- `frontend.include_dirs`：额外头文件目录；
- `verilator.blackbox_tops`：需要作为 Verilator 黑盒的模块；
- `verilator.replacement_order`：由底层到顶层的替换顺序。

本地配置、RTL 和生成物都应放在 Git 忽略目录或仓库外部。

## 4. 第一次准备

正式 EDA 验证统一在 Ubuntu x86_64 环境运行：

```bash
git clone https://github.com/chenaizhang/dsc-systemc-lab.git
git clone --branch codex/systemc-backend https://github.com/chenaizhang/circt.git

cd dsc-systemc-lab
python3 -m venv .venv
. .venv/bin/activate
pip install -e .
dscflow skills
```

如果最后一条提示缺少 Skill，只在第一次运行：

```bash
dscflow skills --install
```

安装状态会缓存；后续循环不会重复下载或检查安装来源。

如果使用 Ubuntu Linux x86_64，可直接下载已通过 CI 门禁的 Release：

```bash
sha256sum -c circt-systemc-*.tar.gz.sha256
tar -xzf circt-systemc-*.tar.gz
cd circt-systemc-1dc04c4e9858d00d5820c417d64db26a6fd9322b-linux-x86_64
export PATH="$PWD/bin:$PATH"
```

该 Release 已通过 27/27 个 SystemC 相关回归，以及标量和 packed 聚合端口的
Verilator/SystemC 生成、C++ 编译链接与运行测试。其他架构或需要修改 CIRCT 时，
再按 LLVM/CIRCT 的标准 CMake 流程从分支构建。无论使用哪种方式，工具目录必须包含：

```text
build/bin/circt-verilog
build/bin/circt-opt
build/bin/circt-translate
build/lib/
```

## 5. 一条命令运行主流程

```bash
bash scripts/run_image_ip_systemc_pipeline.sh \
  configs/image_ip_local.json \
  /path/to/image_ip \
  .work/runs/image-ip \
  /path/to/circt/build
```

也可以直接调用：

```bash
dscflow circt run \
  --config configs/image_ip_local.json \
  --input-root /path/to/image_ip \
  --output-root .work/runs/image-ip \
  --circt-root /path/to/circt/build \
  --circt-library-path /path/to/circt/build/lib
```

每次运行会产生独立目录：

```text
run/
├── 00_input/          输入、UHDM 和 Skill 证据
├── 01_tools/          工具版本、路径和哈希
├── 02_circt/          core IR、HW/Comb/Seq 分析、SystemC 与错误日志
├── 03_verilator/      黑盒头文件、库和构建日志
├── 04_agent_context/  仅含局部缺口的受约束修复上下文
├── 05_hybrid/         替换顺序和后续验证计划
└── report.json        机器可读总报告
```

首先查看 `report.json`，再根据失败阶段进入对应目录，不需要人工翻阅全部日志。

## 6. CIRCT 内联 Verilator 的精确调用

### 6.1 先准备 CIRCT IR

先展开聚合端口，再插入 interop；两步不要倒置：

```bash
circt-opt \
  --hw-flatten-io="flatten-arrays=true join-char=_" \
  --hw-aggregate-to-comb \
  --hw-convert-bitcasts \
  --hw-aggregate-to-comb \
  input.llhd-lowered.mlir \
  -o prepared.mlir
```

### 6.2 生成混合 SystemC

```bash
circt-opt --verify-each=false \
  --systemc-wrap-verilated-instances="modules=LeafA,LeafB" \
  --symbol-dce \
  --convert-hw-to-systemc="prepared-input=true" \
  --systemc-lower-instance-interop \
  --systemc-lower-container-interop \
  prepared.mlir \
  -o mixed.systemc.mlir

circt-opt mixed.systemc.mlir -o /dev/null
circt-translate --export-systemc mixed.systemc.mlir -o mixed.systemc.hpp
```

`--verify-each=false` 只允许中间 pass 暂时形成反馈 SSA；命令结束后必须用第二条
`circt-opt` 对最终 IR 独立验证，不能省略。

### 6.3 为 interop 生成 Verilator 模型

Interop 会直接写成员、调用 `eval()` 再读成员，因此这里使用普通 C++ 模型。对于 packed
struct/array，不能直接让 Verilator 编译原始聚合端口 RTL。整份 prepared IR 仍可能包含
其他模块的 LLHD/Seq/Sim 操作，所以要逐个把目标叶子设为唯一 public 模块，先做 DCE 和
时序 lowering，再导出端口已展平的 SystemVerilog：

```bash
circt-opt --symbol-dce --llhd-lower-processes --canonicalize \
  --lower-seq-to-sv --canonicalize --export-verilog \
  leaf_a_public.mlir -o /dev/null > interop_LeafA.sv
verilator --cc --timing interop_LeafA.sv \
  --top-module LeafA --prefix VLeafA --Mdir obj_leaf_a
make -C obj_leaf_a -f VLeafA.mk -j2
```

这样 CIRCT SystemC 和 Verilator C++ 同时使用 `cfg_field`、`pixels_0` 等标量端口，聚合值的
pack/unpack 由 CIRCT 导出的 HDL 完成，不需要在 C++ 中猜测 SystemVerilog 位域顺序。

不要把 `verilator --sc` 产物直接接到 interop：`--sc` 暴露的是 `sc_in/sc_out`，不能按普通
C++ 数据成员直接赋值。`--sc` 仍可用于构建完整 RTL 的独立 SystemC 参考模型和差分基线。

## 7. 第二个 IP 的建议执行顺序

```text
SV 单模块编译
  → Surelog/UHDM 展开与结构 JSON
  → CIRCT core IR
  → HW 结构 SystemC 和 UHDM 结构交叉检查
  → 原生 Comb/Seq 转换
  → 失败叶子改为 Verilator --cc interop
  → SystemC C++ 编译、链接、运行
  → 与完整 Verilator --sc 参考逐周期差分
  → 再接独立软件 golden 判断算法功能
```

最终交接使用仓库中的源码构建模板，不能把其他机器生成的 `.a` 作为依赖：

```bash
cmake -S project -B build -G Ninja -DCMAKE_BUILD_TYPE=Release
cmake --build build --parallel 2
ctest --test-dir build --output-on-failure
```

模板会在当前机器重新运行 Verilator，同时执行 CDC shim 和混合 SystemC smoke test。

## 8. 当前 DSC 实测边界

| 产物 | x86 实测状态 | 用途 |
|---|---|---|
| 完整顶层 Verilator `--sc` | 已生成、编译 | RTL cycle-level 独立参考 |
| CIRCT HW 结构 SystemC | 已导出并通过 C++ 编译 | 检查模块、端口、层次和胶水连线 |
| 基础 Comb/Seq 与 Verilator interop 最小样例 | 已编译、链接、运行 | 证明修复路径闭环 |
| 引擎层 CIRCT + Verilator 混合 IR/C++ | IR 验证和 SystemC 导出通过 | 供第二实现比对及继续开发 |
| 引擎层混合 C++ 最终编译 | x86 源码重建、链接、运行通过 | 5 个叶子模型与 CIRCT 容器形成最小混合闭环 |
| 完整 encoder 混合 C++ | x86 源码重建、链接、运行通过 | CIRCT 顶层胶水 + UHDM 核对的 7 个直属 Verilator 子模块 |
| packed 宽端口 ABI | 192 位端口编译通过 | CIRCT helper 自动桥接 `sc_biguint` 与 Verilator `VlWide` |
| CDC shim | 单级、双级脉冲测试通过 | 不再用空壳同步器；仅代表通用仿真语义，不等价于专有工艺单元 |
| 图像功能差分 | 未通过最终门禁 | 不能宣称完整 DSC 混合模型功能正确 |

旧交接包直接编译原始聚合端口 RTL，导致 Verilator 只暴露 packed 成员，而 SystemC 容器访问
展平成员；旧包不能作为可用交付。新流程统一从 prepared IR 生成两边的端口 ABI，并要求全新
x86 CMake/CTest 已全部通过。交接包只携带源码、CMake 和验证脚本，不携带跨机器不可复用的
预编译 `.a`。

## 9. 结果判定

- UHDM 与 CIRCT 层次一致：只说明结构一致；
- SystemC 编译运行：只说明语法、链接和 elaboration 可用；
- 与 Verilator 逐周期一致：说明生成模型与当前 RTL 行为一致；
- 与独立软件 golden 一致：才能说明被覆盖用例的图像算法输出正确。

四层证据必须分别报告，不能相互替代。
