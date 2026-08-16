# DSC 数据通路定位与 cycle SystemC 替换任务

## 目标

在 x86 服务器上沿同一份 PPM、PPS 和 APB/AXI-Stream stimulus，继续完成以下工作：

1. 从 SPEC 和 RTL 固化 AXI/DSC 独立时钟、帧行标记和输入像素映射契约；
2. 对 `dsce_engine` 的 pack、partition、slice 和 slice-mux 边界记录逐周期握手及行尾信息；
3. 确定压缩输出短缺和成对重复首次出现的模块边界；
4. 只有在行为契约有证据时，生成并替换对应 cycle SystemC 模块；
5. 修复 UHDM generate-scope 层次导出，并隔离 CIRCT 首个不支持 operation。

## 事实边界

- 官方 VESA model 是独立功能参考；Verilator-SystemC 仅复现交付 RTL 行为。
- 交付的 `gram_bist_1r1w` 是空模块；缺少官方 primitive model 时，仿真替代物的读延迟与冲突语义必须显式记录。
- 用户指南规定 APB、AXI、DSC 为独立时钟域；不得把等频测试结果泛化为平台结论。
- 不允许根据输出错误反推并硬编码算法行为；SystemC 替换必须来自 SPEC、RTL/UHDM/CIRCT 证据。
- 正式编译、仿真和 EDA 结论仅来自 x86_64 服务器。

## 验收

- 机器结果记录测试时钟比例、RAM 模型语义、输入摘要、边界计数和首个异常边界；
- pack、partition、每个 slice 和 slice-mux 至少有 valid/ready/last 或 line 的逐周期计数；
- 如缺少外部契约，生成可直接询问项目成员的中文问题清单，不伪造结论；
- UHDM 层次导出能遍历 generate scope，或保存可复现失败证据；
- CIRCT 缺口具有最小复现或明确的首个不支持 operation；
- Python 回归与 x86 一键验证均通过。
