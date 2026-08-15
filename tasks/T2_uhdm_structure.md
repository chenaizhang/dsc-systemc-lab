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
