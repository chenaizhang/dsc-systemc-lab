from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from ..uhdm_systemc.contract import contract_module_map


def _identifier(value: str) -> str:
    result = re.sub(r"[^A-Za-z0-9_]", "_", value)
    if not result or result[0].isdigit():
        result = f"n_{result}"
    return result


def _type(width: int) -> str:
    return "bool" if width == 1 else f"sc_dt::sc_bv<{width}>"


def _port_type(direction: str, width: int) -> str:
    kind = {"input": "sc_in", "output": "sc_out", "inout": "sc_inout"}[direction]
    return f"sc_core::{kind}<{_type(width)}>"


def _canonical_connection(value: Any) -> str:
    return str(value or "").replace("work@", "")


def _module_order(modules: dict[str, dict[str, Any]]) -> list[str]:
    remaining = set(modules)
    ordered: list[str] = []
    while remaining:
        ready = sorted(
            name
            for name in remaining
            if all(
                str(child["module"]) in ordered
                for child in modules[name].get("instances", [])
            )
        )
        if not ready:
            raise ValueError(f"recursive or unresolved SystemC module graph: {sorted(remaining)}")
        ordered.extend(ready)
        remaining.difference_update(ready)
    return ordered


def render_uhdm_systemc_skeleton(contract: dict[str, Any]) -> str:
    """Render a compilable, behavior-free SystemC hierarchy from UHDM facts.

    The generated source is a structural reference, not a cycle or functional
    implementation.  Every child port is bound to the same parent port or
    internal channel equivalence class reported by UHDM.
    """

    modules = contract_module_map(contract)
    hints = contract.get("non_authoritative_type_hints", {})
    chunks = [
        "#pragma once",
        "",
        "#include <systemc>",
        "#include <functional>",
        "#include <utility>",
        "",
        "struct DscFunctionSlot {",
        "  std::function<void()> function;",
        "  void evaluate_function() { if (function) function(); }",
        "};",
        "",
    ]
    for module_name in _module_order(modules):
        module = modules[module_name]
        widths = hints.get(module_name, {})
        ports = module.get("ports", [])
        port_names = {str(port["name"]) for port in ports}
        declarations = [
            f"  {_port_type(str(port['direction']), int(widths.get(str(port['name']), 1)))} "
            f"{port['name']}{{\"{port['name']}\"}};"
            for port in ports
        ]

        representatives = contract.get("instance_graph", [])
        parent = next(
            (item for item in representatives if item.get("module") == module_name), None
        )
        parent_path = str(parent["path"]) if parent else module_name
        signals: dict[str, tuple[str, int]] = {}
        signal_for_binding: dict[tuple[str, str], str] = {}
        child_declarations: list[str] = []
        constructor_lines: list[str] = []
        destructor_lines: list[str] = []
        evaluation_lines: list[str] = []

        for child in module.get("instances", []):
            child_name = str(child["name"])
            object_name = _identifier(child_name)
            child_type = str(child["module"])
            member = f"{_identifier(child_name)}_instance"
            child_declarations.append(f"  {child_type}* {member} = nullptr;")
            constructor_lines.append(f"    {member} = new {child_type}(\"{object_name}\");")
            destructor_lines.append(f"    delete {member};")
            evaluation_lines.append(f"    {member}->evaluate_hierarchy();")
            child_widths = hints.get(child_type, {})
            for binding in child.get("bindings", []):
                port = str(binding.get("port") or "")
                if not port:
                    continue
                full = _canonical_connection(binding.get("connection_full_name"))
                connection = str(binding.get("connection") or "")
                parent_port = None
                aggregate_adapter = False
                for candidate in port_names:
                    if full == f"{parent_path}.{candidate}" or connection == candidate:
                        parent_width = int(widths.get(candidate, 1))
                        child_width = int(child_widths.get(port, 1))
                        if parent_width == child_width:
                            parent_port = candidate
                        else:
                            aggregate_adapter = True
                        break
                if parent_port:
                    target = parent_port
                else:
                    group = full or connection or f"open:{child_name}.{port}"
                    width = int(child_widths.get(port, 1))
                    storage_group = f"{group}:{child_name}.{port}" if aggregate_adapter else group
                    existing = signals.get(group)
                    if existing and existing[1] != width:
                        # A flattened aggregate port may feed scalar generated
                        # instances.  Keep separate typed adapter channels; the
                        # structural report records that this is not a direct
                        # SystemC interface identity check.
                        storage_group = f"{group}:{child_name}.{port}"
                    signal_name = f"channel_{_identifier(storage_group)}"
                    signals[storage_group] = (signal_name, width)
                    target = signal_name
                signal_for_binding[(child_name, port)] = target
                constructor_lines.append(f"    {member}->{port}({target});")

        signal_declarations = [
            f"  sc_core::sc_signal<{_type(width)}, sc_core::SC_MANY_WRITERS> "
            f"{name}{{\"{name}\"}};"
            for name, width in sorted(signals.values())
        ]
        chunks.extend(
            [
                f"struct {module_name} : sc_core::sc_module, DscFunctionSlot {{",
                *declarations,
                *signal_declarations,
                *child_declarations,
                "",
                f"  explicit {module_name}(sc_core::sc_module_name name) : sc_core::sc_module(name) {{",
                *constructor_lines,
                "  }",
                f"  ~{module_name}() override {{",
                *destructor_lines,
                "  }",
                "  void evaluate_hierarchy() {",
                "    evaluate_function();",
                *evaluation_lines,
                "  }",
                "};",
                "",
            ]
        )
    chunks.append("")
    return "\n".join(chunks)


def write_uhdm_systemc_skeleton(contract: dict[str, Any], output: Path) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render_uhdm_systemc_skeleton(contract), encoding="utf-8")
    return output
