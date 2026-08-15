# 新任务拆分

下面每项都能单独开一个 Codex 任务。顺序是依赖顺序，不要把六项重新揉成一个大任务。

| ID | 任务 | 输入 | 完成条件 |
|---|---|---|---|
| T1 | x86 环境与输入基线 | 私有 RTL/spec、VESA model | 资产 SHA、Python 回归、SystemC/VESA 三路测试通过 |
| T2 | UHDM 结构重建 | `inputs/private/rtl/surelog.f` | 新 UHDM 数据库、端口/实例/连接结构合同通过 |
| T3 | CIRCT 分阶段定位 | T2 RTL/UHDM、CIRCT | HW/Comb/Seq/LLHD 阶段报告和最小失败复现 |
| T4 | Agent cycle SystemC | T2 结构合同、逐模块 SV | 结构、systemc-clang、C++ 编译均通过 |
| T5 | 共享 stimulus 与软件 golden | 公司向量或批准的 VESA 向量 | Function-TLM 输出获得 golden-qualified 结果集 |
| T6 | 差分与混合替换 | T4、T5、Verilator --sc | 全 Verilator 起步，逐模块替换后最终输出保持一致 |
