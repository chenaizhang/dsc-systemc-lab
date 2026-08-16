# T2：UHDM 结构重建

## 目标

从当前私有 RTL 重新生成 UHDM，UHDM 是模块、端口、实例和连接的结构权威。

## 工作

1. 按 `inputs/private/rtl/README.upstream.md` 运行 Surelog。
2. 运行 `tools/export_uhdm_hierarchy.cpp` 并保留原始 UHDM 查询证据。
3. 不只导出 parent-child；补齐端口方向、实例绑定、连接全名和源码位置。
4. 生成新的 `evidence/uhdm/structure_ir.json`，更新结构指纹。
5. 执行 `dscflow uhdm-systemc prepare --config configs/uhdm_agent.json ...`。

## 验收

- Surelog 零 error、`uhdm-lint` 通过、top 唯一为 `dsc_encoder`；
- filelist/source SHA 与报告一致；
- 所有实例端口绑定已解析，未解析项单独列出，不能默认为通过；
- 逐模块 prompt 中结构来自 UHDM，行为提示包含完整对应 SV。

## 当前进度

- 已在 x86 服务器用 Surelog 1.84 从 43 个私有 RTL definition 重建 UHDM；结果为唯一 top、
  261 个实例、最大深度 9、0 fatal/0 syntax/0 error/0 warning，`uhdm-lint` 通过。
- exporter 已递归遍历 `vpiGenScope` 和 `vpiGenScopeArray`，层次 JSON 从旧的 25 个节点恢复为
  完整 261 个节点，其中 236 个实例位于 generate 路径。
- 可复现入口为 `scripts/run_uhdm_structure_verification.sh`，开发依赖由
  `containers/uhdm-dev.Containerfile` 固化。
- 已从本次数据库导出 3,243 个实例端口，其中 3,155 个具名绑定；60 个空表达式均与 SV 的显式
  悬空输出 `()` 对应。
- UHDM 1.84 对部分 packed/typed 端口报告 width 0；尚需用 CIRCT HW type 补齐并更新 Agent 结构
  指纹，T2 因此尚未整体完成。
