from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any


class StructureContractError(RuntimeError):
    pass


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise StructureContractError(f"expected JSON object: {path}")
    return value


def stable_digest(value: Any) -> str:
    payload = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _definition_name(name: Any) -> str:
    return str(name or "").split("@", 1)[-1]


def _canonical_instance_path(full_name: Any, fallback: str) -> str:
    value = str(full_name or fallback)
    return value.replace("work@", "")


def _walk_hierarchy(
    node: dict[str, Any],
    parent_path: str | None = None,
    parent_systemc_path: str | None = None,
    depth: int = 0,
):
    module = _definition_name(node.get("definition_name"))
    name = _definition_name(node.get("instance_name"))
    fallback = module if parent_path is None else f"{parent_path}.{name}"
    path = _canonical_instance_path(node.get("full_name"), fallback)
    if parent_path is None and not path:
        path = module
    if parent_path is None:
        local_name = module
        systemc_path = module
    else:
        prefix = f"{parent_path}."
        local_name = path[len(prefix) :] if path.startswith(prefix) else name
        systemc_name = re.sub(r"[^A-Za-z0-9_]", "_", local_name)
        systemc_path = f"{parent_systemc_path}.{systemc_name}"
    yield node, path, parent_path, local_name, systemc_path, depth
    for child in node.get("children", []):
        if isinstance(child, dict):
            yield from _walk_hierarchy(child, path, systemc_path, depth + 1)


