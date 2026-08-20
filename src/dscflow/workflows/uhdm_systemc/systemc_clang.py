from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

SYSTEMC_CLANG_IMAGE = "docker.io/rseac/systemc-clang:clang-15.0.6"
SYSTEMC_CLANG_IMAGE_DIGEST = (
    "sha256:acb6f2b4c7d191eee90926341009eb24d3b57876d9e014342dad670333d7bf53"
)
SYSTEMC_CLANG_REVISION = "f014deff24c6ffc2c479d39e1eeeb47809e5f372"


def _simple_name(name: str) -> str:
    return name.rsplit("::", 1)[-1].strip()


def render_analysis_tu(candidate_header: str, top_cpp_type: str, top_name: str) -> str:
    """Create an elaboratable TU so systemc-clang can see the instance graph."""

    return f'''#include <systemc>
#include "{candidate_header}"

int sc_main(int, char**) {{
  {top_cpp_type} dut("{top_name}");
  sc_core::sc_start(sc_core::SC_ZERO_TIME);
  return 0;
}}
'''


def parse_systemc_clang_output(output: str) -> dict[str, Any]:
    """Parse the stable labels emitted by systemc-clang's Model::dump.

    The upstream output is diagnostic text rather than JSON.  We deliberately
    consume only named labels from Model/ModuleInstance and retain the complete
    raw log as evidence.  Pointer values and unlabelled debug lines are ignored.
    """

    modules: dict[str, dict[str, Any]] = {}
    current: dict[str, Any] | None = None
    port_direction: str | None = None
    current_process: dict[str, Any] | None = None
    pending_process_name: str | None = None
    started = (
        "Start SCCL" in output or "Parsed SystemC model from systemc-clang" in output
    )
    parse_errors = [
        line.strip()
        for line in output.splitlines()
        if re.search(r"(^|\s)(fatal )?error:", line, re.IGNORECASE)
    ]

    for raw_line in output.splitlines():
        line = raw_line.strip()
        if line.startswith("LLM4EDA_SYSTEMC_CLANG_TARGET "):
            current = None
            current_process = None
            pending_process_name = None
            port_direction = None
            continue
        module_match = re.search(r"Name:\s+(.+?)\s*$", line)
        if module_match:
            name = _simple_name(module_match.group(1))
            current = modules.setdefault(
                name,
                {
                    "name": name,
                    "instances": [],
                    "nested_modules": [],
                    "ports": [],
                    "signals": [],
                    "processes": [],
                    "bindings": [],
                },
            )
            port_direction = None
            current_process = None
            pending_process_name = None
            continue
        if current is None:
            continue

        instance_match = re.search(
            r"module_name:\s+(\S+)\s+instance_name:\s+(\S+)", line
        )
        if instance_match:
            instance_name = instance_match.group(2)
            if (
                instance_name not in {"", "NONE"}
                and instance_name not in current["instances"]
            ):
                current["instances"].append(instance_name)
            continue
        if line.startswith("number_of_input_ports:"):
            port_direction = "input"
            continue
        if line.startswith("number_of_output_ports:"):
            port_direction = "output"
            continue
        if line.startswith("number_of_inout_ports:"):
            port_direction = "inout"
            continue
        if line.startswith("number_of_instream_ports:"):
            port_direction = "stream_input"
            continue
        if line.startswith("number_of_outstream_ports:"):
            port_direction = "stream_output"
            continue
        if line.startswith(("number_of_other_vars:", "number_of_nested_modules:")):
            port_direction = None
            continue
        port_match = re.match(r"^name:\s+(\S+)\s+(.+)$", line)
        if port_match and port_direction:
            port = {
                "name": port_match.group(1),
                "direction": port_direction,
                "type": port_match.group(2).strip(),
            }
            if port not in current["ports"]:
                current["ports"].append(port)
            continue
        nested_match = re.search(
            r"module type name\s+(\S+).*instance name:\s*(.+)$", line
        )
        if nested_match:
            fact = {
                "module": _simple_name(nested_match.group(1)),
                "instances": nested_match.group(2).split(),
            }
            if fact not in current["nested_modules"]:
                current["nested_modules"].append(fact)
            continue
        process_match = re.match(
            r"^(?!process_type\b)(\w+):\s+(SC_(?:C?THREAD|METHOD))\b", line
        )
        process_name_match = re.match(r"^(\w+):\s+entry_name:\s+", line)
        entry_match = re.search(
            r"EntryFunctionContainer '([^']+)' processType '(SC_(?:C?THREAD|METHOD))'",
            line,
        )
        if entry_match:
            process_name, process_kind = entry_match.groups()
            matches = [
                item for item in current["processes"] if item["name"] == process_name
            ]
            if matches:
                current_process = matches[0]
                current_process["kind"] = process_kind
            else:
                current_process = {
                    "name": process_name,
                    "kind": process_kind,
                    "wait_count": 0,
                    "sensitivity_count": 0,
                    "reset_signal": "",
                    "reset_edge": "",
                }
                current["processes"].append(current_process)
            continue
        if process_match:
            process_name, process_kind = process_match.groups()
            matches = [
                item for item in current["processes"] if item["name"] == process_name
            ]
            if matches:
                current_process = matches[0]
                current_process["kind"] = process_kind
            else:
                current_process = {
                    "name": process_name,
                    "kind": process_kind,
                    "wait_count": 0,
                    "sensitivity_count": 0,
                    "reset_signal": "",
                    "reset_edge": "",
                }
                current["processes"].append(current_process)
            continue
        if process_name_match:
            pending_process_name = process_name_match.group(1)
            matches = [
                item
                for item in current["processes"]
                if item["name"] == pending_process_name
            ]
            if matches:
                current_process = matches[0]
            else:
                current_process = {
                    "name": pending_process_name,
                    "kind": "",
                    "wait_count": 0,
                    "sensitivity_count": 0,
                    "reset_signal": "",
                    "reset_edge": "",
                }
                current["processes"].append(current_process)
            continue
        process_type_match = re.match(
            r"^process_type:\s+(SC_(?:C?THREAD|METHOD))\b", line
        )
        if process_type_match and pending_process_name and current_process is not None:
            current_process["kind"] = process_type_match.group(1)
            continue
        sensitivity_match = re.search(r"number_of_sensitivity_signals:\s*(\d+)", line)
        if sensitivity_match and current_process is not None:
            current_process["sensitivity_count"] = int(sensitivity_match.group(1))
            continue
        if current_process is not None and line.startswith("Wait Call:"):
            current_process["wait_count"] += 1
            continue
        if current_process is not None and line.startswith("reset_signal "):
            current_process["reset_signal"] = line.removeprefix("reset_signal ").strip()
            continue
        if current_process is not None and line.startswith("reset_edge "):
            current_process["reset_edge"] = line.removeprefix("reset_edge ").strip()
            continue
        caller = re.match(r"caller_instance_name:\s*(.*)$", line)
        if caller:
            current["bindings"].append({"caller_instance": caller.group(1).strip()})
            continue
        if current["bindings"] and line.startswith("caller_port_name:"):
            current["bindings"][-1]["caller_port"] = line.split(":", 1)[1].strip()
            continue
        if current["bindings"] and line.startswith("callee_instance_name::"):
            current["bindings"][-1]["callee_instance"] = line.split("::", 1)[1].strip()
            continue
        if current["bindings"] and line.startswith("callee_port_name:"):
            current["bindings"][-1]["callee_port"] = line.split(":", 1)[1].strip()

    for module in modules.values():
        module["instances"].sort()
        module["ports"].sort(key=lambda item: (item["direction"], item["name"]))
        module["processes"].sort(key=lambda item: item["name"])
    return {
        "frontend_started": started,
        "modules": sorted(modules.values(), key=lambda item: item["name"]),
        "parse_errors": parse_errors,
    }


