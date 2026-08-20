import json
from pathlib import Path

from tools.format_stream_model import (
    parse_chunk_dump,
    per_line_table,
    trailing_zero_bits,
)


def test_trailing_zero_bits() -> None:
    assert trailing_zero_bits(b"\xff") == 0
    assert trailing_zero_bits(b"\x00") == 8
    assert trailing_zero_bits(b"\x80") == 7  # 0b1000_0000
    assert trailing_zero_bits(b"\x0c") == 2  # 0b0000_1100


def test_per_line_table_shape() -> None:
    payload = bytes(96 * 2 * 3)
    table = per_line_table(payload, 96, 2, 3)
    assert len(table) == 6
    assert [row["slice"] for row in table] == [0, 1, 0, 1, 0, 1]
    assert all(row["coded_bits"] == 0 for row in table)


def test_per_line_table_partial_muxword() -> None:
    # One line whose last byte carries 4 pad bits.
    payload = bytearray(96 * 2)
    payload[95] = 0xF0  # line0-slice0: 4 zero bits at the end
    payload[96 + 95] = 0xFF  # line0-slice1: full byte, no padding
    table = per_line_table(bytes(payload), 96, 2, 1)
    assert table[0]["coded_bits"] == 768 - 4
    assert table[0]["pad_bits"] == 4
    assert table[0]["muxwords"] == 16
    assert table[1]["pad_bits"] == 0


def test_parse_chunk_dump(tmp_path: Path) -> None:
    dump = tmp_path / "chunks.log"
    dump.write_text("0 768 96\n1 768 96\n")
    assert parse_chunk_dump(dump) == [(768, 96), (768, 96)]


def test_contract_golden_fixture(tmp_path: Path) -> None:
    """End-to-end: a synthetic 2x1-slice payload produces a valid contract."""
    import subprocess
    import sys

    payload = bytearray(96 * 2)
    payload[95] = 0xF0
    payload[96 + 95] = 0xFF
    golden = tmp_path / "golden.dsc"
    golden.write_bytes(bytes(payload))
    dump = tmp_path / "chunks.log"
    dump.write_text("0 768 96\n1 768 96\n")
    out = tmp_path / "contract.json"
    result = subprocess.run(
        [sys.executable, "tools/format_stream_model.py",
         str(golden), str(dump), str(out)],
        capture_output=True,
        text=True,
        check=False,
    )
    # The synthetic fixture is not the 192x108 golden, so the verdict gate
    # fails; the tool must still produce a well-formed contract.
    assert result.returncode == 1
    contract = json.loads(out.read_text())
    assert contract["format"] == "llm4eda-dsc-format-stream-contract"
    assert len(contract["per_line"]) == 2
