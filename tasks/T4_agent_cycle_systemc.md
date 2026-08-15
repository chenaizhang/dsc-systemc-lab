# T4：UHDM 约束下生成 cycle SystemC

## 目标

Agent 根据 UHDM 结构合同和完整逐模块 SV 行为提示生成 signal-level、cycle-oriented SystemC。

## 工作

1. 使用 T2 生成的 `structure_contract.json`，禁止 Agent 自己猜层次和连线。
2. 组合逻辑实现为 `SC_METHOD`/普通纯函数；时序逻辑显式处理边沿、复位、enable 和 next-state。
3. 在每个模块接口加入稳定 `[SC_IF]` 日志开关。
4. 执行运行时结构探针、systemc-clang 和 C++ 编译。
5. CIRCT 暂不能处理的模块允许先嵌 Verilator-SystemC 黑盒，并记录边界。

## 验收

- 模块/端口/实例/连接与 UHDM 合同一致；
- systemc-clang 能识别模块和 process；
- SystemC 编译通过；
- 只称“语法与结构通过”，功能通过必须等待 T5/T6。
