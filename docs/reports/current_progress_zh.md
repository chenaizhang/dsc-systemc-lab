# 当前落地进度与阻塞项

## 已完成

1. 软件参考：VESA C model、C++ adapter、Function-TLM 在 x86 上输出 20,736 字节，逐字节一致。
2. 共享刺激：`192 × 108` RGB、PPS、APB 和 AXI stream 已统一。
3. 混合仿真：单体 Verilator、7 模块拆分网络、`CycleApb` 替换网络逐周期一致。
4. engine 打桩：输入到 predict 的数据量和 line-last 完整，首个异常定位到
   `dsce_format/stream/format_buffer`。
5. UHDM：Surelog 1.84 为 0 error/0 warning，261 个实例全部导出；包含 236 个 generate 路径实例、
   3,155 个具名端口绑定和 60 个经 SV 核对的显式悬空输出。
6. CIRCT：真实设计 core IR 成功；`llhd.coroutine` conversion 失败和
   `systemc.convert/comb.icmp/comb.mux` emission 失败均已有独立最小复现。
7. x86 回归：26 个 Python 测试以及 UHDM、CIRCT、原始 RTL 差分、诊断 RTL 差分 5 个检查命令
   均返回 0。
8. 自主排障：已从 8 个待确认问题中自行闭合 7 个；确认 chunk 尾部 6 字节重复来自
   `dsce_slice_mux`，并确认剩余缺口是交付 RTL 缺失的 CBR line-last/flush 链。

## 当前没有完成

1. `dsce_engine` 尚未被独立 cycle SystemC 完整替换；现在只有 `CycleApb` 是非 Verilator 模块。
2. 原始 RTL 仍不匹配软件 golden：20,304 vs 20,736 字节，byte 24 首差异。
3. 安全诊断 overlay 仍未匹配 golden：20,232 vs 20,736 字节，byte 254 首差异；它已消除
   bypass 和 slice-mux 重复，但只得到 210/216 个 line marker。
4. CIRCT 尚不能原生发射可编译的完整 cycle SystemC。
5. UHDM 1.84 对部分复合端口给出 width 0，Agent 新结构指纹仍需 CIRCT HW type 补宽。

## 为什么现在只保留一个外部资料请求

时钟、SRAM 一拍读、启动门控、验收口径和重复发送点都已自行确认。当前交付 RTL 没有形成可验证
的 chunk/last 显式传播链；按端口名重建整链的 x86 反例只有 14,928 字节和 155 个 line marker。
继续猜 FIFO 指针协议会得到能编译但行为错误的模型。恢复实现只需正式 format/stream 源码，或一个
slice 两行的正确边界波形。可直接转发的最小请求见
`docs/blockers/format_stream_contract_questions_zh.md`。

## 后续正确顺序

```text
取得 format/stream last 链源码或两行正确波形
  → 用同一向量修正 RTL/Verilator 到 VESA golden
  → 生成 dsce_engine cycle SystemC 框架和行为
  → 从 format 子链开始逐模块替换
  → 每次替换做逐周期接口与最终 payload 差分
  → 处理 CIRCT conversion/emission patch，逐步减少 Verilator 黑盒
```
