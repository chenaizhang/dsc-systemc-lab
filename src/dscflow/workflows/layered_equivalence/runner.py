from __future__ import annotations

import argparse
import json
from collections.abc import Iterable
from pathlib import Path

from ..uhdm_systemc.contract import build_uhdm_structure_contract, read_json
from .plan import build_layer_plan
from .systemc_skeleton import write_uhdm_systemc_skeleton
from .trace import compare_traces


def prepare(config_path: Path, output_dir: Path) -> dict:
    config_path = config_path.resolve()
    root = config_path.parent
    config = read_json(config_path)
    structure = read_json((root / config["uhdm"]["structure_ir"]).resolve())
    hierarchy = read_json((root / config["uhdm"]["hierarchy_json"]).resolve())
    contract = build_uhdm_structure_contract(structure, hierarchy)
    expected_instances = int(config["uhdm"].get("expected_instance_count", 0))
    expected_bindings = int(config["uhdm"].get("expected_binding_count", 0))
    gates = {
        "instance_count": not expected_instances or contract["instance_count"] == expected_instances,
        "named_binding_count": not expected_bindings or contract["binding_count"] == expected_bindings,
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    contract_path = output_dir / "structure_contract.json"
    contract_path.write_text(json.dumps(contract, ensure_ascii=False, indent=2) + "\n")
    skeleton = write_uhdm_systemc_skeleton(contract, output_dir / "candidate" / "dsc_cycle_model.hpp")
    plan = build_layer_plan(contract, config)
    plan_path = output_dir / "layered_equivalence_plan.json"
    plan_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n")
    result = {
        "pass": all(gates.values()),
        "gates": gates,
        "instance_count": contract["instance_count"],
        "named_binding_count": contract["binding_count"],
        "structure_contract": str(contract_path),
        "uhdm_systemc_reference": str(skeleton),
        "layered_equivalence_plan": str(plan_path),
        "top_down_complete": plan["top_down_complete"],
        "bottom_up_complete": plan["bottom_up_complete"],
    }
    (output_dir / "prepare_report.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    create = sub.add_parser("prepare")
    create.add_argument("--config", type=Path, required=True)
    create.add_argument("--output-dir", type=Path, required=True)
    compare = sub.add_parser("compare-traces")
    compare.add_argument("--reference", type=Path, required=True)
    compare.add_argument("--candidate", type=Path, required=True)
    compare.add_argument("--key", action="append", required=True)
    compare.add_argument("--ignore", action="append", default=[])
    compare.add_argument("--output", type=Path)
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    if args.command == "prepare":
        result = prepare(args.config, args.output_dir.resolve())
    else:
        result = compare_traces(args.reference, args.candidate, args.key, args.ignore)
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

