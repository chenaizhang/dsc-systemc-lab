# DSC engine 数据路径 x86 定位报告

## 1. 目的

在软件 golden 已通过的前提下，判断 RTL-SystemC 的错误属于输入、切片处理、压缩算法还是
格式化输出，并为后续 `dsce_engine` cycle SystemC 替换提供可观测边界。

## 2. 方法

测试使用统一的 PPM、PPS、APB 写序列和 AXI stream。AXI 与 DSC 使用独立时钟，默认比例为
`dsc_clk:axi_clk = 3:1`；该比例高于规范公式对本配置给出的最低 `8:3`。测试驱动在 Verilator
public-flat 信号上采样以下握手边界：

```text
input → pack → partition → CSC → slice buffer
      → flatness → predict → slice output → slice mux → top AXI
```

先运行原始 RTL，再通过运行时 overlay 验证源码假设。overlay 不修改或提交私有 RTL，结果只用于
定位，不能作为正式功能修复。

## 3. 实测结果

### 3.1 时钟比例

原 1:1 测试只输出 7,104 字节。提高到 8:3 后输出 17,904 字节；3:1 与 4:1 达到同一吞吐平台。
因此旧结果混入了 DSC 时钟不足，后续统一使用 3:1。

### 3.2 原始 bypass 重复传输

3:1 下原始 RTL 输出由 423 对完全相同的相邻 192-bit 字组成。源码中最后一个 rate-buffer 字已经在
`eDS_RUNNING` 的 ready/valid 周期被接收，状态机随后仍进入 `eDS_TRANSFER_LAST`，再次发送同一载荷。
诊断 overlay 删除第二次传输后，成对重复消失。

### 3.3 engine 内部边界

安全握手 overlay 的最终计数如下：

| 边界 | slice 0 | slice 1 | 期望判断 |
|---|---:|---:|---|
| partition accept / last | 2,592 / 108 | 2,592 / 108 | 完整 |
| CSC accept / last | 2,592 / 108 | 2,592 / 108 | 完整 |
| slice buffer valid / last | 3,456 / 108 | 3,456 / 108 | 完整 |
| flatness valid / last | 3,456 / 108 | 3,456 / 108 | 完整 |
| predict valid / last | 3,456 / 108 | 3,456 / 108 | 完整 |
| slice output accept / last | 1,693 / 105 | 1,680 / 105 | 不完整 |

顶层收到 843 个 192-bit 字、210 个 line marker 和 1 个 frame marker。golden 为 864 个字，对应
20,736 字节；RTL 为 843 个字，对应 20,232 字节。前 254 字节一致，首差异位于 byte 254。

### 3.4 结构性缺口

当前 RTL 中的格式化输出边界无法形成完整的显式契约：

- `dsce_format.sv` 声明 `i_muxword_last_sb`，但没有使用；
- stream-builder 的 last 输入硬连为 0；
- format-buffer 没有 last 输入；
- 原始 `axi_last_out` 只有清零逻辑；
- `i_axi_xmit_okay` 已被同步，却未参与 format-buffer 控制。

基于 PPS `chunk_size` 补 last 后，两条 slice 都能输出。随后源码分析确认第 5 个字重复上一字末尾
6 字节来自 `dsce_slice_mux`：last 字已经完成握手，状态机仍把 `valid` 保持一拍。修正后重复消失，
首差异后移到 byte 254。

### 3.5 自主验证剩余待确认项

- 用户指南的时钟公式在当前 4 pixel/AXI-cycle、2 slice 配置下给出最低 `8:3`，所以 3:1 是
  有规范依据的保守值，不再需要人工确认。
- `format_buffer` 的 `DATA_INIT` 是同步 RAM 预取拍；当前 shim 的一拍读与状态机匹配。首 254 字节
  精确一致也排除了 RAM 基本读延迟是首错原因。
- `i_axi_xmit_okay` 由 `initial_xmit_delay` 产生，语义是 FIFO 预填充完成后允许 AXI 读启动。
- 本机三个历史副本和 `verilog_dsc.7z` 中相关 RTL 的 SHA-256 相同，没有隐藏的另一个版本。

### 3.6 被拒绝的 line-last 推断

`dsce_muxword` 内存在 `kUSE_FLUSH_LOGIC=0` 的完整数据分支，但交付代码同时缺失 muxword-last 输出、
FIFO last 存储/更新、builder chunk 完成逻辑和 format-buffer last 存储。为判断是否只是漏接信号，
实验性 overlay 开启 flush 并按现有端口意图补了一条 last 链。

该版本可通过 SystemVerilog 编译并运行，但只输出 14,928 字节、155/216 个 line marker，首差异
byte 240。因此它被自动验收门拒绝，没有进入默认修复。机器报告为
`evidence/results/format_stream_last_chain_x86.json`。

## 4. 结论

可以排除顶层拆分连线、APB 替换、输入、partition、CSC、flatness 和 predict 作为本向量的首个错误
边界。首个异常收敛到 `dsce_format → dsce_stream_builder/stream_fifo → dsce_format_buffer`。

现在可以排除 RAM 基本读延迟、时钟比例和顶层接口，剩余问题是 CBR 每行不足 48-bit muxword 时的
flush/padding 与 FIFO 指针协议。恢复正式修复只需一份完整 format/stream 源码，或一个 slice 连续
两行的正确边界波形；最小请求列在 `docs/blockers/format_stream_contract_questions_zh.md`。机器证据为
`evidence/results/repaired_rtl_differential_x86.json` 及三份 repaired trace CSV。
