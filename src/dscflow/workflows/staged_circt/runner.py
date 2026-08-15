from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections.abc import Iterable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .evidence import analyze_inputs, clean_definition
from .mlir import analyze_core_ir, build_agent_context, classify_circt_failure
from .utils import (
    blocked_stage,
    read_json,
    resolve_tool,
    run_command,
    tool_record,
    write_json,
)


def load_config(path: Path) -> dict[str, Any]:
    config = read_json(path)
    if config.get("schema_version") != 1:
        raise ValueError(f"不支持的 staged CIRCT 配置版本: {config.get('schema_version')}")
    for key in ("case", "top", "inputs", "frontend", "circt", "verilator"):
        if key not in config:
            raise ValueError(f"配置缺少字段: {key}")
    config["_config_path"] = str(path.resolve())
    return config


def resolve_input_root(
    repo_root: Path, config: dict[str, Any], explicit: Path | None
) -> Path:
    candidates: list[Path] = []
    if explicit:
        candidates.append(explicit.expanduser())
    input_config = config["inputs"]
    if (environment_name := input_config.get("root_env")) and (
        value := os.environ.get(str(environment_name))
    ):
        candidates.append(Path(value).expanduser())
    if default := input_config.get("default_root"):
        candidates.append(repo_root / str(default))
    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved.is_dir():
            return resolved
    raise FileNotFoundError(
        "verilog_dsc 输入目录不存在；请传 --input-root 或设置 "
        + str(input_config.get("root_env", "VERILOG_DSC_ROOT"))
    )


def _skill_preflight(repo_root: Path, config: dict[str, Any]) -> dict[str, Any]:
    skills = config.get("skills", {})
    required = [str(item) for item in skills.get("required", [])]
    source_repository = (skills.get("source") or {}).get("repository")
    codex_root = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
    roots = [
        codex_root / "skills",
        codex_root / "vendor" / "eda-sandbox" / "skills",
        repo_root / "integrations" / "eda_sandbox" / "skills",
    ]
    results = []
    for name in required:
        locations = [root / name / "SKILL.md" for root in roots]
        found = next((path for path in locations if path.is_file()), None)
        results.append(
            {
                "name": name,
                "available": found is not None,
                "path": str(found.resolve()) if found else None,
            }
        )
    return {
        "required": required,
        "source_repository": source_repository,
        "check_policy": skills.get("check_policy"),
        "skills": results,
        "pass": all(item["available"] for item in results),
        "install_command": (
            None
            if all(item["available"] for item in results) or not source_repository
            else f"git clone --branch dev {source_repository} ~/.codex/vendor/eda-sandbox"
        ),
    }


def _tool_environment(library_path: str | None) -> dict[str, str]:
    environment = os.environ.copy()
    if library_path:
        previous = environment.get("LD_LIBRARY_PATH")
        environment["LD_LIBRARY_PATH"] = library_path + (":" + previous if previous else "")
    return environment


def _resolve_tools(args: argparse.Namespace) -> tuple[dict[str, Path | None], dict[str, str]]:
    root = args.circt_root.expanduser().resolve() if args.circt_root else None

    def circt(name: str, explicit: str | None) -> Path | None:
        if explicit:
            return resolve_tool(name, explicit)
        if root:
            return resolve_tool(name, str(root / "bin" / name))
        return resolve_tool(name)

    tools = {
        "circt_verilog": circt("circt-verilog", args.circt_verilog),
        "circt_opt": circt("circt-opt", args.circt_opt),
        "circt_translate": circt("circt-translate", args.circt_translate),
        "verilator": resolve_tool("verilator", args.verilator),
        "make": resolve_tool("make", args.make),
        "cxx": resolve_tool("c++", args.cxx),
        "pkg_config": resolve_tool("pkg-config", args.pkg_config),
    }
    return tools, _tool_environment(args.circt_library_path)


def _source_arguments(root: Path, sources: list[str]) -> list[str]:
    return [str((root / item).resolve()) for item in sources]


