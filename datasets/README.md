# 测试数据

当前没有公司提供的输入图片、PPS、寄存器配置序列和参考压缩码流。

已验证的唯一数据是工具自动生成的 `192x108 RGB 4:4:4 / 8bpc / 8bpp / 双 slice`
合成图。`models/function_tlm/run_x86_verify.sh` 会在 `.work/runs/vesa-differential/` 重新生成
PPM 输入和 VESA `.dsc` 参考结果，不依赖仓库内预存二进制向量。

公司向量到位后，按 `manifest.json` 中的五阶段文件名放置，并通过 `dscflow golden compare`
逐阶段门禁。