def compare_systemc_clang(
    contract: dict[str, Any], observed: dict[str, Any], config: dict[str, Any]
) -> dict[str, Any]:
    expected_modules = {
        _simple_name(str(item["name"])) for item in contract.get("modules", [])
    }
    module_map = {str(item["name"]): item for item in observed.get("modules", [])}
    actual_modules = set(module_map)
    errors = list(observed.get("parse_errors", []))
    if not observed.get("frontend_started"):
        errors.append("systemc-clang frontend marker was not observed")
    missing_modules = expected_modules - actual_modules
    if missing_modules:
        errors.append(f"systemc-clang module types missing: {sorted(missing_modules)}")

    expected_processes = config.get("expected_processes", [])
    for expected in expected_processes:
        module_name = _simple_name(str(expected["module"]))
        process_name = str(expected["name"])
        kind = str(expected.get("kind", ""))
        processes = module_map.get(module_name, {}).get("processes", [])
        matches = [item for item in processes if item.get("name") == process_name]
        if not matches:
            errors.append(
                f"systemc-clang process missing: {module_name}.{process_name}"
            )
            continue
        if kind and matches[0].get("kind") != kind:
            errors.append(
                f"systemc-clang process kind mismatch: {module_name}.{process_name} "
                f"{matches[0].get('kind')} != {kind}"
            )
        if expected.get("requires_wait") and int(matches[0].get("wait_count", 0)) == 0:
            errors.append(
                f"systemc-clang found no wait() in {module_name}.{process_name}"
            )

    return {
        "pass": not errors,
        "expected_module_types": sorted(expected_modules),
        "actual_module_types": sorted(actual_modules),
        "expected_processes": expected_processes,
        "errors": errors,
    }


