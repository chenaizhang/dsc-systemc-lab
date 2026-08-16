# DSC 格式化输出路径：唯一剩余资料请求

## 已自行确认，不再询问

以下事项已经由源码、用户指南、VESA golden 和 x86 差分实验闭合：

- **验收规则**：按验收要求使用参考数据，压缩 payload 必须与 VESA C model 字节级一致；当前
  golden 为 20,736 字节。
- **时钟比例**：用户指南给出的公式在本配置下要求 `dsc_clk:axi_clk >= 8:3`；回归固定使用
  `3:1`，继续提高到 `4:1` 不增加吞吐。
- **`i_axi_xmit_okay`**：它由 PPS 的 `initial_xmit_delay` 倒计时产生并跨到 AXI 域，作用是等
  format FIFO 预填充后再启动读取。当前诊断 overlay 将它接回启动门控。
- **SRAM 读语义**：format-buffer 的 `DATA_INIT` 预取状态明确要求一拍同步读；shim 使用
  `posedge clk_r && en_r` 更新并在禁用时保持，符合该状态机。当前读写地址由异步 FIFO 指针隔离，
  本向量没有依赖同地址 read-during-write 的证据。
- **交付版本**：本机三个历史目录及原始 `verilog_dsc.7z` 中的 format/stream/bypass/slice-mux
  文件 SHA-256 完全一致，没有发现可替代的完整版本。
- **重复字节根因**：`dsce_slice_mux` 在 line-last 已握手后仍保持 `valid`，会把每个 chunk
  最后 6 字节发送两次；握手修正后重复消失。

## 为什么仍缺一份外部证据

交付 RTL 的 line-last 链不是单点错误，而是成套逻辑缺失：

- `dsce_format.sv` 把 stream-builder 的两个 last 输入硬连为 0；
- `dsce_muxword.sv` 有被常量关闭的 flush 分支，但没有 muxword-last 输出；
- `dsce_stream_fifo.sv` 的 last 输出只在复位时赋值，运行时从不更新；
- `dsce_stream_builder.sv` 的 last 输出同样只复位、不生成；
- `dsce_format_buffer.sv` 没有保存上游 last 的端口或 RAM 位。

安全握手 overlay 后，两个 slice 分别只产生 1,693 和 1,680 个 48-bit muxword；正确值应为
`108 行 × 16 muxword = 1,728`。结果为 20,232 字节、210/216 个 line marker，首差异 byte 254。
这说明剩余 504 字节主要是 CBR chunk 行尾 padding/flush 未生成。

仓库还实测了“开启 flush 并按端口名恢复 last 链”的推断版本，但只得到 14,928 字节和
155/216 个 line marker。该反例证明仅凭端口名无法可靠恢复 FIFO 指针与 chunk 完成协议，故没有
把它升级为默认修复。

## 唯一剩余上游资料请求

请提供以下二选一，任意一项即可：

1. 可正确运行的 `dsce_muxword.sv`、`dsce_stream_fifo.sv`、`dsce_stream_builder.sv`、
   `dsce_format_buffer.sv` 正式版本；或
2. 一小段 VCS 正确波形/CSV：任选一个 slice 的连续两行，包含
   `muxword_valid/data/last`、三个子流的 `valid/last/size`、format FIFO `we/waddr/ren/raddr` 和
   slice-mux `valid/ready/last`。

不再需要询问提示词、VCS 工具源码、完整工程、时钟比例或 SRAM 库。拿到上述任一证据后，就能
确定每行 flush/padding 的准确边沿，再继续 cycle SystemC 替换。
