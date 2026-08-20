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

from ..uhdm_systemc.contract import build_uhdm_structure_contract
from ..uhdm_systemc.systemc_clang import run_systemc_clang
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


def _render_systemc_runtime_probe(header: Path, top: str) -> str:
    text = header.read_text(encoding="utf-8", errors="replace")
    match = re.search(
        rf"SC_MODULE\({re.escape(top)}\)\s*\{{(?P<body>.*?)SC_CTOR\({re.escape(top)}\)",
        text,
        re.DOTALL,
    )
    if not match:
        raise ValueError(f"generated SystemC does not contain top SC_MODULE({top})")
    ports: list[tuple[str, str]] = []
    for line in match.group("body").splitlines():
        port = re.match(
            r"\s*sc_(?:in|out|inout)<(.+)>\s+([A-Za-z_][A-Za-z0-9_]*)\s*;\s*$",
            line,
        )
        if port:
            ports.append((port.group(1), port.group(2)))
    signals = "\n".join(
        f'  sc_core::sc_signal<{port_type}> sig_{name}{{"sig_{name}"}};'
        for port_type, name in ports
    )
    bindings = "\n".join(f"  dut.{name}(sig_{name});" for _, name in ports)
    return f'''#include <systemc>
#include <iostream>
#include "{header.name}"

static unsigned module_count = 0;
static unsigned port_count = 0;

static void visit(const sc_core::sc_object &object) {{
  if (dynamic_cast<const sc_core::sc_module *>(&object))
    ++module_count;
  if (dynamic_cast<const sc_core::sc_port_base *>(&object))
    ++port_count;
  for (const sc_core::sc_object *child : object.get_child_objects())
    visit(*child);
}}

int sc_main(int, char **) {{
{signals}
  {top} dut{{"dut"}};
{bindings}
  sc_core::sc_start(sc_core::SC_ZERO_TIME);
  visit(dut);
  std::cout << "CIRCT_SYSTEMC_MODULES=" << module_count << "\\n";
  std::cout << "CIRCT_SYSTEMC_PORTS=" << port_count << "\\n";
  return 0;
}}
'''