def _container_command(
    engine: str,
    image: str,
    executable: str,
    tool_root: Path,
    candidate_dir: Path,
    output_dir: Path,
    source_name: str,
    config: dict[str, Any],
) -> list[str]:
    systemc_include = str(
        config.get("container_systemc_include", "/opt/systemc-2.3.3/include")
    )
    clang_resource_include = str(
        config.get(
            "container_clang_resource_include",
            "/opt/clang-15.0.6/lib/clang/15.0.6/include",
        )
    )
    return [
        engine,
        "run",
        "--rm",
        "--cidfile",
        str(output_dir / f"{source_name}.cid"),
        "--userns=keep-id",
        "-v",
        f"{candidate_dir}:/workspace/candidate:ro",
        "-v",
        f"{output_dir}:/workspace/output",
        "-v",
        f"{tool_root / 'source'}:/systemc-clang:ro",
        "-v",
        f"{tool_root / 'build'}:/systemc-clang-build:ro",
        image,
        executable,
        f"/workspace/output/{source_name}",
        "--debug",
        "--",
        "-D__STDC_CONSTANT_MACROS",
        "-D__STDC_LIMIT_MACROS",
        "-I/workspace/candidate",
        f"-I{clang_resource_include}",
        f"-I{systemc_include}",
        "-x",
        "c++",
        "-std=c++17",
        "-w",
        "-c",
    ]


