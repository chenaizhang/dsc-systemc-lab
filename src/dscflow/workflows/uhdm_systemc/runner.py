from __future__ import annotations

import argparse
import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from .contract import build_uhdm_structure_contract, read_json
from .prompt_pack import prepare_prompt_pack, resolve
from .structure_probe import run_structure_probe
from .systemc_clang import install_systemc_clang, run_systemc_clang


def load_config(path: Path) -> tuple[Path, dict[str, Any]]:
    path = path.resolve()
    config = read_json(path)
    if config.get("schema_version") != 1:
        raise ValueError("UHDM Agent SystemC config schema_version must be 1")
    return path.parent, config


def load_contract(
    case_root: Path, config: dict[str, Any], run_dir: Path
) -> dict[str, Any]:
    prepared = run_dir / "structure_contract.json"
    if prepared.is_file():
        contract = read_json(prepared)
    else:
        ir = read_json(resolve(case_root, config["uhdm"]["structure_ir"]))
        contract = build_uhdm_structure_contract(ir)
    expected = config["uhdm"].get("expected_structure_fingerprint")
    if expected and contract.get("structural_fingerprint") != expected:
        raise RuntimeError(
            "UHDM structure fingerprint changed: "
            f"{contract.get('structural_fingerprint')} != {expected}"
        )
    return contract


def verify(
    repo_root: Path,
    config_path: Path,
    run_dir: Path,
    candidate_dir: Path | None = None,
) -> dict[str, Any]:
    case_root, config = load_config(config_path)
    run_dir = run_dir.resolve()
    candidate = candidate_dir.resolve() if candidate_dir else run_dir / "candidate"
    contract = load_contract(case_root, config, run_dir)
    runtime = run_structure_probe(
        contract,
        candidate,
        run_dir / "verification" / "runtime_structure",
        config.get("runtime_probe", {}),
    )
    systemc_clang = run_systemc_clang(
        repo_root,
        contract,
        candidate,
        run_dir / "verification" / "systemc_clang",
        config.get("systemc_clang", {}),
    )
    report = {
        "format": "llm4eda-uhdm-agent-systemc-verification",
        "version": "1.0.0",
        "case": config.get("case"),
        "top": contract["top"],
        "candidate_dir": str(candidate),
        "structural_fingerprint": contract["structural_fingerprint"],
        "runtime_structure": runtime,
        "systemc_clang": systemc_clang,
        "pass": runtime.get("pass") is True and systemc_clang.get("pass") is True,
        "claim_boundary": (
            "UHDM/runtime/systemc-clang gates validate elaborated structure and static SystemC processes; "
            "functional equivalence still requires the shared-stimulus RTL/SystemC comparator."
        ),
    }
    output = run_dir / "verification" / "report.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return {**report, "report": str(output)}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    prepare = sub.add_parser(
        "prepare", help="create UHDM contract and per-module agent prompts"
    )
    prepare.add_argument("--config", type=Path, required=True)
    prepare.add_argument("--output-dir", type=Path, required=True)
    prepare.add_argument("--rtl-root", type=Path)
    check = sub.add_parser("verify", help="run runtime hierarchy and systemc-clang gates")
    check.add_argument("--config", type=Path, required=True)
    check.add_argument("--run-dir", type=Path, required=True)
    check.add_argument("--candidate-dir", type=Path)
    install = sub.add_parser(
        "systemc-clang-install", help="install the pinned official SCCL container"
    )
    install.add_argument("--repo-root", type=Path, default=Path("."))
    graph = sub.add_parser("systemc-clang", help="analyze SystemC hierarchy and processes")
    graph.add_argument("--config", type=Path, required=True)
    graph.add_argument("--run-dir", type=Path, required=True)
    graph.add_argument("--candidate-dir", type=Path, required=True)
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    repo_root = Path.cwd().resolve()
    if args.command == "prepare":
        result = prepare_prompt_pack(
            args.config, args.output_dir.resolve(), args.rtl_root
        )
    elif args.command == "verify":
        result = verify(repo_root, args.config, args.run_dir, args.candidate_dir)
    elif args.command == "systemc-clang-install":
        result = install_systemc_clang(args.repo_root.resolve())
    elif args.command == "systemc-clang":
        case_root, config = load_config(args.config)
        contract = load_contract(case_root, config, args.run_dir.resolve())
        result = run_systemc_clang(
            repo_root,
            contract,
            args.candidate_dir.resolve(),
            args.run_dir.resolve() / "verification" / "systemc_clang",
            config.get("systemc_clang", {}),
        )
    else:
        raise AssertionError(args.command)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("pass", result.get("status") == "ready") else 1


if __name__ == "__main__":
    raise SystemExit(main())
