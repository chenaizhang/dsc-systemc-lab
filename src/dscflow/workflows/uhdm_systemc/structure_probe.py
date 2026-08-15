from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

from .contract import (
    contract_module_map,
    expected_instance_paths,
    expected_port_paths,
)


def sc_type(width: int) -> str:
    return "bool" if width == 1 else f"sc_dt::sc_bv<{width}>"


def render_structure_probe(
    contract: dict[str, Any], candidate_header: str, top_cpp_type: str
) -> str:
    modules = contract_module_map(contract)
    top = str(contract["top"])
    hints = contract.get("non_authoritative_type_hints", {}).get(top, {})
    declarations: list[str] = []
    bindings: list[str] = []
    reset_signal: str | None = None
    for port in modules[top].get("ports", []):
        name = str(port["name"])
        width = int(hints.get(name, 1))
        signal_name = f"probe_{name}"
        if name in {"clk", "clock"} and width == 1:
            declarations.append(
                f'  sc_core::sc_clock {signal_name}("{signal_name}", 10, sc_core::SC_NS);'
            )
        else:
            declarations.append(
                f'  sc_core::sc_signal<{sc_type(width)}> {signal_name}("{signal_name}");'
            )
            if name in {"rst", "reset", "reset_n", "rst_n"} and width == 1:
                reset_signal = signal_name
        bindings.append(f"  dut.{name}({signal_name});")
    reset_write = (
        f"  {reset_signal}.write(true);"
        if reset_signal in {"probe_rst", "probe_reset"}
        else ""
    )
    return f"""#include <iostream>
#include <systemc>
#include \"{candidate_header}\"

static void dump_object(sc_core::sc_object* object) {{
  if (dynamic_cast<sc_core::sc_module*>(object) != nullptr) {{
    std::cout << "LLM4EDA_MODULE " << object->name() << "\\n";
  }}
  if (auto* port = dynamic_cast<sc_core::sc_port_base*>(object)) {{
    auto* interface = port->get_interface();
    auto* interface_object = dynamic_cast<sc_core::sc_object*>(interface);
    std::cout << "LLM4EDA_PORT " << object->name() << " "
              << (interface_object ? interface_object->name() : "<unbound>") << "\\n";
  }}
  for (auto* child : object->get_child_objects()) dump_object(child);
}}

int sc_main(int, char**) {{
{chr(10).join(declarations)}
  {top_cpp_type} dut("{top}");
{chr(10).join(bindings)}
{reset_write}
  sc_core::sc_start(sc_core::SC_ZERO_TIME);
  dump_object(&dut);
  return 0;
}}
"""


def parse_probe_output(output: str) -> dict[str, Any]:
    modules: set[str] = set()
    ports: dict[str, str] = {}
    for line in output.splitlines():
        if line.startswith("LLM4EDA_MODULE "):
            modules.add(line.split(" ", 1)[1].strip())
        elif line.startswith("LLM4EDA_PORT "):
            fields = line.split(" ", 2)
            if len(fields) == 3:
                ports[fields[1]] = fields[2].strip()
    return {"modules": sorted(modules), "ports": ports}


def compare_runtime_structure(
    contract: dict[str, Any], observed: dict[str, Any]
) -> dict[str, Any]:
    expected_modules = expected_instance_paths(contract)
    actual_modules = set(observed.get("modules", []))
    expected_ports = expected_port_paths(contract)
    raw_ports = observed.get("ports", {})
    actual_port_map = normalize_runtime_ports(contract, raw_ports)
    actual_ports = set(actual_port_map)
    errors: list[str] = []
    if expected_modules != actual_modules:
        errors.append(
            "module path mismatch: "
            f"missing={sorted(expected_modules - actual_modules)}, "
            f"unexpected={sorted(actual_modules - expected_modules)}"
        )
    if expected_ports != actual_ports:
        errors.append(
            "port path mismatch: "
            f"missing={sorted(expected_ports - actual_ports)}, "
            f"unexpected={sorted(actual_ports - expected_ports)}"
        )

    interface_by_port = actual_port_map
    groups: dict[str, list[str]] = {}
    for module in contract.get("modules", []):
        for instance in module.get("instances", []):
            instance_path = str(instance["path"])
            parent_path = instance_path.rsplit(".", 1)[0]
            for binding in instance.get("bindings", []):
                connection = binding.get("connection")
                port = binding.get("port")
                if not connection or not port:
                    errors.append(f"unresolved UHDM binding: {instance_path}.{port}")
                    continue
                group = f"{parent_path}:{connection}"
                path = f"{instance_path}.{port}"
                interface = interface_by_port.get(path)
                if interface is None:
                    continue
                groups.setdefault(group, []).append(str(interface))
    for group, interfaces in groups.items():
        if len(set(interfaces)) != 1:
            errors.append(
                f"SystemC connection split for UHDM net {group}: {sorted(set(interfaces))}"
            )
    reverse: dict[str, set[str]] = {}
    for group, interfaces in groups.items():
        if interfaces:
            reverse.setdefault(interfaces[0], set()).add(group)
    for interface, group_names in reverse.items():
        if len(group_names) > 1:
            errors.append(
                f"different UHDM nets collapsed onto SystemC interface {interface}: "
                f"{sorted(group_names)}"
            )
    return {
        "pass": not errors,
        "expected_modules": sorted(expected_modules),
        "actual_modules": sorted(actual_modules),
        "expected_port_count": len(expected_ports),
        "actual_port_count": len(actual_ports),
        "normalized_ports": actual_port_map,
        "connection_groups": groups,
        "errors": errors,
    }