def _frontend_argv(
    tool: Path,
    root: Path,
    config: dict[str, Any],
    sources: list[str],
    output: Path,
) -> list[str]:
    frontend = config["frontend"]
    argv = [str(tool), "--single-unit"]
    for directory in frontend.get("include_dirs", ["."]):
        argv.extend(["-I", str((root / str(directory)).resolve())])
    if timescale := frontend.get("timescale"):
        argv.append(f"--timescale={timescale}")
    if frontend.get("sroa"):
        argv.append("--sroa")
    argv.extend(
        [
            "--top",
            str(config["top"]),
            "--ir-hw",
            "--mlir-print-debuginfo",
            *_source_arguments(root, sources),
            "-o",
            str(output),
        ]
    )
    return argv


def _stderr(report: dict[str, Any]) -> str:
    path = report.get("stderr_log")
    return Path(path).read_text(encoding="utf-8", errors="replace") if path else ""


def _circt_flow(
    root: Path,
    config: dict[str, Any],
    evidence: dict[str, Any],
    tools: dict[str, Path | None],
    environment: dict[str, str],
    run_dir: Path,
) -> tuple[dict[str, Any], dict[str, Any] | None, list[dict[str, Any]]]:
    stage_dir = run_dir / "02_circt"
    timeout = int(config["circt"].get("timeout_seconds", 300))
    source_plan = evidence["source_plan"]
    circt_verilog = tools["circt_verilog"]
    circt_opt = tools["circt_opt"]
    circt_translate = tools["circt_translate"]
    failures: list[dict[str, Any]] = []
    if circt_verilog is None or circt_opt is None or circt_translate is None:
        missing = [
            name
            for name in ("circt_verilog", "circt_opt", "circt_translate")
            if tools[name] is None
        ]
        return (
            {
                "pass": False,
                "status": "blocked_missing_circt_tools",
                "missing_tools": missing,
                "stages": {},
            },
            None,
            failures,
        )

    full_ir = stage_dir / "all_sources.hw.mlir"
    all_frontend = run_command(
        "01_frontend_all_sources",
        _frontend_argv(
            circt_verilog,
            root,
            config,
            list(source_plan["all_sources"]),
            full_ir,
        ),
        cwd=root,
        output_dir=stage_dir,
        timeout=timeout,
        artifact=full_ir,
        env=environment,
    )
    all_failure = None if all_frontend["pass"] else classify_circt_failure(
        _stderr(all_frontend), "frontend_all_sources"
    )
    if all_failure:
        failures.append(all_failure)

    core_ir = stage_dir / f"{config['top']}.core.mlir"
    reachable_frontend = run_command(
        "02_frontend_reachable_design",
        _frontend_argv(
            circt_verilog,
            root,
            config,
            list(source_plan["reachable_sources"]),
            core_ir,
        ),
        cwd=root,
        output_dir=stage_dir,
        timeout=timeout,
        artifact=core_ir,
        env=environment,
    )
    if not reachable_frontend["pass"]:
        failure = classify_circt_failure(
            _stderr(reachable_frontend), "frontend_reachable_design"
        )
        if failure:
            failures.append(failure)
        return (
            {
                "pass": False,
                "status": "failed_at_frontend_reachable_design",
                "stages": {
                    "frontend_all_sources": all_frontend,
                    "frontend_reachable_design": reachable_frontend,
                },
                "all_sources_failure": all_failure,
            },
            None,
            failures,
        )

    inventory = analyze_core_ir(
        core_ir.read_text(encoding="utf-8", errors="replace"), str(config["top"])
    )
    write_json(stage_dir / "core_ir_inventory.json", inventory)

    normalized = stage_dir / f"{config['top']}.normalized.mlir"
    normalization = run_command(
        "03_canonicalize_symbol_dce",
        [
            str(circt_opt),
            "--canonicalize",
            "--symbol-dce",
            str(core_ir),
            "-o",
            str(normalized),
        ],
        cwd=root,
        output_dir=stage_dir,
        timeout=timeout,
        artifact=normalized,
        env=environment,
    )
    conversion_input = normalized if normalization["pass"] else core_ir
    systemc_ir = stage_dir / f"{config['top']}.systemc.mlir"
    conversion = run_command(
        "04_hw_to_systemc",
        [
            str(circt_opt),
            "--convert-hw-to-systemc",
            str(conversion_input),
            "-o",
            str(systemc_ir),
        ],
        cwd=root,
        output_dir=stage_dir,
        timeout=timeout,
        artifact=systemc_ir,
        env=environment,
    )
    conversion_failure = None if conversion["pass"] else classify_circt_failure(
        _stderr(conversion), "hw_to_systemc"
    )
    if conversion_failure:
        failures.append(conversion_failure)

    if conversion["pass"]:
        systemc_cpp = stage_dir / f"{config['top']}.systemc.cpp"
        emission = run_command(
            "05_export_systemc",
            [
                str(circt_translate),
                "--export-systemc",
                str(systemc_ir),
                "-o",
                str(systemc_cpp),
            ],
            cwd=root,
            output_dir=stage_dir,
            timeout=timeout,
            artifact=systemc_cpp,
            env=environment,
        )
        emission_failure = None if emission["pass"] else classify_circt_failure(
            _stderr(emission), "systemc_emission"
        )
        if emission_failure:
            failures.append(emission_failure)
    else:
        systemc_cpp = None
        emission = blocked_stage("05_export_systemc", "04_hw_to_systemc")
        emission_failure = None

    all_source_known_failure = (
        not all_frontend["pass"]
        and all_failure is not None
        and all_failure.get("kind") == "frontend_undeclared_identifier"
        and source_plan["all_exclusions_proven"]
    )
    partitions = inventory["stage_partitions"]
    stage_matrix = {
        "frontend": {
            "all_sources_pass": all_frontend["pass"],
            "all_sources_known_uninstantiated_failure": all_source_known_failure,
            "reachable_design_pass": reachable_frontend["pass"],
        },
        "hw": {
            "core_ir_available": True,
            "module_count": inventory["module_count"],
            "instance_operation_count": inventory["instance_operation_count"],
            "systemc_module_conversion_pass": conversion["pass"],
        },
        "comb": {
            "ssa_extracted": inventory["dialect_totals"]["comb"] > 0,
            "operation_count": inventory["dialect_totals"]["comb"],
            "module_count": len(partitions["comb_modules"]),
            "native_completion": conversion["pass"] and emission["pass"],
            "blocked_by": None if conversion["pass"] else "04_hw_to_systemc",
        },
        "seq": {
            "ssa_extracted": inventory["dialect_totals"]["seq"] > 0,
            "operation_count": inventory["dialect_totals"]["seq"],
            "module_count": len(partitions["seq_modules"]),
            "native_completion": conversion["pass"] and emission["pass"],
            "blocked_by": None if conversion["pass"] else "04_hw_to_systemc",
        },
        "llhd": {
            "ssa_extracted": inventory["dialect_totals"]["llhd"] > 0,
            "operation_count": inventory["dialect_totals"]["llhd"],
            "module_count": len(partitions["llhd_modules"]),
            "first_failure_operation": (
                conversion_failure.get("operation") if conversion_failure else None
            ),
        },
        "emission": {"pass": emission["pass"], "failure": emission_failure},
    }
    report = {
        "pass": reachable_frontend["pass"],
        "native_systemc_complete": conversion["pass"] and emission["pass"],
        "status": (
            "native_systemc_complete"
            if conversion["pass"] and emission["pass"]
            else "core_ir_ready_native_systemc_incomplete"
        ),
        "all_sources_failure": all_failure,
        "conversion_failure": conversion_failure,
        "stages": {
            "frontend_all_sources": all_frontend,
            "frontend_reachable_design": reachable_frontend,
            "canonicalize_symbol_dce": normalization,
            "hw_to_systemc": conversion,
            "export_systemc": emission,
        },
        "stage_matrix": stage_matrix,
        "artifacts": {
            "core_ir": str(core_ir.resolve()),
            "inventory": str((stage_dir / "core_ir_inventory.json").resolve()),
            "systemc_ir": str(systemc_ir.resolve()) if conversion["pass"] else None,
            "systemc_cpp": str(systemc_cpp.resolve()) if systemc_cpp else None,
        },
    }
    write_json(stage_dir / "report.json", report)
    return report, inventory, failures


