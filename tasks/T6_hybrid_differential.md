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
