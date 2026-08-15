# UHDM 证据说明

- `module_hierarchy.json`：赖聪流程导出的原始父子模块摘要；只表示模块包含关系，不包含端口、
  signal 或 net 连接。
- `structure_ir.json`：旧仓库真实 UHDM 查询后规范化的端口/实例/连接结构快照，当前
  `configs/uhdm_agent.json` 使用它生成结构合同。
- `producer.json`、`uhdm-hier.log`：生产命令、工具和原始层次日志。

`structure_ir.json.provenance` 中的 `cases/...` 路径是不可改写的历史来源记录，在新仓库内不会
解析；相关大型 JSONL 和 260 MB `surelog.uhdm` 没有迁移。T2 应在 x86 上从
`inputs/private/rtl/surelog.f` 重建证据，生成新结构指纹后再更新配置。

