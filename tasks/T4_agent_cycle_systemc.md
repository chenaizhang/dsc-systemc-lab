# T4：UHDM 约束下逐层生成 Function SystemC

## 目标

先从顶层 Function-TLM 建立独立功能参考，再按 UHDM 层次逐层拆分为模块 function；每层均与上一层
做端到端同输入差分。底层 function 最终与 CIRCT Comb/Seq cycle SystemC 对齐。

## 工作

1. 使用 T2 生成的 `structure_contract.json`，禁止 Agent 自己猜层次和连线。
2. 用 `DscFunctionSlot` 作为行为注入点，但空 slot 不得计作已实现。
3. 从深度 1 开始填充子模块 function，每次拆解后与父级 function 的最终输出比较。
4. 从最底层开始，把 function 输出与 CIRCT Comb/Seq 模块逐周期或逐事务比较。
5. 执行运行时结构探针、systemc-clang 和 C++ 编译；结构与语义门禁分开报告。
6. CIRCT 暂不能处理的模块允许先嵌 Verilator-SystemC 黑盒，并记录边界。

## 验收

- 模块/端口/实例/连接与 UHDM 合同一致；
- systemc-clang 能识别模块和 process；
- SystemC 编译通过；
- 只称“语法与结构通过”，function 必须有共享输入差分证据才能标为 `verified`。

## 当前进度

- UHDM 同构骨架：261 实例、3,243 端口，运行时和 systemc-clang 通过。
- 顶层 Function-TLM：已验证。
- 深度 1～5：共 260 个子实例尚未形成经验证的 function；已有 cycle model 不冒充 function。
- 逐层计划和 CSV/JSONL 首差异比较器已落地，可在模型补齐后直接执行。