def _probe_metric(report: dict[str, Any], name: str) -> int | None:
    path = report.get("stdout_log")
    if not path:
        return None
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    match = re.search(rf"^{re.escape(name)}=(\d+)$", text, re.MULTILINE)
    return int(match.group(1)) if match else None


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

    structure_ir = stage_dir / f"{config['top']}.structure.systemc.mlir"
    structure_conversion = run_command(
        "04_hw_structure_to_systemc",
        [
            str(circt_opt),
            "--convert-hw-to-systemc=structure-only=true",
            str(conversion_input),
            "-o",
            str(structure_ir),
        ],
        cwd=root,
        output_dir=stage_dir,
        timeout=timeout,
        artifact=structure_ir,
        env=environment,
    )
    if structure_conversion["pass"]:
        structure_cpp = stage_dir / f"{config['top']}.structure.systemc.hpp"
        structure_emission = run_command(
            "05_export_hw_structure_systemc",
            [
                str(circt_translate),
                "--export-systemc",
                str(structure_ir),
                "-o",
                str(structure_cpp),
            ],
            cwd=root,
            output_dir=stage_dir,
            timeout=timeout,
            artifact=structure_cpp,
            env=environment,
        )
    else:
        structure_cpp = None
        structure_emission = blocked_stage(
            "05_export_hw_structure_systemc", "04_hw_structure_to_systemc"
        )

    cxx = tools["cxx"]
    pkg_config = tools["pkg_config"]
    if structure_emission["pass"] and cxx is not None and pkg_config is not None:
        pkg_flags = run_command(
            "06_systemc_compile_flags",
            [str(pkg_config), "--cflags", "systemc"],
            cwd=root,
            output_dir=stage_dir,
            timeout=timeout,
            env=environment,
        )
        flags = (
            Path(pkg_flags["stdout_log"])
            .read_text(encoding="utf-8", errors="replace")
            .split()
            if pkg_flags["pass"]
            else []
        )
        structure_compile = run_command(
            "07_compile_hw_structure_systemc",
            [
                str(cxx),
                "-std=c++17",
                "-x",
                "c++",
                "-fsyntax-only",
                *flags,
                str(structure_cpp),
            ],
            cwd=root,
            output_dir=stage_dir,
            timeout=timeout,
            env=environment,
        )
        runtime_probe_source = stage_dir / "hw_structure_runtime_probe.cpp"
        runtime_probe_source.write_text(
            _render_systemc_runtime_probe(structure_cpp, str(config["top"])),
            encoding="utf-8",
        )
        runtime_flags = run_command(
            "07b_systemc_runtime_flags",
            [str(pkg_config), "--cflags", "--libs", "systemc"],
            cwd=root,
            output_dir=stage_dir,
            timeout=timeout,
            env=environment,
        )
        link_flags = (
            Path(runtime_flags["stdout_log"])
            .read_text(encoding="utf-8", errors="replace")
            .split()
            if runtime_flags["pass"]
            else []
        )
        runtime_probe = stage_dir / "hw_structure_runtime_probe"
        runtime_compile = run_command(
            "07c_compile_hw_structure_runtime_probe",
            [
                str(cxx),
                "-std=c++17",
                str(runtime_probe_source),
                *link_flags,
                "-o",
                str(runtime_probe),
            ],
            cwd=stage_dir,
            output_dir=stage_dir,
            timeout=timeout,
            artifact=runtime_probe,
            env=environment,
        )
        runtime_run = (
            run_command(
                "07d_run_hw_structure_runtime_probe",
                [str(runtime_probe)],
                cwd=stage_dir,
                output_dir=stage_dir,
                timeout=timeout,
                env=environment,
            )
            if runtime_compile["pass"]
            else blocked_stage(
                "07d_run_hw_structure_runtime_probe",
                "07c_compile_hw_structure_runtime_probe",
            )
        )
    else:
        pkg_flags = blocked_stage(
            "06_systemc_compile_flags",
            "05_export_hw_structure_systemc_or_required_tool",
        )
        structure_compile = blocked_stage(
            "07_compile_hw_structure_systemc",
            "05_export_hw_structure_systemc_or_required_tool",
        )
        runtime_flags = blocked_stage(
            "07b_systemc_runtime_flags",
            "05_export_hw_structure_systemc_or_required_tool",
        )
        runtime_compile = blocked_stage(
            "07c_compile_hw_structure_runtime_probe",
            "05_export_hw_structure_systemc_or_required_tool",
        )
        runtime_run = blocked_stage(
            "07d_run_hw_structure_runtime_probe",
            "07c_compile_hw_structure_runtime_probe",
        )

    llhd_core_ir = stage_dir / f"{config['top']}.llhd-core.mlir"
    llhd_core_pipeline = (
        "builtin.module("
        "hw.module(llhd-wrap-procedural-ops),"
        "llhd-inline-calls,llhd-inline-suspend-free-coroutines,symbol-dce,"
        "hw.module(sroa,llhd-mem2reg,llhd-hoist-signals,llhd-deseq,"
        "llhd-lower-processes,cse,canonicalize,llhd-unroll-loops,cse,"
        "canonicalize,llhd-remove-control-flow,cse,canonicalize,"
        "map-arith-to-comb{enable-best-effort-lowering=true},"
        "llhd-combine-drives,llhd-sig2reg,cse,canonicalize))"
    )
    llhd_core = run_command(
        "08a_prepare_llhd_core",
        [
            str(circt_opt),
            f"--pass-pipeline={llhd_core_pipeline}",
            str(conversion_input),
            "-o",
            str(llhd_core_ir),
        ],
        cwd=root,
        output_dir=stage_dir,
        timeout=timeout,
        artifact=llhd_core_ir,
        env=environment,
    )
    lowered_llhd_ir = stage_dir / f"{config['top']}.llhd-lowered.mlir"
    llhd_remaining = (
        run_command(
            "08b_lower_remaining_llhd_processes",
            [
                str(circt_opt),
                "--mlir-disable-threading",
                "--llhd-lower-timed-processes",
                str(llhd_core_ir),
                "-o",
                str(lowered_llhd_ir),
            ],
            cwd=root,
            output_dir=stage_dir,
            timeout=timeout,
            artifact=lowered_llhd_ir,
            env=environment,
        )
        if llhd_core["pass"]
        else blocked_stage("08b_lower_remaining_llhd_processes", "08a_prepare_llhd_core")
    )
    lowered_inventory = None
    if llhd_remaining["pass"]:
        lowered_inventory = analyze_core_ir(
            lowered_llhd_ir.read_text(encoding="utf-8", errors="replace"),
            str(config["top"]),
        )
        write_json(stage_dir / "llhd_lowered_inventory.json", lowered_inventory)

    systemc_ir = stage_dir / f"{config['top']}.systemc.mlir"
    conversion = (
        run_command(
            "08c_full_hw_comb_seq_to_systemc",
            [
                str(circt_opt),
                "--convert-hw-to-systemc",
                str(lowered_llhd_ir),
                "-o",
                str(systemc_ir),
            ],
            cwd=root,
            output_dir=stage_dir,
            timeout=timeout,
            artifact=systemc_ir,
            env=environment,
        )
        if llhd_remaining["pass"]
        else blocked_stage(
            "08c_full_hw_comb_seq_to_systemc",
            "08b_lower_remaining_llhd_processes",
        )
    )
    conversion_failure = None if conversion["pass"] else classify_circt_failure(
        _stderr(conversion), "hw_to_systemc"
    )
    if conversion_failure:
        failures.append(conversion_failure)

    if conversion["pass"]:
        systemc_cpp = stage_dir / f"{config['top']}.systemc.cpp"
        emission = run_command(
            "09_export_full_systemc",
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
        emission = blocked_stage(
            "09_export_full_systemc", "08c_full_hw_comb_seq_to_systemc"
        )
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
            "structure_conversion_pass": structure_conversion["pass"],
            "structure_emission_pass": structure_emission["pass"],
            "structure_cpp_compile_pass": structure_compile["pass"],
            "runtime_elaboration_pass": runtime_run["pass"],
            "runtime_module_count": _probe_metric(
                runtime_run, "CIRCT_SYSTEMC_MODULES"
            ),
            "runtime_port_count": _probe_metric(runtime_run, "CIRCT_SYSTEMC_PORTS"),
            "systemc_skeleton_pass": structure_compile["pass"]
            and runtime_run["pass"],
        },
        "comb": {
            "ssa_extracted": inventory["dialect_totals"]["comb"] > 0,
            "operation_count": inventory["dialect_totals"]["comb"],
            "module_count": len(partitions["comb_modules"]),
            "native_completion": conversion["pass"] and emission["pass"],
            "blocked_by": (
                None if conversion["pass"] else "08c_full_hw_comb_seq_to_systemc"
            ),
        },
        "seq": {
            "ssa_extracted": inventory["dialect_totals"]["seq"] > 0,
            "operation_count": inventory["dialect_totals"]["seq"],
            "module_count": len(partitions["seq_modules"]),
            "native_completion": conversion["pass"] and emission["pass"],
            "blocked_by": (
                None if conversion["pass"] else "08c_full_hw_comb_seq_to_systemc"
            ),
        },
        "llhd": {
            "ssa_extracted": inventory["dialect_totals"]["llhd"] > 0,
            "operation_count": inventory["dialect_totals"]["llhd"],
            "module_count": len(partitions["llhd_modules"]),
            "lowering_pass": llhd_remaining["pass"],
            "remaining_operation_count": (
                lowered_inventory["dialect_totals"]["llhd"]
                if lowered_inventory
                else None
            ),
            "remaining_module_count": (
                len(lowered_inventory["stage_partitions"]["llhd_modules"])
                if lowered_inventory
                else None
            ),
            "first_failure_operation": (
                conversion_failure.get("operation")
                if conversion_failure
                and str(conversion_failure.get("operation", "")).startswith("llhd.")
                else None
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
            "hw_structure_to_systemc": structure_conversion,
            "export_hw_structure_systemc": structure_emission,
            "systemc_compile_flags": pkg_flags,
            "compile_hw_structure_systemc": structure_compile,
            "systemc_runtime_flags": runtime_flags,
            "compile_hw_structure_runtime_probe": runtime_compile,
            "run_hw_structure_runtime_probe": runtime_run,
            "prepare_llhd_core": llhd_core,
            "lower_remaining_llhd_processes": llhd_remaining,
            "full_hw_comb_seq_to_systemc": conversion,
            "export_full_systemc": emission,
        },
        "stage_matrix": stage_matrix,
        "artifacts": {
            "core_ir": str(core_ir.resolve()),
            "inventory": str((stage_dir / "core_ir_inventory.json").resolve()),
            "structure_systemc_ir": (
                str(structure_ir.resolve()) if structure_conversion["pass"] else None
            ),
            "structure_systemc_cpp": (
                str(structure_cpp.resolve()) if structure_cpp else None
            ),
            "llhd_core_ir": str(llhd_core_ir.resolve()) if llhd_core["pass"] else None,
            "llhd_lowered_ir": (
                str(lowered_llhd_ir.resolve()) if llhd_remaining["pass"] else None
            ),
            "llhd_lowered_inventory": (
                str((stage_dir / "llhd_lowered_inventory.json").resolve())
                if lowered_inventory
                else None
            ),
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


def _write_reduced_systemc_header(
    source: Path,
    selected_modules: list[str],
    inventory: dict[str, Any],
    output: Path,
) -> Path:
    dependencies: dict[str, set[str]] = {}
    for instance in inventory.get("instances", []):
        dependencies.setdefault(str(instance["parent"]), set()).add(
            str(instance["module"])
        )
    closure = set(selected_modules)
    pending = list(selected_modules)
    while pending:
        parent = pending.pop()
        for child in dependencies.get(parent, set()):
            if child not in closure:
                closure.add(child)
                pending.append(child)

    text = source.read_text(encoding="utf-8", errors="replace")
    blocks: list[tuple[str, str]] = []
    cursor = 0
    marker = re.compile(r"^SC_MODULE\(([A-Za-z_][A-Za-z0-9_]*)\)\s*\{", re.MULTILINE)
    while match := marker.search(text, cursor):
        depth = 0
        end = match.end()
        for index in range(match.end() - 1, len(text)):
            if text[index] == "{":
                depth += 1
            elif text[index] == "}":
                depth -= 1
                if depth == 0:
                    semicolon = text.find(";", index)
                    end = semicolon + 1 if semicolon >= 0 else index + 1
                    break
        blocks.append((match.group(1), text[match.start() : end]))
        cursor = end
    selected = [block for name, block in blocks if name in closure]
    available_modules = {name for name, _ in blocks}
    if available_modules & closure != closure:
        missing = closure - available_modules
        raise ValueError(f"generated SystemC modules are missing: {sorted(missing)}")
    output.write_text(
        "#ifndef DSCFLOW_CIRCT_STRUCTURE_ANALYSIS_HPP\n"
        "#define DSCFLOW_CIRCT_STRUCTURE_ANALYSIS_HPP\n\n"
        "#include <systemc.h>\n\n"
        + "\n\n".join(selected)
        + "\n\n#endif\n",
        encoding="utf-8",
    )
    return output


def _analyze_circt_systemc_structure(
    repo_root: Path,
    config: dict[str, Any],
    circt: dict[str, Any],
    inventory: dict[str, Any] | None,
    run_dir: Path,
) -> dict[str, Any]:
    systemc_config = dict(config.get("systemc_clang", {}))
    if not systemc_config.get("enabled", False):
        return {"pass": False, "status": "disabled"}
    header_value = circt.get("artifacts", {}).get("structure_systemc_cpp")
    if not header_value or inventory is None:
        return {"pass": False, "status": "blocked_without_hw_structure"}
    header = Path(header_value)
    analysis_all = bool(systemc_config.get("analysis_all_modules", False))
    targets = systemc_config.get("analysis_targets", [])
    module_names = (
        list(inventory["module_names"])
        if analysis_all
        else [str(item["module"]) for item in targets]
    )
    analysis_header = header
    if not analysis_all and module_names:
        analysis_header = _write_reduced_systemc_header(
            header,
            module_names,
            inventory,
            header.parent / "hw_structure_systemc_clang.hpp",
        )
    systemc_config["candidate_header"] = analysis_header.name
    contract = {
        "top": config["top"],
        "modules": [{"name": name} for name in module_names],
    }
    return run_systemc_clang(
        repo_root,
        contract,
        analysis_header.parent,
        run_dir / "02_circt" / "systemc_clang",
        systemc_config,
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
    repo_root: Path,
    config: dict[str, Any],
    evidence: dict[str, Any],
    inventory: dict[str, Any] | None,
) -> dict[str, Any]:
    if inventory is None:
        return {"pass": False, "status": "blocked_without_circt_inventory"}
    reference_config = config.get("structural_reference", {})
    structure_path = reference_config.get("structure_ir")
    hierarchy_path = reference_config.get("hierarchy_json")
    canonical_contract = None
    if structure_path and hierarchy_path:
        canonical_contract = build_uhdm_structure_contract(
            read_json((repo_root / str(structure_path)).resolve()),
            read_json((repo_root / str(hierarchy_path)).resolve()),
        )
    if canonical_contract:
        uhdm_definitions = {item["name"] for item in canonical_contract["modules"]}
        uhdm_invocations = int(canonical_contract["instance_count"])
        uhdm_definition_edges = sum(
            len(item.get("instances", [])) for item in canonical_contract["modules"]
        )
        canonical_ready = True
    else:
        uhdm_definitions = {
            clean_definition(item) for item in evidence["hierarchy"]["definitions"]
        }
        uhdm_invocations = evidence["hierarchy"]["invocation_count"]
        uhdm_definition_edges = None
        canonical_ready = evidence["hierarchy_completeness"]["pass"]
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
        "canonical_uhdm_reference_ready": canonical_ready,
        "circt_instance_operation_count": inventory["instance_operation_count"],
        "uhdm_definition_edge_count": uhdm_definition_edges,
        "uhdm_elaborated_instance_count": uhdm_invocations,
        "definition_edge_count_match": (
            uhdm_definition_edges == inventory["instance_operation_count"]
            if uhdm_definition_edges is not None
            else False
        ),
        "pass": (
            config["top"] in circt_modules
            and bool(exact_common)
            and canonical_ready
            and uhdm_definition_edges == inventory["instance_operation_count"]
        ),
        "canonical_equivalence_proven": False,
        "limitation": (
            "CIRCT specializes parameterized module names and flattens aggregate ports; "
            "the counts and shared definitions are checked here, while complete port/path "
            "equivalence is checked on normalized SystemC analysis artifacts."
        ),
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
    structure_analysis = _analyze_circt_systemc_structure(
        repo_root, config, circt, inventory, run_dir
    )
    circt["structure_systemc_clang"] = structure_analysis
    if "stage_matrix" in circt and "hw" in circt["stage_matrix"]:
        circt["stage_matrix"]["hw"]["systemc_clang_pass"] = structure_analysis.get(
            "pass", False
        )
    write_json(run_dir / "02_circt" / "report.json", circt)
    cross_check = _cross_check(repo_root, config, evidence, inventory)
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