def run_systemc_clang(
    repo_root: Path,
    contract: dict[str, Any],
    candidate_dir: Path,
    output_dir: Path,
    config: dict[str, Any],
) -> dict[str, Any]:
    candidate_header = str(config.get("candidate_header", "functional_model.hpp"))
    header = candidate_dir / candidate_header
    if not header.is_file():
        return {
            "pass": False,
            "status": "blocked",
            "failure_kind": "candidate_header_missing",
            "path": str(header),
        }
    output_dir.mkdir(parents=True, exist_ok=True)
    if config.get("analysis_all_modules"):
        targets = [
            {"module": str(module["name"]), "cpp_type": str(module["name"])}
            for module in contract.get("modules", [])
        ]
    else:
        targets = config.get("analysis_targets") or [
            {
                "module": str(contract["top"]),
                "cpp_type": str(config.get("top_cpp_type", contract["top"])),
            }
        ]
    sources: list[tuple[str, Path]] = []
    for target in targets:
        module_name = str(target["module"])
        source = output_dir / f"systemc_clang_{module_name}.cpp"
        source.write_text(
            render_analysis_tu(
                candidate_header,
                str(target["cpp_type"]),
                module_name,
            ),
            encoding="utf-8",
        )
        sources.append((module_name, source))

    executable = config.get("executable") or shutil.which("systemc-clang")
    image = str(config.get("image", SYSTEMC_CLANG_IMAGE))
    if executable:
        commands = [
            [
                str(executable),
                str(source),
                "--debug",
                "--",
                "-D__STDC_CONSTANT_MACROS",
                "-D__STDC_LIMIT_MACROS",
                f"-I{candidate_dir}",
                *[
                    f"-I{os.path.expandvars(str(path))}"
                    for path in config.get("include_dirs", [])
                ],
                "-x",
                "c++",
                "-std=c++17",
                "-w",
                "-c",
            ]
            for _, source in sources
        ]
        backend = "native"
    else:
        engine = (
            config.get("container_engine")
            or shutil.which("podman")
            or shutil.which("docker")
        )
        if not engine:
            return {
                "pass": False,
                "status": "blocked",
                "failure_kind": "systemc_clang_missing",
                "install_command": "dscflow uhdm-systemc systemc-clang-install",
            }
        tool_root = (
            repo_root
            / ".work"
            / "toolchains"
            / "systemc-clang"
            / SYSTEMC_CLANG_REVISION
        )
        container_executable = str(
            config.get("container_executable", "/systemc-clang-build/systemc-clang")
        )
        if not (tool_root / "build" / Path(container_executable).name).is_file():
            return {
                "pass": False,
                "status": "blocked",
                "failure_kind": "systemc_clang_not_built",
                "tool_root": str(tool_root),
                "install_command": "dscflow uhdm-systemc systemc-clang-install",
            }
        commands = [
            _container_command(
                str(engine),
                image,
                container_executable,
                tool_root,
                candidate_dir,
                output_dir,
                source.name,
                config,
            )
            for _, source in sources
        ]
        backend = "container"

    processes: list[subprocess.CompletedProcess[str]] = []
    raw_parts: list[str] = []
    for (module_name, _), command in zip(sources, commands, strict=True):
        try:
            process = subprocess.run(
                command,
                cwd=str(output_dir),
                capture_output=True,
                text=True,
                timeout=int(config.get("timeout_seconds", 300)),
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            cidfile = output_dir / f"{source.name}.cid"
            if cidfile.is_file():
                container_id = cidfile.read_text(encoding="utf-8").strip()
                if container_id:
                    subprocess.run(
                        [command[0], "rm", "-f", container_id],
                        capture_output=True,
                        text=True,
                        timeout=30,
                        check=False,
                    )
                cidfile.unlink(missing_ok=True)
            return {
                "pass": False,
                "status": "failed",
                "failure_kind": "systemc_clang_timeout",
                "module": module_name,
                "error": str(exc),
                "command": command,
            }
        (output_dir / f"{source.name}.cid").unlink(missing_ok=True)
        processes.append(process)
        raw_parts.append(
            f"LLM4EDA_SYSTEMC_CLANG_TARGET {module_name}\n"
            + process.stdout
            + "\n"
            + process.stderr
        )
    raw = "\n".join(raw_parts)
    raw_log = output_dir / "systemc-clang.log"
    raw_log.write_text(raw, encoding="utf-8")
    observed = parse_systemc_clang_output(raw)
    comparison = compare_systemc_clang(contract, observed, config)
    failed_targets = [
        module_name
        for (module_name, _), process in zip(sources, processes, strict=True)
        if process.returncode != 0
    ]
    if failed_targets:
        comparison["errors"].insert(
            0, f"systemc-clang failed targets: {failed_targets}"
        )
        comparison["pass"] = False
    result = {
        "format": "llm4eda-systemc-clang-analysis",
        "version": "1.0.0",
        "backend": backend,
        "tool": "anikau31/systemc-clang (SCCL)",
        "upstream_revision": SYSTEMC_CLANG_REVISION,
        "image": image if backend == "container" else None,
        "commands": commands,
        "targets": [module_name for module_name, _ in sources],
        "returncodes": [process.returncode for process in processes],
        "observed": observed,
        "comparison": comparison,
        "raw_log": str(raw_log),
        "pass": comparison["pass"],
        "claim_boundary": (
            "systemc-clang statically identifies SystemC module types and processes; "
            "elaborated instance paths and concrete channel bindings are independently "
            "checked by the SystemC runtime probe against UHDM."
        ),
    }
    report = output_dir / "systemc-clang.json"
    report.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    result["report"] = str(report)
    return result


def install_systemc_clang(
    repo_root: Path, image: str = SYSTEMC_CLANG_IMAGE
) -> dict[str, Any]:
    engine = shutil.which("podman") or shutil.which("docker")
    if not engine:
        return {
            "pass": False,
            "status": "blocked",
            "failure_kind": "container_engine_missing",
        }
    pull = subprocess.run(
        [engine, "pull", image],
        capture_output=True,
        text=True,
        timeout=1800,
        check=False,
    )
    if pull.returncode != 0:
        return {
            "pass": False,
            "status": "failed",
            "backend": Path(engine).name,
            "image": image,
            "stdout": pull.stdout,
            "stderr": pull.stderr,
        }
    inspect = subprocess.run(
        [engine, "image", "inspect", image, "--format", "{{json .RepoDigests}}"],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    if inspect.returncode != 0 or SYSTEMC_CLANG_IMAGE_DIGEST not in inspect.stdout:
        return {
            "pass": False,
            "status": "failed",
            "failure_kind": "systemc_clang_image_digest_mismatch",
            "expected_digest": SYSTEMC_CLANG_IMAGE_DIGEST,
            "observed": inspect.stdout.strip(),
            "stderr": inspect.stderr,
        }
    git = shutil.which("git")
    if not git:
        return {"pass": False, "status": "blocked", "failure_kind": "git_missing"}
    tool_root = (
        repo_root / ".work" / "toolchains" / "systemc-clang" / SYSTEMC_CLANG_REVISION
    )
    source = tool_root / "source"
    build = tool_root / "build"
    tool_root.mkdir(parents=True, exist_ok=True)
    commands: list[list[str]] = []
    if not (source / ".git").is_dir():
        commands.append(
            [
                git,
                "clone",
                "--filter=blob:none",
                "https://github.com/anikau31/systemc-clang.git",
                str(source),
            ]
        )
    commands.extend(
        [
            [
                git,
                "-C",
                str(source),
                "fetch",
                "--depth",
                "1",
                "origin",
                SYSTEMC_CLANG_REVISION,
            ],
            [git, "-C", str(source), "checkout", "--detach", SYSTEMC_CLANG_REVISION],
        ]
    )
    build.mkdir(parents=True, exist_ok=True)
    commands.append(
        [
            engine,
            "run",
            "--rm",
            "--userns=keep-id",
            "-v",
            f"{source}:/systemc-clang:ro",
            "-v",
            f"{build}:/systemc-clang-build",
            image,
            "sh",
            "-lc",
            (
                "cmake -S /systemc-clang -B /systemc-clang-build -G Ninja "
                "-DCMAKE_BUILD_TYPE=Release -DLLVM_INSTALL_DIR=/opt/clang-15.0.6 "
                "-DSYSTEMC_DIR=/opt/systemc-2.3.3 && "
                "cmake --build /systemc-clang-build -j2"
            ),
        ]
    )
    logs: list[dict[str, Any]] = []
    for command in commands:
        process = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=1800,
            check=False,
        )
        logs.append(
            {
                "command": command,
                "returncode": process.returncode,
                "stdout": process.stdout,
                "stderr": process.stderr,
            }
        )
        if process.returncode != 0:
            return {
                "pass": False,
                "status": "failed",
                "backend": Path(engine).name,
                "image": image,
                "tool_root": str(tool_root),
                "steps": logs,
            }
    return {
        "pass": True,
        "status": "ready",
        "backend": Path(engine).name,
        "image": image,
        "image_digest": SYSTEMC_CLANG_IMAGE_DIGEST,
        "upstream_revision": SYSTEMC_CLANG_REVISION,
        "tool_root": str(tool_root),
        "executable": str(build / "systemc-clang"),
        "steps": logs,
    }
