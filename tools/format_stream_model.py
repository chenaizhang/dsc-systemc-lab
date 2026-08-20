#!/usr/bin/env python3
"""DSC format/stream 行为模型与合同验证。

依据 VESA DSC 1.2 规格、C model 实测与 golden 码流，推导 format/stream 级的
码流拼装规则，并用 192x108 双 slice 测试向量逐字节验证：

- CBR 模式下每行固定 chunk_size 字节
  （chunk_size = ceil(slice_width x bits_per_pixel / 8) = 96 字节 = 768 位）；
- 每行编码位数可变；行尾不足 48-bit muxword 的部分用零补齐
  （golden 中 128/216 行存在 1~17 位补零，另有 2 行零数据帧尾）；
- payload 逐行交替拼接（line-major：line0-slice0, line0-slice1, ...）；
- 总计 slice_height x slices_per_line x chunk_size = 108 x 2 x 96 = 20,736 字节。

输出合同包含 216 行的逐行编码位数表，作为 RTL format/stream 阶段的
行为合同与修复验收向量。

用法:
  format_stream_model.py GOLDEN_DSC CHUNK_DUMP OUTPUT_CONTRACT
"""

import hashlib
import json
import pathlib
import sys


def parse_chunk_dump(dump_path):
    """Parse the instrumented C model dump: (chunk_index, num_bits, chunk_size)
    per chunk-end event. num_bits is the rate-buffer removal target, which is
    constant at 8 bpp; the actual coded length is derived from the golden."""
    chunks = []
    for line in pathlib.Path(dump_path).read_text().splitlines():
        parts = line.split()
        if len(parts) != 3:
            continue
        chunks.append((int(parts[1]), int(parts[2])))
    return chunks


def trailing_zero_bits(chunk: bytes) -> int:
    bits = "".join(f"{byte:08b}" for byte in chunk)
    return len(bits) - len(bits.rstrip("0"))


def per_line_table(payload: bytes, chunk_size: int, slices: int,
                   lines_per_slice: int):
    """Return per-line records in assembly order (line-major)."""
    assert len(payload) == chunk_size * slices * lines_per_slice, (
        f"payload {len(payload)} does not match "
        f"{chunk_size}x{slices}x{lines_per_slice}"
    )
    table = []
    for line in range(lines_per_slice):
        for slice_x in range(slices):
            offset = (line * slices + slice_x) * chunk_size
            chunk = payload[offset : offset + chunk_size]
            pad = trailing_zero_bits(chunk)
            coded = chunk_size * 8 - pad
            muxwords = (coded + 47) // 48
            table.append(
                {
                    "line": line,
                    "slice": slice_x,
                    "coded_bits": coded,
                    "pad_bits": pad,
                    "muxwords": muxwords,
                    "full_muxwords": coded // 48,
                }
            )
    return table


def main():
    if len(sys.argv) != 4:
        print(
            "usage: format_stream_model.py GOLDEN_DSC CHUNK_DUMP OUTPUT_CONTRACT",
            file=sys.stderr,
        )
        return 2

    golden_path = pathlib.Path(sys.argv[1])
    dump_path = pathlib.Path(sys.argv[2])
    output_path = pathlib.Path(sys.argv[3])

    raw = golden_path.read_bytes()
    # The raw VESA .dsc output carries a 132-byte prefix; the adapter payload
    # starts after it. Accept both the raw file and the bare payload.
    payload = raw[len(raw) - 20736 :] if len(raw) > 20736 else raw

    # The contract is derived for the 192x108 two-slice case, but the
    # framing logic works for any payload that is a multiple of one line
    # (two 96-byte chunks).
    assert len(payload) % (96 * 2) == 0, "payload is not line-aligned"
    lines_per_slice = len(payload) // (96 * 2)
    table = per_line_table(payload, 96, 2, lines_per_slice)
    dump = parse_chunk_dump(dump_path)

    partial_lines = [row for row in table if row["pad_bits"] > 0]
    zero_lines = [row["line"] for row in table if row["coded_bits"] == 0]
    target_ok = all(bits == 768 for bits, _ in dump)

    verdict = (
        len(table) == 216
        and len(partial_lines) == 128
        and zero_lines == [107, 107]  # final line, both slices
    )

    contract = {
        "format": "llm4eda-dsc-format-stream-contract",
        "version": "1.0.0",
        "source": {
            "golden": str(golden_path),
            "golden_sha256": hashlib.sha256(raw).hexdigest(),
            "chunk_dump": str(dump_path),
            "instrumentation": (
                "DSC_model_20211213 dsc_codec.c RemoveBitsEncoderBuffer CBR "
                "branch (DSC_CHUNK_DUMP)"
            ),
        },
        "derivation": {
            "chunk_size_bytes": 96,
            "chunk_size_bits": 768,
            "formula": "chunk_size = ceil(slice_width x bits_per_pixel / 8)",
            "lines_per_slice": 108,
            "slices": 2,
            "total_bytes": 20736,
            "assembly_order": "line-major: (line, slice0, slice1) per line",
            "padding_rule": (
                "each line occupies exactly chunk_size bytes; the coded bits "
                "are followed by zero padding, including the completion of a "
                "partial final 48-bit muxword"
            ),
            "muxword_bits": 48,
            "muxwords_per_line_full": 16,
        },
        "observations": {
            "chunk_events": len(dump),
            "rate_buffer_target_constant_768": target_ok,
            "payload_chunks": len(table),
            "lines_with_padding": len(partial_lines),
            "padding_distribution": sorted(
                {row["pad_bits"] for row in table}
            ),
            "zero_data_lines": zero_lines,
        },
        "per_line": table,
        "verdict": {
            "framing_contract_holds": verdict,
            "rtl_implication": (
                "the format/stream stage must emit exactly 16 muxwords per "
                "line per slice: the coded muxwords followed by one "
                "zero-completed partial muxword when the line has padding "
                "bits, and a full zero muxword for the two frame-tail lines. "
                "Total per slice: 1,728 muxwords."
            ),
        },
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(contract, indent=1) + "\n")

    print(
        f"format/stream contract: lines={len(table)} "
        f"partial={len(partial_lines)} zero_lines={zero_lines} "
        f"verdict={verdict}"
    )
    return 0 if verdict else 1


if __name__ == "__main__":
    sys.exit(main())