def _verilator_port_names(header: Path) -> list[str]:
    if not header.is_file():
        return []
    text = header.read_text(encoding="utf-8", errors="replace")
    return sorted(
        set(
            re.findall(
                r"\b(?:sc_core::)?sc_(?:in|out|inout)\s*<[^;\n]+>\s*"
                r"(?:\(\s*&\s*|&?\s*)([A-Za-z_$][A-Za-z0-9_$]*)"
                r"(?:\s*\)\s*\[[^\]]+\])?\s*;",
                text,
            )
        )
    )


def _run_verilator(
    root: Path,
    config: dict[str, Any],
    evidence: dict[str, Any],
    inventory: dict[str, Any] | None,
    tools: dict[str, Path | None],
    run_dir: Path,
) -> dict[str, Any]:
    verilator = tools["verilator"]
    make = tools["make"]
    if verilator is None or make is None:
        return {
            "pass": False,
            "status": "blocked_missing_verilator_or_make",
            "models": [],
        }
    timeout = int(config["verilator"].get("timeout_seconds", 900))
    jobs = int(config["verilator"].get("build_jobs", 2))
    sources = _source_arguments(root, evidence["source_plan"]["reachable_sources"])
    models: list[dict[str, Any]] = []
    inventory_by_name = {
        item["name"]: item for item in (inventory or {}).get("modules", [])
    }
    for target in config["verilator"].get("blackbox_tops", [config["top"]]):
        target = str(target)
        target_dir = run_dir / "03_verilator" / target
        object_dir = target_dir / "obj_dir"
        prefix = "V" + re.sub(r"[^A-Za-z0-9_]", "_", target)
        header = object_dir / f"{prefix}.h"
        library = object_dir / f"{prefix}__ALL.a"
        generate = run_command(
            "01_generate_systemc",
            [
                str(verilator),
                "--cc",
                "--sc",
                "--timing",
                "--trace",
                "-Wno-fatal",
                "--top-module",
                target,
                "--prefix",
                prefix,
                "--Mdir",
                str(object_dir),
                *sources,
            ],
            cwd=root,
            output_dir=target_dir,
            timeout=timeout,
            artifact=header,
        )
        if generate["pass"]:
            build = run_command(
                "02_build_model_library",
                [
                    str(make),
                    "-C",
                    str(object_dir),
                    "-f",
                    f"{prefix}.mk",
                    f"-j{jobs}",
                    f"{prefix}__ALL.a",
                ],
                cwd=root,
                output_dir=target_dir,
                timeout=timeout,
                artifact=library,
            )
        else:
            build = blocked_stage("02_build_model_library", "01_generate_systemc")
        circt_ports = sorted(
            port["name"] for port in inventory_by_name.get(target, {}).get("ports", [])
        )
        verilator_ports = _verilator_port_names(header)
        models.append(
            {
                "module": target,
                "model_class": prefix,
                "header": str(header.resolve()) if header.is_file() else None,
                "library": str(library.resolve()) if library.is_file() else None,
                "generate": generate,
                "build": build,
                "pass": generate["pass"] and build["pass"],
                "port_comparison": {
                    "circt_ports": circt_ports,
                    "verilator_ports": verilator_ports,
                    "only_circt": sorted(set(circt_ports) - set(verilator_ports)),
                    "only_verilator": sorted(set(verilator_ports) - set(circt_ports)),
                    "pass": bool(circt_ports) and set(circt_ports) == set(verilator_ports),
                },
            }
        )
    report = {
        "format": "llm4eda-verilator-systemc-blackbox-matrix-v1",
        "models": models,
        "pass": bool(models) and all(item["pass"] for item in models),
        "top_model_pass": any(
            item["module"] == config["top"] and item["pass"] for item in models
        ),
        "functional_equivalence": "not_run_no_shared_stimulus_in_bundle",
        "claim": "compiled cycle-accurate RTL C++/SystemC models; functional correctness is not implied",
    }
    write_json(run_dir / "03_verilator" / "report.json", report)
    return report


