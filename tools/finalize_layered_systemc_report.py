#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"expected JSON object: {path}")
    return value


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Create a path-sanitized layered SystemC verification summary."
    )
    parser.add_argument("--staged-report", type=Path, required=True)
    parser.add_argument("--uhdm-report", type=Path, required=True)
    parser.add_argument("--layer-plan", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    staged = read_json(args.staged_report)
    uhdm = read_json(args.uhdm_report)
    plan = read_json(args.layer_plan)
    circt = staged["circt"]
    hw = circt["stage_matrix"]["hw"]
    static = circt.get("structure_systemc_clang", {})
    runtime = uhdm["runtime_structure"]
    uhdm_modules = runtime["observed"]["modules"]
    uhdm_ports = runtime["observed"]["ports"]
    models = staged["verilator"]["models"]

    summary = {
        "format": "dsc-layered-systemc-equivalence-x86",
        "version": "1.0.0",
        "environment": "x86_64 Linux validation host",
        "uhdm_reference": {
            "pass": uhdm["pass"],
            "runtime_module_count": len(uhdm_modules),
            "runtime_port_count": len(uhdm_ports),
            "systemc_clang_pass": uhdm["systemc_clang"]["pass"],
            "systemc_clang_target_count": len(
                uhdm["systemc_clang"].get("targets", [])
            ),
        },
        "circt_hw_structure": {
            "pass": hw["systemc_skeleton_pass"],
            "definition_count": hw["module_count"],
            "definition_edge_count": hw["instance_operation_count"],
            "runtime_module_count": hw["runtime_module_count"],
            "flattened_runtime_port_count": hw["runtime_port_count"],
            "cpp_compile_pass": hw["structure_cpp_compile_pass"],
            "runtime_elaboration_pass": hw["runtime_elaboration_pass"],
            "systemc_clang_pass": static.get("pass", False),
            "systemc_clang_targets": static.get("targets", []),
        },
        "structure_cross_check": {
            key: staged["structure_cross_check"][key]
            for key in (
                "pass",
                "uhdm_definition_count",
                "circt_module_count",
                "circt_instance_operation_count",
                "uhdm_definition_edge_count",
                "uhdm_elaborated_instance_count",
                "definition_edge_count_match",
                "circt_parameter_specializations",
                "only_uhdm",
            )
        },
        "behavior_lowering": {
            "comb": circt["stage_matrix"]["comb"],
            "seq": circt["stage_matrix"]["seq"],
            "llhd": circt["stage_matrix"]["llhd"],
            "native_systemc_complete": staged["native_circt_systemc_complete"],
            "first_full_conversion_failure": circt["conversion_failure"],
        },
        "function_refinement": {
            "top_down_complete": plan["top_down_complete"],
            "bottom_up_complete": plan["bottom_up_complete"],
            "depth_summary": plan["depth_summary"],
            "verified_end_to_end_function": plan["depth_summary"][0]["pass"],
        },
        "verilator_fallback": {
            "pass": staged["verilator"]["pass"],
            "models": [
                {"module": item["module"], "pass": item["pass"]} for item in models
            ],
        },
        "gates": {
            "structure_ready": bool(
                uhdm["pass"]
                and hw["systemc_skeleton_pass"]
                and staged["structure_cross_check"]["pass"]
            ),
            "function_refinement_ready": plan["top_down_complete"],
            "comb_seq_ready": staged["native_circt_systemc_complete"],
            "bottom_up_semantic_equivalence_ready": plan["bottom_up_complete"],
        },
        "claim_boundary": (
            "HW hierarchy generation, C++ compilation, elaboration and structural counts "
            "are verified. Comb/Seq native lowering and per-layer function semantic "
            "equivalence remain incomplete and are not inferred from syntax success."
        ),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
