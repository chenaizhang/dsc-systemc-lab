# DSC 混合差分 x86 完整验证报告

## 1. 目的

本次验证把三个模型层次放到同一条可复现流水线上：

1. 先用官方 VESA DSC C model 验证无内部硬件层次的 Function-TLM；
2. 把参考 RTL 用 Verilator `--sc` 生成可运行的 cycle-level SystemC；
3. 使用同一图像、PPS、APB 配置和 AXI 数据，对单体 RTL、拆分模块网络和真实混合替换网络做逐周期及最终码流差分。

正式 EDA、C++/SystemC 编译和仿真均在 `x86_64` 服务器完成。macOS 仅用于编辑和查看结果。

## 2. 模型与证据链

| 模型 | 组成 | 角色 |
|---|---|---|
| 软件 golden | VESA DSC C model 1.67 | 独立算法参考 |
| Function-TLM | VESA C adapter + 单顶层 TLM-2.0 wrapper | 顶层纯软件模型 |
| 单体 RTL-SystemC | `Vdsc_encoder` | Verilator 保真的 RTL 行为 |
| 拆分 RTL-SystemC | 7 个 Verilator 模块按 UHDM/CIRCT 结构连接 | 验证模块层次和胶水连线 |
| 混合 SystemC | `CycleApb` + 6 个 Verilator 黑盒 | 验证真实模块替换能力 |

拆分网络包含 `dsce_apb`、`dsce_command`、`dsce_engine`、`dsce_interrupt`、`dsce_pps`、`dsce_reset`、`dsce_timers`。`HybridTop` 的端口、实例和内部连接受已有 UHDM 层次及 CIRCT 结构证据约束，没有让 LLM 自行猜测顶层连线。

## 3. 输入与配置

- 图像：确定性 `192 × 108` RGB444、8 bpc；
- 切片：`96 × 108`，每行 2 个切片；
- 输入摘要：`d54ae9b32d303a4e1423160bc88b5ca854c24e272385ca63bfbdf9c5bb48b7f3`；
- PPS：取自同一次 VESA DSCF 输出的第 4～131 字节；
- RTL 配置：使用 APB 写入相同 PPS、像素/周期、切片数、输出宽度、chunk size 和 FRAME 命令；
- 三个 cycle 模型共用同一组 APB、AXI 输入和输出 ready。

这不是公司数据集。报告只能证明该公开配置向量，不能声称公司配置已通过。

## 4. 实施过程

### 4.1 软件模型门禁

VESA CLI 先生成 DSCF、128 字节 PPS 和 20,736 字节压缩 payload。Function-TLM adapter 使用同一 RGB 输入和配置运行，输出与 VESA payload 逐字节相同。

### 4.2 Verilator-SystemC

脚本分别对顶层和 7 个可替换模块运行 Verilator `--sc --timing`，构建对应静态库，再与 SystemC 测试驱动链接。服务器上的 Verilator timing runtime 需要 C++20，而 SystemC 3.0.2 库按 C++17 构建；构建命令关闭 SystemC 仅用于检测编译语言版本的 ABI 标记，实际链接和运行使用同一套 SystemC 3.0.2 头文件与库。

### 4.3 参考 RTL 缺失原语

交付的 `dsc_support_primitives.sv` 只声明了以下模块，没有行为：

- `gprim_sync_stage`；
- `gprim_sync2_stage`；
- `gram_bist_1r1w`。

第一次真实运行因此一直处于 bypass：APB 已写入 FRAME 命令，但空的同步器无法把命令送入 AXI 域。仓库新增仿真 shim，实现同步器和 1R1W 功能存储；BIST 保持确定性未激活，未模拟专有 BIST 行为。原始私有 RTL 未被改写，验证 filelist 显式替换该空壳文件。

### 4.4 拆分和替换

`HybridTop<Vdsce_apb>` 重建全 Verilator 模块网络；`HybridTop<CycleApb>` 在相同连线中把 APB 模块替换为手写 cycle-level SystemC。替换过程中发现 PPS_DATA 写入同周期拉低 READY 时，`CycleApb` 错误使用了更新后的 READY，导致 PPS 字节被丢弃；修复为按时钟沿开始时采样的 READY 接受事务后，替换网络与拆分 Verilator 网络逐周期一致。

## 5. x86 实测结果

测试环境：`x86_64`，Verilator 5.032，SystemC 3.0.2，GCC 15.2。

| 门禁 | 结果 | 证据 |
|---|---|---|
| VESA C 与 Function-TLM | 通过 | 20,736 字节逐字节一致 |
| 单体 RTL-SystemC 可运行 | 通过 | 进入编码态并产生输出 |
| 拆分模块网络 vs 单体 RTL | 通过 | 顶层接口逐周期一致，最终字节一致 |
| `CycleApb` 混合替换 vs 拆分网络 | 通过 | 无首差异周期，最终字节一致 |
| RTL-SystemC vs VESA golden | **失败** | 7,104 字节 vs 20,736 字节 |

三路 RTL/cycle 输出均为 7,104 字节且 SHA-256 相同。独立 golden 为 20,736 字节。RTL 的第一个 24 字节输出与 golden 完全相同，但从字节 24 开始出现差异；296 个 192-bit 输出字中有 148 对成对重复，且 250,000 个 drain 周期后仍未达到目标长度。接口日志还显示输出帧标志出现 1 次，但输出行结束标志为 0 次。

因此当前失败不是模块拆分连错，也不是 `CycleApb` 替换引入的，因为单体、拆分和混合三路行为完全一致。首个可疑模块边界已收敛到三路共同保留的 `dsce_engine` 输出路径：它没有产生任何完整行标志，并在目标码流完成前停止继续输出。更深一层仍可能是 engine 内部 slice/stream 控制，或仿真 shim 与专有 SRAM 的精确时序差异；这是基于接口证据的定位，不冒充已证明的单行 RTL 根因。Verilator 只能复现参考 RTL 行为，不能把这个结果当成算法 golden。

## 6. 结论

混合差分验证基础设施已经形成闭环：软件 golden、RTL Verilator-SystemC、UHDM/CIRCT 约束的拆分网络、真实模块替换、逐周期首差异和最终码流比较均已落地，并能由一个 x86 脚本重建。

本向量下可以确认：

- Function-TLM 是正确的软件参考；
- 模块层次和顶层胶水连线与单体 RTL 等价；
- `dsce_apb` 可被 cycle-level SystemC 实际替换且不改变行为；
- 参考 RTL 数据路径尚未通过独立 VESA 功能门禁。

不能确认：

- 专有 SRAM 的真实读写冲突和 BIST 语义；
- 其余 6 个模块已经被非 Verilator 的 cycle SystemC 替换；
- 公司图像及 PPS 配置已经验证。

机器可读结果位于 `evidence/results/hybrid_differential_x86.json`。每次运行还会生成按状态变化和有效输出采样的 `evidence/results/hybrid_differential_module_interface_trace.csv`；一键入口为 `scripts/run_hybrid_differential_verification.sh`。
