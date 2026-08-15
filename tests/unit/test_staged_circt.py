from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

from dscflow.workflows.staged_circt.evidence import analyze_inputs
from dscflow.workflows.staged_circt.mlir import (
    analyze_core_ir,
    classify_circt_failure,
)
from dscflow.workflows.staged_circt.runner import _verilator_port_names
from dscflow.workflows.staged_circt.utils import run_command


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_input_evidence_exposes_incomplete_uhdm_export(tmp_path: Path) -> None:
    _write(tmp_path / "surelog.f", "+incdir+.\nkeep.sv\nbroken.sv\n")
    _write(tmp_path / "keep.sv", "module top; endmodule\n")
    _write(tmp_path / "broken.sv", "module unused; bad_t value; endmodule\n")
    hierarchy = {
        "source": "surelog.uhdm",
        "designs": [
            {
                "module_definitions": ["work@top", "work@unused"],
                "top_modules": [
                    {
                        "instance_name": "work@top",
                        "definition_name": "work@top",
                        "full_name": "",
                        "children": [],
                    }
                ],
                "invocations": [],
            }
        ],
    }
    hierarchy_path = tmp_path / "hierarchy.json"
    _write(hierarchy_path, json.dumps(hierarchy))
    _write(
        tmp_path / "surelog.log",
        """Nb Top level modules: 1.
Max instance depth: 3.
Nb instances: 5.
Nb leaf instances: 2.
[  FATAL] : 0
[ SYNTAX] : 0
[  ERROR] : 0
[WARNING] : 0
""",
    )
    expected_hash = hashlib.sha256(hierarchy_path.read_bytes()).hexdigest()
    config = {
        "inputs": {
            "filelist": "surelog.f",
            "hierarchy_json": "hierarchy.json",
            "surelog_log": "surelog.log",
        },
        "expected": {
            "hierarchy_sha256": expected_hash,
            "definition_count": 2,
            "provided_hierarchy_nodes": 1,
            "surelog_instances": 5,
        },
        "frontend": {
            "exclude_uninstantiated_sources": [
                {
                    "source": "broken.sv",
                    "definition": "unused",
                    "reason": "unit-test fixture",
                }
            ]
        },
    }

    report = analyze_inputs(tmp_path, config)

    assert report["pass"] is True
    assert report["canonical_hierarchy_ready"] is False
    assert report["hierarchy_completeness"]["missing_or_unrepresented_nodes"] == 4
    assert report["source_plan"]["reachable_sources"] == ["keep.sv"]


def test_core_ir_inventory_separates_structure_comb_seq_and_llhd() -> None:
    mlir = r'''
module {
  hw.module @top(in %clk : !seq.clock, in %a : i8, out y : i8) {
    %sum = comb.add %a, %a : i8
    %reg = seq.compreg %sum, %clk : i8
    %out = hw.instance "u_child" @child(a: %reg: i8) -> (y: i8)
    hw.output %out : i8
  }
  hw.module @child(in %a : i8, out y : i8) {
    %p = llhd.prb %a : i8
    hw.output %a : i8
  }
}
'''

    report = analyze_core_ir(mlir, "top")

    assert report["top_found"] is True
    assert report["module_count"] == 2
    assert report["instance_operation_count"] == 1
    assert report["instances"] == [
        {"parent": "top", "instance": "u_child", "module": "child"}
    ]
    assert report["dialect_totals"]["comb"] == 1
    assert report["dialect_totals"]["seq"] == 1
    assert report["dialect_totals"]["llhd"] == 1
    assert report["stage_partitions"]["seq_modules"] == ["top"]
    assert report["stage_partitions"]["llhd_modules"] == ["child"]


def test_failure_classifier_preserves_stage_and_operation() -> None:
    report = classify_circt_failure(
        "error: failed to legalize operation 'llhd.coroutine' that was explicitly marked illegal",
        "hw_to_systemc",
    )

    assert report == {
        "kind": "unsupported_llhd_conversion",
        "stage": "hw_to_systemc",
        "operation": "llhd.coroutine",
        "symbol": None,
        "owner": "circt_conversion",
        "llm_may_change_structure": False,
        "requires_local_reproducer": True,
    }


def test_frontend_failure_classifier_names_bad_symbol() -> None:
    report = classify_circt_failure(
        "sample.sv:4:9: error: use of undeclared identifier 'tDSC_SAMPLE'",
        "frontend_all_sources",
    )

    assert report is not None
    assert report["kind"] == "frontend_undeclared_identifier"
    assert report["symbol"] == "tDSC_SAMPLE"


def test_command_logs_non_utf8_tool_output_without_crashing(tmp_path: Path) -> None:
    report = run_command(
        "non_utf8",
        [
            sys.executable,
            "-c",
            "import os; os.write(2, bytes([0xff, 0xfe, 10]))",
        ],
        cwd=tmp_path,
        output_dir=tmp_path / "logs",
        timeout=5,
    )

    assert report["pass"] is True
    assert "\ufffd" in (tmp_path / "logs/non_utf8.stderr.log").read_text(
        encoding="utf-8"
    )


def test_verilator_systemc_reference_ports_are_recognized(tmp_path: Path) -> None:
    header = tmp_path / "Vtop.h"
    _write(
        header,
        """class Vtop {
  sc_core::sc_in<bool> &clk;
  sc_core::sc_out<sc_dt::sc_bv<92> > &cfg;
  sc_core::sc_in<uint32_t> (&bist)[18];
  sc_in<uint32_t> data;
};
""",
    )

    assert _verilator_port_names(header) == ["bist", "cfg", "clk", "data"]
