# UHDM 证据说明

- `module_hierarchy.json`：2026-08-15 在 x86 上由 Surelog 1.84 UHDM 数据库重新导出的父子模块摘要；
  已覆盖 generate scope，共 43 个 definition、261 个实例节点、260 条调用边、3,155 个具名实例
  端口绑定和 60 个 SV 显式悬空输出。连接来自 `vpiHighConn`；内部 signal/net 驱动图尚未导出。
- `structure_ir.json`：旧仓库真实 UHDM 查询后规范化的端口/实例/连接结构快照，当前
  `configs/uhdm_agent.json` 使用它生成结构合同。
- `producer.json`、`uhdm-hier.log`：生产命令、工具和原始层次日志。

`surelog.log` 和空输出的 `uhdm-lint.log` 是本次重建日志，`uhdm-hier.log` 是原生层次对照。
大型 `surelog.uhdm` 保留在服务器 `.work/uhdm`，不提交 Git。下一步需用 CIRCT HW type 补齐 UHDM
报告为 0 的复合端口宽度，并把本次层次/绑定转换成 Agent 使用的新结构指纹。