def _cross_check(
    config: dict[str, Any], evidence: dict[str, Any], inventory: dict[str, Any] | None
) -> dict[str, Any]:
    if inventory is None:
        return {"pass": False, "status": "blocked_without_circt_inventory"}
    uhdm_definitions = {
        clean_definition(item) for item in evidence["hierarchy"]["definitions"]
    }
    circt_modules = set(inventory["module_names"])
    exact_common = sorted(uhdm_definitions & circt_modules)
    specialized = sorted(
        name
        for name in circt_modules - uhdm_definitions
        if any(name.startswith(base + "_") for base in uhdm_definitions)
    )
    return {
        "format": "llm4eda-uhdm-circt-structure-cross-check-v1",
        "top": config["top"],
        "top_in_circt": config["top"] in circt_modules,
        "uhdm_definition_count": len(uhdm_definitions),
        "circt_module_count": len(circt_modules),
        "exact_common_definitions": exact_common,
        "circt_parameter_specializations": specialized,
        "only_uhdm": sorted(uhdm_definitions - circt_modules),
        "only_circt_non_specialized": sorted(
            (circt_modules - uhdm_definitions) - set(specialized)
        ),
        "provided_uhdm_hierarchy_complete": evidence["hierarchy_completeness"]["pass"],
        "circt_instance_operation_count": inventory["instance_operation_count"],
        "provided_uhdm_invocation_count": evidence["hierarchy"]["invocation_count"],
        "pass": config["top"] in circt_modules and bool(exact_common),
        "canonical_equivalence_proven": False,
        "limitation": "provided UHDM JSON omits generate-scope instances, so exact hierarchy equality is intentionally blocked",
    }


