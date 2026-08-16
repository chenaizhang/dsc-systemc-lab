# T6：逐模块差分与混合替换

## 目标

以全 Verilator-SystemC 为参考，逐模块替换为 Agent/CIRCT cycle SystemC，并定位第一处分歧。

## 工作

1. 建立统一 stimulus driver 和端口规范化 adapter。
2. 先跑全 Verilator，生成 `rtl_verilator.results.json`。
3. 按 `dsce_apb → dsce_engine → dsc_encoder` 从小到大替换。
4. 每次替换都比较模块接口日志和最终 bitstream；失败时定位第一周期、第一接口。
5. 修正 SystemC 后反向核查 RTL 是否也需修复。

## 验收

- 每个替换组合有机器可读报告；
- 最终输出与 T5 软件 golden 一致；
- 所有 cycle SystemC 替换通过后，才可把对应 RTL 标为该数据集下功能通过。

## 当前进度

| 项目 | 状态 |
|---|---|
| 统一 PPM/PPS/APB/AXI stimulus | 已完成 |
| 单体 `Vdsc_encoder` Verilator-SystemC | 已完成 |
| 7 模块拆分网络与单体逐周期差分 | 已通过 |
| `dsce_apb → CycleApb` 真实混合替换 | 已通过 |
| 独立时钟与 engine 内部探针 | 已完成：默认 `dsc_clk:axi_clk=3:1` |
| 最终输出与 VESA golden | 未通过：安全 overlay 后 20,232 vs 20,736 字节，首差异 byte 254 |
| 首个异常边界 | 已定位到 `dsce_format/stream/format_buffer` |
| 自主假设验证 | 已定位并消除 bypass/slice-mux 重复；推断 last 链版本因 155/216 line-last 被拒绝 |
| 其余 6 模块 cycle SystemC 替换 | 待完成 |

详细过程见 `docs/reports/hybrid_differential_x86.md` 和
`docs/reports/engine_localization_x86.md`。当前只缺正式 last/chunk 传播实现或一段正确边界波形，
不得把诊断 overlay 作为生产修复，也不得把 T6 整体标成算法功能通过。
