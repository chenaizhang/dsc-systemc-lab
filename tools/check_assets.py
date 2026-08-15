#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from dscflow.workflows.uhdm_systemc.contract import build_uhdm_structure_contract  # noqa: E402


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"JSON 根节点不是对象：{path}")
    return value


def main() -> int:
    errors: list[str] = []
    checks: list[dict[str, Any]] = []

    agent_config = load(ROOT / "configs" / "uhdm_agent.json")
    source_root = (ROOT / "configs" / agent_config["behavior"]["source_root"]).resolve()
    for item in agent_config["behavior"]["sources"]:
        path = source_root / item["path"]
        actual = digest(path) if path.is_file() else None
        passed = actual == item["sha256"]
        checks.append(
            {
                "kind": "rtl_behavior_source",
                "module": item["module"],
                "path": str(path.relative_to(ROOT)) if path.is_file() else str(path),
                "expected_sha256": item["sha256"],
                "actual_sha256": actual,
                "pass": passed,
            }
        )
        if not passed:
            errors.append(f"RTL 缺失或 SHA 不符：{item['module']} -> {path}")

    structure_path = (ROOT / "configs" / agent_config["uhdm"]["structure_ir"]).resolve()
    if structure_path.is_file():
        contract = build_uhdm_structure_contract(load(structure_path))
        actual_fingerprint = contract["structural_fingerprint"]
    else:
        actual_fingerprint = None
    expected_fingerprint = agent_config["uhdm"]["expected_structure_fingerprint"]
    structure_passed = actual_fingerprint == expected_fingerprint
    checks.append(
        {
            "kind": "uhdm_structure_contract",
            "path": str(structure_path),
            "expected_fingerprint": expected_fingerprint,
            "actual_fingerprint": actual_fingerprint,
            "pass": structure_passed,
        }
    )
    if not structure_passed:
        errors.append("UHDM 结构指纹不一致")

    staged = load(ROOT / "configs" / "staged_circt.json")
    hierarchy = ROOT / staged["inputs"]["default_root"] / staged["inputs"]["hierarchy_json"]
    hierarchy_actual = digest(hierarchy) if hierarchy.is_file() else None
    hierarchy_expected = staged["expected"]["hierarchy_sha256"]
    hierarchy_passed = hierarchy_actual == hierarchy_expected
    checks.append(
        {
            "kind": "uhdm_hierarchy_summary",
            "path": str(hierarchy),
            "expected_sha256": hierarchy_expected,
            "actual_sha256": hierarchy_actual,
            "pass": hierarchy_passed,
        }
    )
    if not hierarchy_passed:
        errors.append("UHDM hierarchy summary 缺失或 SHA 不一致")

    archive = ROOT / "third_party" / "vesa-dsc-model-20211213" / "DSC_model_20211213.zip"
    vesa_expected = "f2339edb1d5603d2f3ca5fbb6ca089b18ff73c43088352fa7c3b59df03e3ee2c"
    vesa_actual = digest(archive) if archive.is_file() else None
    vesa_passed = vesa_actual == vesa_expected
    checks.append(
        {
            "kind": "vesa_reference_archive",
            "path": str(archive),
            "expected_sha256": vesa_expected,
            "actual_sha256": vesa_actual,
            "pass": vesa_passed,
        }
    )
    if not vesa_passed:
        errors.append("VESA reference model 缺失或 SHA 不一致；可运行下载脚本恢复")

    report = {
        "format": "dscflow-asset-check-v1",
        "root": str(ROOT),
        "checks": checks,
        "errors": errors,
        "pass": not errors,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
