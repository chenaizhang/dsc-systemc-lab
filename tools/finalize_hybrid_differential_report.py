#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import platform
import subprocess
from itertools import pairwise
from pathlib import Path
from typing import Any


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def first_difference(left: bytes, right: bytes) -> dict[str, Any] | None:
    for index, (left_byte, right_byte) in enumerate(zip(left, right)):
        if left_byte != right_byte:
            return {"byte": index, "reference": left_byte, "candidate": right_byte}
    if len(left) != len(right):
        return {
            "byte": min(len(left), len(right)),
            "reference": left[min(len(left), len(right))] if len(left) > len(right) else None,
            "candidate": right[min(len(left), len(right))] if len(right) > len(left) else None,
            "reason": "length_mismatch",
        }
    return None


def version(command: list[str]) -> str:
    completed = subprocess.run(command, text=True, capture_output=True, check=False)
    text = completed.stdout.strip() or completed.stderr.strip()
    return text.splitlines()[0] if text else "unavailable"


def stream_diagnostics(payload: bytes, word_bytes: int = 24) -> dict[str, Any]:
    words = [payload[index : index + word_bytes] for index in range(0, len(payload), word_bytes)]
    return {
        "word_bytes": word_bytes,
        "words": len(words),
        "adjacent_duplicate_words": sum(
            left == right for left, right in pairwise(words)
        ),
        "paired_duplicate_words": sum(
            words[index] == words[index + 1] for index in range(0, len(words) - 1, 2)
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--golden-report", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()

    runtime = json.loads(args.runtime.read_text(encoding="utf-8"))
    golden_report = json.loads(args.golden_report.read_text(encoding="utf-8"))
    paths = {
        name: args.output_dir / filename
        for name, filename in {
            "golden": "golden_payload.bin",
            "rtl_monolithic": "rtl_monolithic.bin",
            "rtl_split": "rtl_split.bin",
            "hybrid_cycle_apb": "hybrid_cycle_apb.bin",
        }.items()
    }
    payloads = {name: path.read_bytes() for name, path in paths.items()}
    comparisons = {
        "rtl_vs_golden": first_difference(payloads["golden"], payloads["rtl_monolithic"]),
        "split_vs_rtl": first_difference(payloads["rtl_monolithic"], payloads["rtl_split"]),
        "hybrid_vs_split": first_difference(
            payloads["rtl_split"], payloads["hybrid_cycle_apb"]
        ),
    }
    structural_differential_pass = (
        comparisons["split_vs_rtl"] is None
        and runtime["cycle_first_difference"]["split_vs_rtl"] is None
    )
    replacement_differential_pass = (
        comparisons["hybrid_vs_split"] is None
        and runtime["cycle_first_difference"]["hybrid_vs_split"] is None
    )
    workflow_completed = structural_differential_pass and replacement_differential_pass
    rtl_matches_golden = comparisons["rtl_vs_golden"] is None
    if not workflow_completed:
        status = "failed_hybrid_or_structural_differential"
    elif rtl_matches_golden:
        status = "completed_rtl_matches_vesa_vector"
    else:
        status = "completed_rtl_function_mismatch_localized"

    report = {
        "format": "dsc-hybrid-differential-verification-v1",
        "version": "1.0.0",
        "status": status,
        "host": {"architecture": platform.machine(), "node": platform.node()},
        "tools": {
            "verilator": version(["verilator", "--version"]),
            "systemc": version(["pkg-config", "--modversion", "systemc"]),
            "cxx": version(["c++", "--version"]),
        },
        "source_function_model": {
            "pass": bool(golden_report.get("pass")),
            "report": str(args.golden_report),
            "case": golden_report.get("case"),
        },
        "stimulus": {
            "kind": "shared_ppm_pps_apb_axi_stream",
            "input_width": runtime["input"]["width"],
            "input_height": runtime["input"]["height"],
            "input_sha256": golden_report.get("case", {}).get("input_sha256"),
            "pps_source": "bytes 4..131 of VESA DSCF output",
        },
        "models": {
            "rtl_monolithic": "Vdsc_encoder generated with Verilator --sc",
            "rtl_split": [
                "Vdsce_apb",
                "Vdsce_command",
                "Vdsce_engine",
                "Vdsce_interrupt",
                "Vdsce_pps",
                "Vdsce_reset",
                "Vdsce_timers",
            ],
            "hybrid_cycle_apb": {
                "systemc": ["CycleApb"],
                "verilator_blackboxes": [
                    "Vdsce_command",
                    "Vdsce_engine",
                    "Vdsce_interrupt",
                    "Vdsce_pps",
                    "Vdsce_reset",
                    "Vdsce_timers",
                ],
            },
        },
        "rtl_support_shims": {
            "reason": "delivered dsc_support_primitives.sv contains declarations without behavior",
            "substituted_modules": [
                "gprim_sync_stage",
                "gprim_sync2_stage",
                "gram_bist_1r1w",
            ],
            "source": "models/cycle_systemc/rtl_shims/dsc_support_primitives.sv",
            "boundary": "functional simulation semantics; proprietary BIST behavior is not modeled",
        },
        "runtime": runtime,
        "module_interface_trace": runtime.get("module_interface_trace"),
        "outputs": {
            name: {
                "bytes": len(payloads[name]),
                "sha256": digest(paths[name]),
                "path": str(paths[name]),
            }
            for name in paths
        },
        "comparisons": comparisons,
        "diagnostics": {
            "golden": stream_diagnostics(payloads["golden"]),
            "rtl_monolithic": stream_diagnostics(payloads["rtl_monolithic"]),
            "rtl_first_word_matches_golden": (
                payloads["rtl_monolithic"][:24] == payloads["golden"][:24]
            ),
            "rtl_output_byte_delta": len(payloads["rtl_monolithic"])
            - len(payloads["golden"]),
            "classification": (
                "byte_exact"
                if rtl_matches_golden
                else "shared RTL behavior differs from independent VESA function model"
            ),
            "first_suspect_boundary": (
                None
                if rtl_matches_golden
                else {
                    "module": "dsce_engine shared RTL output path",
                    "evidence": (
                        f"{runtime.get('output_sidebands', {}).get('line_markers', 0)} "
                        "output line markers observed before drain timeout"
                    ),
                    "inference": True,
                }
            ),
        },
        "gates": {
            "software_function_byte_exact": bool(golden_report.get("pass")),
            "monolithic_rtl_ran": len(payloads["rtl_monolithic"]) > 0,
            "split_module_network_cycle_exact": structural_differential_pass,
            "cycle_apb_replacement_cycle_exact": replacement_differential_pass,
            "rtl_matches_vesa_golden": rtl_matches_golden,
            "workflow_completed": workflow_completed,
        },
        "claim_boundary": (
            "The report proves only this shared vector and configuration. Verilator preserves RTL "
            "bugs. CycleApb is the only non-Verilator cycle module in the hybrid run; remaining "
            "modules are explicit Verilator-SystemC black boxes."
        ),
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": status, "gates": report["gates"]}, ensure_ascii=False, indent=2))
    return 0 if workflow_completed and golden_report.get("pass") else 1


if __name__ == "__main__":
    raise SystemExit(main())
