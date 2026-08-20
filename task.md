# 分层 SystemC 等价建模任务

## 目标

在 x86 服务器上完成两条可汇合的实现线：

1. 修复 CIRCT 完整 HW→SystemC 转换中由聚合 `hw.bitcast` 暴露的 LLHD/聚合类型降级缺口，并继续记录后续首个不支持 operation；
2. 为顶层直属的 7 个子模块建立有证据来源的 function contract、可执行 SystemC function model 和端到端等价门禁；
3. 保持 CIRCT 结构骨架与 UHDM reference 层次自动对比；
4. 为后续从底层开始用 Comb/Seq 生成模块替换 function model 保留统一接口。

## 事实边界

- 官方 VESA model 是独立功能参考；Verilator-SystemC 仅复现交付 RTL 行为。
- 交付的 `gram_bist_1r1w` 是空模块；缺少官方 primitive model 时，仿真替代物的读延迟与冲突语义必须显式记录。
- 用户指南规定 APB、AXI、DSC 为独立时钟域；不得把等频测试结果泛化为平台结论。
- 不允许根据输出错误反推并硬编码算法行为；SystemC 替换必须来自 SPEC、RTL/UHDM/CIRCT 证据。
- 正式编译、仿真和 EDA 结论仅来自 x86_64 服务器。

## 验收

- CIRCT fork 对最小 `hw.bitcast` 复现和真实 DSC 输入均有自动回归；
- 完整转换越过现有聚合 `hw.bitcast` 阻塞点，并保存新的首个失败点或可编译产物；
- 7 个直属子模块均具有输入、输出、状态、时序、错误行为和证据来源明确的 contract；
- 分层 function SystemC 可编译、可运行，并与顶层 reference model 使用同一测试数据做端到端比较；
- 没有独立参考证据的模块不得标记为语义通过；
- UHDM/SystemC 层次对比、Python 回归与 x86 一键验证均通过。