def _hybrid_plan(
    config: dict[str, Any], circt: dict[str, Any], verilator: dict[str, Any]
) -> dict[str, Any]:
    usable = [item["module"] for item in verilator.get("models", []) if item["pass"]]
    return {
        "format": "llm4eda-systemc-verilator-hybrid-plan-v1",
        "native_circt_systemc_complete": bool(circt.get("native_systemc_complete")),
        "verilator_blackboxes": usable,
        "full_rtl_fallback": config["top"] in usable,
        "partial_replacement_candidates": [
            item for item in usable if item != config["top"]
        ],
        "circt_interop_operation": "systemc.interop.verilated",
        "replacement_order": list(config["verilator"].get("replacement_order", [])),
        "required_next_gate": "shared image/config stimulus differential against functional SystemC/VESA reference",
        "functional_comparison_executed": False,
        "claim_boundary": "this plan proves buildable black boxes and structural insertion points, not image-output equivalence",
    }


def run_pipeline(args: argparse.Namespace) -> tuple[Path, dict[str, Any]]:
    repo_root = args.repo_root.resolve()
    config = load_config(args.config.resolve())
    input_root = resolve_input_root(repo_root, config, args.input_root)
    run_id = args.run_id or datetime.now(timezone.utc).astimezone().strftime("%Y%m%d-%H%M%S")
    run_dir = args.output_root.resolve() / run_id
    run_dir.mkdir(parents=True, exist_ok=False)

    skill_preflight = _skill_preflight(repo_root, config)
    write_json(run_dir / "00_input" / "skill_preflight.json", skill_preflight)
    evidence = analyze_inputs(input_root, config)
    write_json(run_dir / "00_input" / "evidence.json", evidence)

    tools, environment = _resolve_tools(args)
    tool_report = {
        "circt_verilog": tool_record(
            tools["circt_verilog"], ["--version"], environment
        ),
        "circt_opt": tool_record(tools["circt_opt"], ["--version"], environment),
        "circt_translate": tool_record(
            tools["circt_translate"], ["--version"], environment
        ),
        "verilator": tool_record(tools["verilator"], ["--version"]),
        "make": tool_record(tools["make"], ["--version"]),
        "cxx": tool_record(tools["cxx"], ["--version"]),
        "pkg_config": tool_record(tools["pkg_config"], ["--version"]),
    }
    write_json(run_dir / "01_tools" / "tools.json", tool_report)

    circt, inventory, failures = _circt_flow(
        input_root, config, evidence, tools, environment, run_dir
    )
    cross_check = _cross_check(config, evidence, inventory)
    write_json(run_dir / "02_circt" / "structure_cross_check.json", cross_check)
    agent_context = (
        build_agent_context(evidence, inventory, failures)
        if inventory is not None
        else {
            "format": "llm4eda-staged-circt-agent-context-v1",
            "status": "blocked_without_core_ir",
            "candidates": [],
        }
    )
    write_json(run_dir / "04_agent_context" / "context.json", agent_context)

    verilator = _run_verilator(
        input_root, config, evidence, inventory, tools, run_dir
    )
    hybrid = _hybrid_plan(config, circt, verilator)
    write_json(run_dir / "05_hybrid" / "plan.json", hybrid)

    fallback_ready = bool(verilator.get("top_model_pass"))
    native_complete = bool(circt.get("native_systemc_complete"))
    completed = (
        skill_preflight["pass"]
        and evidence["pass"]
        and circt.get("pass", False)
        and (native_complete or fallback_ready)
    )
    report = {
        "format": "llm4eda-staged-circt-systemc-run-v1",
        "case": config["case"],
        "top": config["top"],
        "run_id": run_id,
        "status": (
            "completed_native_systemc"
            if completed and native_complete
            else (
                "completed_with_verilator_fallback"
                if completed and fallback_ready
                else "failed_or_blocked"
            )
        ),
        "pass": completed,
        "native_circt_systemc_complete": native_complete,
        "verilator_fallback_ready": fallback_ready,
        "functional_equivalence": "not_run_no_shared_stimulus_in_verilog_dsc_bundle",
        "skill_preflight": skill_preflight,
        "input_evidence": evidence,
        "circt": circt,
        "structure_cross_check": cross_check,
        "verilator": verilator,
        "hybrid": hybrid,
        "failures": failures,
        "artifacts": {
            "run_dir": str(run_dir),
            "agent_context": str((run_dir / "04_agent_context" / "context.json").resolve()),
            "hybrid_plan": str((run_dir / "05_hybrid" / "plan.json").resolve()),
        },
    }
    write_json(run_dir / "report.json", report)
    return run_dir, report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="UHDM 证据约束的 CIRCT HW/Comb/Seq 分阶段 SystemC 与 Verilator 回退验证"
    )
    parser.add_argument("action", choices=["run"], nargs="?", default="run")
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("configs/staged_circt.json"),
    )
    parser.add_argument("--input-root", type=Path)
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path(".work/runs/staged-circt"),
    )
    parser.add_argument("--run-id")
    parser.add_argument("--circt-root", type=Path)
    parser.add_argument("--circt-library-path")
    parser.add_argument("--circt-verilog")
    parser.add_argument("--circt-opt")
    parser.add_argument("--circt-translate")
    parser.add_argument("--verilator")
    parser.add_argument("--make")
    parser.add_argument("--cxx")
    parser.add_argument("--pkg-config")
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    try:
        run_dir, report = run_pipeline(args)
    except (FileExistsError, FileNotFoundError, TypeError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(
        json.dumps(
            {
                "run_dir": str(run_dir),
                "report": str(run_dir / "report.json"),
                "status": report["status"],
                "native_circt_systemc_complete": report[
                    "native_circt_systemc_complete"
                ],
                "verilator_fallback_ready": report["verilator_fallback_ready"],
                "functional_equivalence": report["functional_equivalence"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if report["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
