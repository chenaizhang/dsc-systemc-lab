# DSC format/stream 行为合同（x86 实测）

## 结论

format/stream 级的码流拼装规则已从 VESA DSC 1.2 规格、C model 1.67 实测与
golden 码流三方推导并逐字节验证，可作为 RTL format/stream 阶段修复的行为合同
与验收向量。

## 推导依据

- **规格**：CBR 下 chunk_size = ceil(slice_width × bits_per_pixel / 8)；每行占
  整数个 chunk；行尾不足 48-bit muxword 的部分补零。
- **C model 实测**：在 `RemoveBitsEncoderBuffer` 的 CBR 分支插桩
  （`DSC_CHUNK_DUMP` 环境变量），确认速率缓冲目标恒定 768 位/行；前
  `initial_xmit_delay`(512) 像素无 chunk 事件。
- **golden 码流**：从 20,736 字节 payload 直接测出每行实际编码位数
  （尾部零位数法）。

## 合同内容

| 项 | 值 |
|---|---|
| 每行字节数（chunk_size） | 96（768 位 = 16 × 48-bit muxword） |
| 行数 | 108 × 2 slice = 216 |
| 拼装顺序 | line-major：每行 (slice0, slice1) 交替 |
| 总字节数 | 20,736 |
| 部分尾字行 | 128 / 216（补零 1~15 位） |
| 零数据行 | line 107 的 slice0/slice1 各 1 行（帧尾） |
| 补零分布 | 1,2,3,4,5,6,8,9,11,14,15,518,557,768 位 |

## 对 RTL 的约束（行为合同）

format/stream 阶段必须：

1. 每行每 slice 输出恰好 16 个 muxword（每 slice 共 1,728 个）；
2. 行尾编码位不足 48 时，最后一个 muxword 用零补齐并正常输出；
3. 帧尾两行为全零 muxword；
4. 不允许缩短或重复任何行（当前 RTL 每 slice 仅 1,693/1,680 个 muxword，
   即每行平均缺失约 0.3 个词，与已定位的 line-last/flush 断链一致）。

逐行验收向量见 `evidence/results/format_stream_contract_x86.json` 的
`per_line` 表（216 行：coded_bits / pad_bits / muxwords）。

## 复现

```bash
# 1. 重建带插桩的 C model（DSC_CHUNK_DUMP 环境变量控制输出）
make -C third_party/vesa-dsc-model-20211213/DSC_model_20211213/source all
DSC_CHUNK_DUMP=/tmp/chunks.log tools/run_dsc_reference_differential.py ...

# 2. 合同生成与验证
.work/venv/bin/python tools/format_stream_model.py \
  <golden.dsc> /tmp/chunks.log evidence/results/format_stream_contract_x86.json
```
