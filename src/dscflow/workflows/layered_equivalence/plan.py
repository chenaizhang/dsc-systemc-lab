from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any


def build_layer_plan(contract: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    implementations = config.get("implementations", {})
    graph = contract.get("instance_graph", [])
    rows = []
    for item in graph:
        path = str(item["path"])
        depth = int(item.get("depth", path.count(".")))
        declared = implementations.get(path) or implementations.get(str(item["module"]))
        if declared:
            kind = str(declared.get("kind", "unknown"))
            implementation_status = str(declared.get("status", "unverified"))
            counts_as_function = bool(
                declared.get("counts_as_function_reference", "function" in kind)
            )
            status = (
                implementation_status if counts_as_function else "missing_function_reference"
            )
            evidence = list(declared.get("evidence", []))
        else:
            status = "missing"
            kind = "function_model"
            implementation_status = "missing"
            counts_as_function = False
            evidence = []
        rows.append(
            {
                "path": path,
                "parent_path": item.get("parent_path"),
                "module": item["module"],
                "depth": depth,
                "model_kind": kind,
                "status": status,
                "implementation_status": implementation_status,
                "counts_as_function_reference": counts_as_function,
                "evidence": evidence,
            }
        )
    depth_summary = []
    for depth in sorted({int(row["depth"]) for row in rows}):
        selected = [row for row in rows if row["depth"] == depth]
        counts = Counter(str(row["status"]) for row in selected)
        missing = counts["missing"] + counts["missing_function_reference"]
        depth_summary.append(
            {
                "depth": depth,
                "instance_count": len(selected),
                "verified": counts["verified"],
                "unverified": counts["unverified"],
                "missing": missing,
                "non_function_implementations": counts["missing_function_reference"],
                "pass": counts["unverified"] == 0 and missing == 0,
            }
        )
    semantic_pairs = config.get("semantic_pairs", [])
    return {
        "format": "dsc-layered-function-equivalence-plan",
        "version": "1.0.0",
        "top": contract["top"],
        "instance_count": len(rows),
        "instances": rows,
        "depth_summary": depth_summary,
        "semantic_pairs": semantic_pairs,
        "top_down_complete": all(item["pass"] for item in depth_summary),
        "bottom_up_complete": bool(semantic_pairs)
        and all(str(item.get("status")) == "verified" for item in semantic_pairs),
        "claim_boundary": (
            "A generated FunctionSlot is only an integration point.  A module becomes "
            "verified only after shared-stimulus comparison against its parent function "
            "or the corresponding CIRCT Comb/Seq implementation."
        ),
    }


def write_layer_plan(contract: dict[str, Any], config: dict[str, Any], output: Path) -> Path:
    plan = build_layer_plan(contract, config)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return output
