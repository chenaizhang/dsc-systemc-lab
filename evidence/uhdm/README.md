# UHDM 证据说明

- `module_hierarchy.json`：2026-08-15 在 x86 上由 Surelog 1.84 UHDM 数据库重新导出的父子模块摘要；
  已覆盖 generate scope，共 43 个 definition、261 个实例节点、260 条调用边、3,155 个具名实例
  端口绑定和 60 个 SV 显式悬空输出。连接来自 `vpiHighConn`；内部 signal/net 驱动图尚未导出。
  UHDM 1.84 对所有端口均报告宽度 0，宽度以 `structure_ir.json` 中的 CIRCT 补宽为准。
- `structure_ir.json`：规范化结构合同 v2（`llm4eda-uhdm-dual-framework` 2.0.0）。层次、端口名、
  方向和连接以 UHDM 为权威；每个端口的 `hw_type` 与 `width_bits` 由 CIRCT HW IR 端口签名交叉
  补全（`tools/fill_uhdm_widths.py`），3,243 个端口全部非零、与 SV 声明一致（抽查 11 处含嵌套
  聚合）。`structural_fingerprint` 基于补宽后的模块端口表计算。
- `producer.json`、`uhdm-hier.log`：生产命令、工具和原始层次日志。
- `surelog.log` 和空输出的 `uhdm-lint.log` 是本次重建日志。

`surelog.uhdm` 与 CIRCT core IR 保留在服务器（`.work/uhdm`、`.work/dsc_encoder.hw.mlir`），
不提交 Git；`structure_ir.json` 的 `provenance.hw_mlir_sha256` 记录 core IR 哈希以便复现。
