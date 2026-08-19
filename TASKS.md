# 新任务拆分

下面每项都能单独开一个 Codex 任务。顺序是依赖顺序，不要把六项重新揉成一个大任务。

| ID | 任务 | 输入 | 完成条件 |
|---|---|---|---|
| T1 | x86 环境与输入基线 | 私有 RTL/spec、VESA model | 资产 SHA、Python 回归、SystemC/VESA 三路测试通过 ✅ |
| T2 | UHDM 结构重建 | `inputs/private/rtl/surelog.f` | 261 实例层次已恢复；端口宽度已用 CIRCT HW IR 补全（3,243/3,243），结构指纹已更新 ✅ |
| T3 | CIRCT 分阶段定位 | T2 RTL/UHDM、CIRCT | 两个最小复现 + fork 内聚合管线/时序 process pass 已落地（全量 lit 1627 通过）✅ |
| T4 | Agent cycle SystemC | T2 结构合同、逐模块 SV | 结构、systemc-clang、C++ 编译均通过 ✅ |
| T5 | 共享 stimulus 与软件 golden | 公司向量或批准的 VESA 向量 | Function-TLM 输出获得 golden-qualified 结果集 ✅ |
| T6 | 差分与混合替换 | T4、T5、Verilator --sc | 首错定位到 format/stream；行为合同已推导（每行 16 muxword、128/216 行需补零 flush）；按合同修复 overlay 进行中 |

## 附：format/stream 行为合同（2026-08-19 新增）

- 合同文件：`evidence/results/format_stream_contract_x86.json`（216 行逐行
  coded_bits/pad_bits/muxwords 表）
- 报告：`docs/reports/format_stream_contract_x86.md`
- 关键结论：CBR 每行固定 96 字节；128/216 行存在 1~15 位行尾补零（部分尾 muxword
  必须零补齐后输出）；帧尾 2 行零数据；line-major 交替拼接。
- RTL 修复方向：format/stream 阶段每行必须恰好输出 16 个 muxword（每 slice
  1,728 个）；当前诊断 overlay 每 slice 仅 1,693/1,680 个。
