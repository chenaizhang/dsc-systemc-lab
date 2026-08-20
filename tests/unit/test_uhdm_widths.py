import json
from pathlib import Path

from tools.fill_uhdm_widths import (
    compute_width,
    definition_key,
    parse_circt_ports,
)


def test_compute_width_scalars() -> None:
    assert compute_width("i1") == 1
    assert compute_width("i12") == 12
    assert compute_width("i192") == 192


def test_compute_width_arrays() -> None:
    assert compute_width("!hw.array<18xi12>") == 216
    assert compute_width("!hw.array<4xi4>") == 16


def test_compute_width_nested_aggregates() -> None:
    # Nested structs/arrays print without the !hw. prefix.
    assert compute_width("!hw.array<3xstruct<y: i16, co: i16, cg: i16>>") == 144
    assert compute_width("!hw.array<3xstruct<res_y: i17, res_co: i17, res_cg: i17>>") == 153
    assert (
        compute_width("!hw.struct<follow_vsync: i1, encode_command: i4, chunk_size: i12>")
        == 17
    )


def test_definition_key_strips_library_prefix() -> None:
    assert definition_key("work@dsce_apb") == "dsce_apb"
    assert definition_key("dsce_apb") == "dsce_apb"


def test_parse_circt_ports(tmp_path: Path) -> None:
    ir = tmp_path / "sample.hw.mlir"
    ir.write_text(
        """
hw.module @top(in %clk : i1 loc(#loc1), in %data : i4, out sum : i8) {
  hw.output %sum : i8
}
hw.module private @child(in %a : !hw.array<3xstruct<y: i16, co: i16, cg: i16>> loc(#loc2), out b : i1) {
  hw.output %a#0 : i1
}
"""
    )
    ports = parse_circt_ports(ir)
    assert set(ports) == {"top", "child"}
    assert ports["top"]["clk"] == ("in", "i1", 1)
    assert ports["top"]["data"] == ("in", "i4", 4)
    assert ports["top"]["sum"] == ("out", "i8", 8)
    assert ports["child"]["a"][2] == 144
    assert ports["child"]["a"][1] == "!hw.array<3xstruct<y: i16, co: i16, cg: i16>>"


def test_merge_fills_widths(tmp_path: Path) -> None:
    import subprocess
    import sys

    ir = tmp_path / "sample.hw.mlir"
    ir.write_text(
        "hw.module @top(in %clk : i1, out data : i12) {\n  hw.output %data : i12\n}\n"
    )
    hierarchy = tmp_path / "hierarchy.json"
    hierarchy.write_text(
        json.dumps(
            {
                "designs": [
                    {
                        "module_definitions": ["work@top"],
                        "top_modules": [
                            {
                                "instance_name": "top",
                                "definition_name": "work@top",
                                "full_name": "top",
                                "ports": [
                                    {
                                        "name": "clk",
                                        "direction": "input",
                                        "width_bits": 0,
                                        "connected": False,
                                        "connection_name": "",
                                        "connection_full_name": "",
                                        "source_file": "t.sv",
                                        "source_line": 1,
                                    }
                                ],
                                "children": [],
                            }
                        ],
                    }
                ]
            }
        )
    )
    output = tmp_path / "structure_ir.json"
    result = subprocess.run(
        [sys.executable, "tools/fill_uhdm_widths.py",
         str(hierarchy), str(ir), str(output)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    merged = json.loads(output.read_text())
    assert merged["gates"]["widths_filled"] == 1
    assert merged["gates"]["widths_missing"] == 0
    assert merged["modules"][0]["ports"][0]["width_bits"] == 1
    assert merged["modules"][0]["ports"][0]["hw_type"] == "i1"
