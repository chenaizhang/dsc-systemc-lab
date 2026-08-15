from __future__ import annotations

import hashlib
import json
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


def build_uhdm_structure_contract(ir: dict[str, Any]) -> dict[str, Any]:
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

    structural_view = {
        "top": ir.get("top"),
        "modules": structural_modules,
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
        "non_authoritative_type_hints": type_hints,
    }


def contract_module_map(contract: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(module["name"]): module for module in contract.get("modules", [])}


def expected_instance_paths(contract: dict[str, Any]) -> set[str]:
    result = {str(contract["top"])}
    for module in contract.get("modules", []):
        for instance in module.get("instances", []):
            path = instance.get("path")
            if path:
                result.add(str(path))
    return result


def expected_port_paths(contract: dict[str, Any]) -> set[str]:
    modules = contract_module_map(contract)
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
