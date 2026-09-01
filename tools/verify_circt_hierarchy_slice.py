#!/usr/bin/env python3
"""Verify a CIRCT hierarchy slice against its manifest and optional UHDM JSON."""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path

MODULE_RE = re.compile(r"^\s*hw\.module(?:\.extern)?(?:\s+private)?\s+@([^\s(]+)")
INSTANCE_RE = re.compile(r'hw\.instance\s+"([^"]+)"\s+@([^\s(]+)')
SC_MODULE_RE = re.compile(r"\bSC_MODULE\s*\(\s*([A-Za-z_][A-Za-z0-9_]*)\s*\)")
SC_STRUCT_RE = re.compile(
    r"\bstruct\s+([A-Za-z_][A-Za-z0-9_]*)\s*:\s*(?:sc_core::)?sc_module\b"
)


def normalize_uhdm_name(name: str) -> str:
    return name.rsplit("@", 1)[-1]


def parse_hw_slice(path: Path) -> tuple[set[str], list[tuple[str, str, str]]]:
    modules: set[str] = set()
    edges: list[tuple[str, str, str]] = []
    current: str | None = None
    brace_depth = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        module = MODULE_RE.match(line)
        if module:
            current = module.group(1)
            modules.add(current)
            brace_depth = line.count("{") - line.count("}")
            if ".extern" in line or brace_depth == 0:
                current = None
            continue
        if current:
            for instance, target in INSTANCE_RE.findall(line):
                edges.append((current, instance, target))
            brace_depth += line.count("{") - line.count("}")
            if brace_depth <= 0:
                current = None
    return modules, edges


def parse_systemc_modules(path: Path) -> set[str]:
    text = path.read_text(encoding="utf-8")
    return set(SC_MODULE_RE.findall(text)) | set(SC_STRUCT_RE.findall(text))


def uhdm_direct_children(path: Path, top: str) -> Counter[tuple[str, str]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    results: Counter[tuple[str, str]] = Counter()
    for design in payload.get("designs", []):
        for root in design.get("top_modules", []):
            if normalize_uhdm_name(root.get("definition_name", "")) != top:
                continue
            for child in root.get("children", root.get("instances", [])):
                results[
                    (
                        child.get("instance_name", ""),
                        normalize_uhdm_name(child.get("definition_name", "")),
                    )
                ] += 1
    return results


def normalize_circt_specialization(target: str, references: set[str]) -> str:
    if target in references:
        return target
    matches = [name for name in references if target.startswith(name + "_")]
    return max(matches, key=len) if matches else target


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--hw-mlir", type=Path, required=True)
    parser.add_argument("--systemc", type=Path, required=True)
    parser.add_argument("--uhdm-json", type=Path)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()

    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    retained = set(manifest["retained_modules"])
    frontier = set(manifest["frontier_modules"])
    hw_modules, hw_edges = parse_hw_slice(args.hw_mlir)
    systemc_modules = parse_systemc_modules(args.systemc)
    retained_edges = Counter(
        (edge["parent"], edge["instance"], edge["target"])
        for edge in manifest["instances"]
        if edge["retained"]
    )
    actual_edges = Counter(hw_edges)

    checks = {
        "manifest_schema": manifest.get("schema") == "circt.hw.hierarchy-slice.v1",
        "hw_module_set": hw_modules == retained,
        "hw_instance_edges": actual_edges == retained_edges,
        "systemc_module_set": systemc_modules == retained,
        "frontier_is_retained": frontier <= retained,
        "frontier_has_no_retained_children": not any(
            parent in frontier for parent, _, _ in actual_edges
        ),
    }

    uhdm_result: dict[str, object] | None = None
    if args.uhdm_json:
        reference_direct = uhdm_direct_children(args.uhdm_json, manifest["top"])
        reference_targets = {target for _, target in reference_direct}
        circt_direct = Counter(
            (instance, normalize_circt_specialization(target, reference_targets))
            for parent, instance, target in actual_edges
            if parent == manifest["top"]
        )
        # CIRCT parameter specialization appends a suffix to the source module
        # name. Normalize only when the prefix names an actual UHDM child; all
        # other mismatches remain visible and fail the gate.
        checks["uhdm_top_direct_children"] = circt_direct == reference_direct
        uhdm_result = {
            "circt": sorted([list(item) + [count] for item, count in circt_direct.items()]),
            "reference": sorted(
                [list(item) + [count] for item, count in reference_direct.items()]
            ),
        }

    report = {
        "status": "pass" if all(checks.values()) else "fail",
        "top": manifest["top"],
        "max_depth": manifest["max_depth"],
        "checks": checks,
        "counts": {
            "retained_modules": len(retained),
            "frontier_modules": len(frontier),
            "retained_instances": sum(actual_edges.values()),
        },
        "uhdm_top_direct_children": uhdm_result,
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