def normalize_runtime_ports(
    contract: dict[str, Any], ports: dict[str, str]
) -> dict[str, str]:
    """Restore logical names when SystemC auto-registers ports as ``port_N``.

    SystemC preserves member construction order.  The UHDM contract preserves
    declaration order, so this mapping also checks that the generated class did
    not reorder or drop ports.  Explicitly named ports pass through unchanged.
    """

    modules = contract_module_map(contract)
    top = str(contract["top"])
    module_by_path = {top: top}
    for module in contract.get("modules", []):
        for instance in module.get("instances", []):
            module_by_path[str(instance["path"])] = str(instance["module"])
    result: dict[str, str] = {}
    for path, interface in ports.items():
        parent, separator, leaf = path.rpartition(".")
        if not separator or not leaf.startswith("port_"):
            result[path] = interface
            continue
        try:
            index = int(leaf.removeprefix("port_"))
        except ValueError:
            result[path] = interface
            continue
        module_name = module_by_path.get(parent)
        declared = modules.get(module_name or "", {}).get("ports", [])
        if 0 <= index < len(declared):
            result[f"{parent}.{declared[index]['name']}"] = interface
        else:
            result[path] = interface
    return result


def _expand_paths(values: list[str]) -> list[str]:
    return [os.path.expandvars(str(value)) for value in values]


def discover_systemc_flags(config: dict[str, Any]) -> tuple[list[str], list[str]]:
    include_dirs = _expand_paths(config.get("include_dirs", []))
    library_dirs = _expand_paths(config.get("library_dirs", []))
    if include_dirs and library_dirs:
        return include_dirs, library_dirs
    roots: list[Path] = []
    if os.environ.get("SYSTEMC_HOME"):
        roots.append(Path(os.environ["SYSTEMC_HOME"]))
    roots.extend((Path("/opt/homebrew/opt/systemc"), Path("/usr/local"), Path("/usr")))
    for root in roots:
        include = root / "include"
        libraries = [root / "lib", root / "lib64"]
        if (include / "systemc").exists() or (include / "systemc.h").exists():
            usable_libraries = [str(path) for path in libraries if path.is_dir()]
            if usable_libraries:
                return [str(include)], usable_libraries
    raise FileNotFoundError(
        "SystemC headers/libraries not found; set SYSTEMC_HOME or configure runtime_probe paths"
    )


def run_structure_probe(
    contract: dict[str, Any],
    candidate_dir: Path,
    output_dir: Path,
    config: dict[str, Any],
) -> dict[str, Any]:
    candidate_header = str(config.get("candidate_header", "functional_model.hpp"))
    top_cpp_type = str(config.get("top_cpp_type", contract["top"]))
    header_path = candidate_dir / candidate_header
    if not header_path.is_file():
        return {
            "pass": False,
            "status": "blocked",
            "failure_kind": "candidate_header_missing",
            "path": str(header_path),
        }
    output_dir.mkdir(parents=True, exist_ok=True)
    probe_source = output_dir / "structure_probe.cpp"
    probe_binary = output_dir / "structure_probe"
    probe_source.write_text(
        render_structure_probe(contract, candidate_header, top_cpp_type),
        encoding="utf-8",
    )
    try:
        include_dirs, library_dirs = discover_systemc_flags(config)
    except FileNotFoundError as exc:
        return {
            "pass": False,
            "status": "blocked",
            "failure_kind": "systemc_missing",
            "error": str(exc),
            "probe_source": str(probe_source),
        }
    compiler = config.get("compiler") or shutil.which("c++")
    if not compiler:
        return {
            "pass": False,
            "status": "blocked",
            "failure_kind": "cxx_compiler_missing",
        }
    command = [
        str(compiler),
        "-std=c++17",
        *(
            item
            for path in [candidate_dir, *map(Path, include_dirs)]
            for item in ("-I", str(path))
        ),
        str(probe_source),
        *(item for path in library_dirs for item in ("-L", path)),
        *(f"-Wl,-rpath,{path}" for path in library_dirs),
        "-lsystemc",
        "-o",
        str(probe_binary),
    ]
    compile_process = subprocess.run(
        command,
        cwd=str(output_dir),
        capture_output=True,
        text=True,
        timeout=int(config.get("timeout_seconds", 180)),
        check=False,
    )
    compile_report = {
        "command": command,
        "returncode": compile_process.returncode,
        "stdout": compile_process.stdout,
        "stderr": compile_process.stderr,
        "pass": compile_process.returncode == 0 and probe_binary.is_file(),
    }
    if not compile_report["pass"]:
        return {
            "pass": False,
            "status": "failed",
            "failure_kind": "structure_probe_compile",
            "compile": compile_report,
            "probe_source": str(probe_source),
        }
    run_process = subprocess.run(
        [str(probe_binary)],
        cwd=str(output_dir),
        capture_output=True,
        text=True,
        timeout=int(config.get("timeout_seconds", 180)),
        check=False,
    )
    observed = parse_probe_output(run_process.stdout)
    comparison = compare_runtime_structure(contract, observed)
    passed = run_process.returncode == 0 and comparison["pass"]
    return {
        "pass": passed,
        "status": "passed" if passed else "failed",
        "compile": compile_report,
        "run": {
            "command": [str(probe_binary)],
            "returncode": run_process.returncode,
            "stdout": run_process.stdout,
            "stderr": run_process.stderr,
            "pass": run_process.returncode == 0,
        },
        "observed": observed,
        "comparison": comparison,
        "probe_source": str(probe_source),
        "probe_binary": str(probe_binary),
    }