def _hierarchy_instances(
    hierarchy: dict[str, Any], width_modules: dict[str, dict[str, Any]]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    designs = hierarchy.get("designs")
    if not isinstance(designs, list) or len(designs) != 1:
        raise StructureContractError("UHDM hierarchy must contain exactly one design")
    roots = designs[0].get("top_modules", [])
    if not isinstance(roots, list) or len(roots) != 1:
        raise StructureContractError("UHDM hierarchy must contain exactly one top")

    graph: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    for node, path, parent_path, local_name, systemc_path, depth in _walk_hierarchy(roots[0]):
        module = _definition_name(node.get("definition_name"))
        if module not in width_modules:
            raise StructureContractError(f"hierarchy references unknown module {module}")
        bindings = []
        for port in node.get("ports", []):
            bindings.append(
                {
                    "port": port.get("name"),
                    "connection": port.get("connection_name") or None,
                    "connection_full_name": port.get("connection_full_name") or None,
                    "connected": bool(port.get("connected")),
                    "source_file": port.get("source_file"),
                    "source_line": port.get("source_line"),
                }
            )
        item = {
            "name": local_name,
            "path": path,
            "systemc_path": systemc_path,
            "parent_path": parent_path,
            "module": module,
            "depth": depth,
            "bindings": bindings,
        }
        graph.append(item)
        if parent_path is not None:
            edges.append(item)
    return graph, edges


def build_uhdm_structure_contract(
    ir: dict[str, Any], hierarchy: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Strip non-structural supplements from a validated UHDM framework IR.

    Widths are retained only as code-generation hints.  They are deliberately
    excluded from the UHDM structural fingerprint because legacy UHDM 1.84
    reported zero width for this design and the old framework used a typed
    supplement.  Module, port, instance and connection facts remain UHDM-owned.
    """

    authority = ir.get("authority")
    if not isinstance(authority, dict) or "UHDM" not in str(
        authority.get("hierarchy", "")
    ):
        raise StructureContractError(
            "structure IR is not marked as an UHDM-owned hierarchy"
        )
    modules = ir.get("modules")
    if not isinstance(modules, list) or not modules:
        raise StructureContractError("structure IR contains no modules")

    structural_modules: list[dict[str, Any]] = []
    type_hints: dict[str, dict[str, int]] = {}
    for module in modules:
        name = str(module.get("code_name") or module.get("name") or "")
        if not name:
            raise StructureContractError("module without code_name")
        ports = []
        hints: dict[str, int] = {}
        for port in module.get("ports", []):
            port_name = str(port.get("name", ""))
            direction = str(port.get("direction", ""))
            if not port_name or direction not in {"input", "output", "inout"}:
                raise StructureContractError(f"invalid port in module {name}")
            ports.append(
                {
                    "name": port_name,
                    "direction": direction,
                    "evidence_id": port.get("evidence_id"),
                    "source_refs": port.get("source_refs", []),
                }
            )
            width = port.get("width_bits")
            if isinstance(width, int) and width > 0:
                hints[port_name] = width
        instances = []
        for instance in module.get("instances", []):
            bindings = []
            for binding in instance.get("bindings", []):
                bindings.append(
                    {
                        "port": binding.get("port"),
                        "connection": binding.get("connection"),
                        "connection_full_name": binding.get("connection_full_name"),
                        "source_location": binding.get("source_location"),
                    }
                )
            instances.append(
                {
                    "name": instance.get("name"),
                    "path": instance.get("path"),
                    "module": instance.get("module"),
                    "evidence_id": instance.get("evidence_id"),
                    "module_evidence_id": instance.get("module_evidence_id"),
                    "source_refs": instance.get("source_refs", []),
                    "bindings": bindings,
                }
            )
        structural_modules.append(
            {
                "name": name,
                "evidence_id": module.get("evidence_id"),
                "source_refs": module.get("source_refs", []),
                "ports": ports,
                "instances": instances,
            }
        )
        type_hints[name] = hints

    width_modules = {item["name"]: item for item in structural_modules}
    instance_graph: list[dict[str, Any]] = []
    instance_edges: list[dict[str, Any]] = []
    if hierarchy is not None:
        instance_graph, instance_edges = _hierarchy_instances(hierarchy, width_modules)

        # Keep one elaborated child layout per module type for code generation.
        # The DSC design has no parameter variant with a different child layout;
        # reject such a case instead of silently choosing one.
        layouts: dict[str, tuple[tuple[str, str], ...]] = {}
        children_by_parent = {
            parent["path"]: [
                child for child in instance_edges if child["parent_path"] == parent["path"]
            ]
            for parent in instance_graph
        }
        for parent in instance_graph:
            children = children_by_parent[parent["path"]]
            layout = tuple((child["name"], child["module"]) for child in children)
            previous = layouts.setdefault(parent["module"], layout)
            if previous != layout:
                raise StructureContractError(
                    f"module {parent['module']} has multiple elaborated child layouts"
                )
            module_contract = width_modules[parent["module"]]
            if not module_contract["instances"] and children:
                module_contract["instances"] = [
                    {
                        "name": child["name"],
                        "path": child["path"],
                        "module": child["module"],
                        "bindings": child["bindings"],
                    }
                    for child in children
                ]

    structural_view = {
        "top": ir.get("top"),
        "modules": structural_modules,
        "instance_graph": instance_graph,
    }
    fingerprint = stable_digest(structural_view)
    return {
        "format": "llm4eda-uhdm-agent-systemc-structure-contract",
        "version": "1.0.0",
        "top": ir.get("top"),
        "authority": {
            "modules_ports_instances": "UHDM canonical graph",
            "connections": "official UHDM Python VPI query",
            "behavior": "original SystemVerilog source supplied to the coding agent",
            "systemc_static_model": "systemc-clang post-generation validation only",
        },
        "source_structure_fingerprint": ir.get("structural_fingerprint"),
        "structural_fingerprint": fingerprint,
        "modules": structural_modules,
        "instance_graph": instance_graph,
        "instance_count": len(instance_graph),
        "binding_count": sum(
            1
            for item in instance_edges
            for binding in item["bindings"]
            if binding.get("connection") or binding.get("connection_full_name")
        ),
        "non_authoritative_type_hints": type_hints,
    }


def contract_module_map(contract: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(module["name"]): module for module in contract.get("modules", [])}


def expected_instance_paths(contract: dict[str, Any]) -> set[str]:
    graph = contract.get("instance_graph", [])
    if graph:
        return {str(item.get("systemc_path") or item["path"]) for item in graph}
    result = {str(contract["top"])}
    for module in contract.get("modules", []):
        for instance in module.get("instances", []):
            path = instance.get("path")
            if path:
                result.add(str(path))
    return result


def expected_port_paths(contract: dict[str, Any]) -> set[str]:
    modules = contract_module_map(contract)
    graph = contract.get("instance_graph", [])
    if graph:
        return {
            f"{instance.get('systemc_path') or instance['path']}.{port['name']}"
            for instance in graph
            for port in modules[str(instance["module"])].get("ports", [])
        }
    result: set[str] = set()
    top = str(contract["top"])
    for port in modules[top].get("ports", []):
        result.add(f"{top}.{port['name']}")
    for parent in contract.get("modules", []):
        for instance in parent.get("instances", []):
            child = modules[str(instance["module"])]
            path = str(instance["path"])
            for port in child.get("ports", []):
                result.add(f"{path}.{port['name']}")
    return result
