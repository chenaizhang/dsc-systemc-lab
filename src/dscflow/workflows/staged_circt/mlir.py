from __future__ import annotations

import re
from collections import Counter
from typing import Any

OPERATION_RE = re.compile(
    r"(?<![!#])\b((?:hw|comb|seq|llhd|sv|cf|systemc|interop)\.[A-Za-z0-9_.]+)"
)
MODULE_RE = re.compile(
    r"^\s*hw\.module(?P<extern>\.extern)?\s+(?:(?:private|public|nested)\s+)?@(?P<name>[^\s(]+)"
)
INSTANCE_RE = re.compile(r'\bhw\.instance\s+"(?P<instance>[^"]+)"\s+@(?P<module>[^\s(]+)')


def _brace_delta(line: str) -> int:
    stripped = re.sub(r'"(?:\\.|[^"\\])*"', "", line)
    return stripped.count("{") - stripped.count("}")


def _find_matching(text: str, start: int, opening: str, closing: str) -> int:
    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(text)):
        character = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                in_string = False
            continue
        if character == '"':
            in_string = True
        elif character == opening:
            depth += 1
        elif character == closing:
            depth -= 1
            if depth == 0:
                return index
    raise ValueError(f"unbalanced {opening}{closing} starting at {start}")


def _split_top_level(value: str) -> list[str]:
    result: list[str] = []
    start = 0
    round_depth = angle_depth = square_depth = brace_depth = 0
    in_string = False
    escaped = False
    for index, character in enumerate(value):
        if in_string:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                in_string = False
            continue
        if character == '"':
            in_string = True
        elif character == "(":
            round_depth += 1
        elif character == ")":
            round_depth -= 1
        elif character == "<":
            angle_depth += 1
        elif character == ">":
            angle_depth -= 1
        elif character == "[":
            square_depth += 1
        elif character == "]":
            square_depth -= 1
        elif character == "{":
            brace_depth += 1
        elif character == "}":
            brace_depth -= 1
        elif (
            character == ","
            and round_depth == 0
            and angle_depth == 0
            and square_depth == 0
            and brace_depth == 0
        ):
            result.append(value[start:index].strip())
            start = index + 1
    tail = value[start:].strip()
    if tail:
        result.append(tail)
    return result


def _parse_ports(header: str) -> list[dict[str, Any]]:
    opening = header.find("(")
    if opening < 0:
        return []
    closing = _find_matching(header, opening, "(", ")")
    ports: list[dict[str, Any]] = []
    for item in _split_top_level(header[opening + 1 : closing]):
        match = re.match(
            r"^(?P<direction>in|out|inout)\s+%?(?P<name>[A-Za-z_$][A-Za-z0-9_.$]*)\s*:\s*(?P<type>.+)$",
            item,
        )
        if not match:
            continue
        port_type = match.group("type")
        port_type = re.sub(r"\s+loc\([^)]*\)\s*$", "", port_type).strip()
        ports.append(
            {
                "name": match.group("name"),
                "direction": match.group("direction"),
                "type": port_type,
                "aggregate": port_type.startswith(
                    ("!hw.array", "!hw.struct", "!hw.union")
                ),
            }
        )
    return ports


def extract_module_blocks(text: str) -> list[dict[str, Any]]:
    lines = text.splitlines(keepends=True)
    modules: list[dict[str, Any]] = []
    index = 0
    while index < len(lines):
        match = MODULE_RE.match(lines[index])
        if not match:
            index += 1
            continue
        start = index
        header = lines[index].rstrip("\n")
        external = bool(match.group("extern"))
        if external or "{" not in lines[index]:
            end = index
        else:
            depth = 0
            entered = False
            end = index
            while end < len(lines):
                delta = _brace_delta(lines[end])
                if "{" in re.sub(r'"(?:\\.|[^"\\])*"', "", lines[end]):
                    entered = True
                depth += delta
                if entered and depth == 0:
                    break
                end += 1
            if end >= len(lines):
                raise ValueError(f"unterminated hw.module @{match.group('name')}")
        block = "".join(lines[start : end + 1])
        operations = Counter(OPERATION_RE.findall(block))
        instances = [item.groupdict() for item in INSTANCE_RE.finditer(block)]
        modules.append(
            {
                "name": match.group("name"),
                "external": external,
                "start_line": start + 1,
                "end_line": end + 1,
                "ports": _parse_ports(header),
                "instances": instances,
                "operation_counts": dict(sorted(operations.items())),
                "has_comb": any(name.startswith("comb.") for name in operations),
                "has_seq": any(name.startswith("seq.") for name in operations),
                "has_llhd": any(name.startswith("llhd.") for name in operations),
            }
        )
        index = end + 1
    return modules


def analyze_core_ir(text: str, top: str | None = None) -> dict[str, Any]:
    operation_counts = Counter(OPERATION_RE.findall(text))
    modules = extract_module_blocks(text)
    module_names = {module["name"] for module in modules}
    all_instances = [
        {"parent": module["name"], **instance}
        for module in modules
        for instance in module["instances"]
    ]
    unresolved = sorted(
        {
            instance["module"]
            for instance in all_instances
            if instance["module"] not in module_names
        }
    )
    categories = {
        "hw": sum(count for name, count in operation_counts.items() if name.startswith("hw.")),
        "comb": sum(count for name, count in operation_counts.items() if name.startswith("comb.")),
        "seq": sum(count for name, count in operation_counts.items() if name.startswith("seq.")),
        "llhd": sum(count for name, count in operation_counts.items() if name.startswith("llhd.")),
        "cf": sum(count for name, count in operation_counts.items() if name.startswith("cf.")),
    }
    return {
        "format": "llm4eda-circt-core-ir-inventory-v1",
        "top": top,
        "top_found": top in module_names if top else None,
        "module_count": len(modules),
        "module_names": sorted(module_names),
        "instance_operation_count": len(all_instances),
        "instances": all_instances,
        "unresolved_instance_targets": unresolved,
        "operation_counts": dict(sorted(operation_counts.items())),
        "dialect_totals": categories,
        "modules": modules,
        "stage_partitions": {
            "structure_only_modules": [
                item["name"]
                for item in modules
                if not item["has_comb"] and not item["has_seq"] and not item["has_llhd"]
            ],
            "comb_modules": [item["name"] for item in modules if item["has_comb"]],
            "seq_modules": [item["name"] for item in modules if item["has_seq"]],
            "llhd_modules": [item["name"] for item in modules if item["has_llhd"]],
        },
    }


def classify_circt_failure(stderr: str, stage: str) -> dict[str, Any] | None:
    if not stderr.strip():
        return None
    legalize = re.search(r"failed to legalize operation ['\"]([^'\"]+)", stderr)
    unsupported = re.search(r"UNSUPPORTED OPERATION \(([^)]+)\)", stderr)
    undeclared = re.search(r"error: use of undeclared identifier ['\"]([^'\"]+)", stderr)
    emission = re.search(r"no emission pattern found for operation ['\"]?([^'\"\s]+)", stderr)
    if undeclared:
        kind = "frontend_undeclared_identifier"
        operation = None
        symbol = undeclared.group(1)
        owner = "input_rtl_or_frontend"
    elif legalize:
        operation = legalize.group(1)
        symbol = None
        if operation.startswith("llhd."):
            kind = "unsupported_llhd_conversion"
        elif operation.startswith("seq."):
            kind = "unsupported_seq_conversion"
        elif operation.startswith("comb."):
            kind = "unsupported_comb_conversion"
        else:
            kind = "unsupported_conversion_operation"
        owner = "circt_conversion"
    elif emission or unsupported:
        match = emission or unsupported
        operation = match.group(1) if match else None
        symbol = None
        kind = "missing_systemc_emission_pattern"
        owner = "circt_emitter"
    else:
        operation = None
        symbol = None
        kind = "unclassified_tool_failure"
        owner = "needs_analysis"
    return {
        "kind": kind,
        "stage": stage,
        "operation": operation,
        "symbol": symbol,
        "owner": owner,
        "llm_may_change_structure": False,
        "requires_local_reproducer": owner.startswith("circt"),
    }


def build_agent_context(
    evidence: dict[str, Any],
    inventory: dict[str, Any],
    failures: list[dict[str, Any]],
) -> dict[str, Any]:
    candidates: list[dict[str, Any]] = []
    for failure in failures:
        operation = failure.get("operation")
        affected = []
        if operation:
            affected = [
                module["name"]
                for module in inventory["modules"]
                if operation in module["operation_counts"]
            ]
        candidates.append(
            {
                "failure": failure,
                "affected_modules": affected,
                "allowed_actions": [
                    "add a bounded CIRCT conversion/emission pattern",
                    "extract SSA operands/results for an agent-authored local SystemC body",
                    "replace only the affected module with a Verilator-SystemC black box",
                ],
                "forbidden_actions": [
                    "invent module hierarchy or port wiring",
                    "label agent-authored C++ as CIRCT exporter output",
                    "weaken the UHDM/CIRCT structural comparison",
                ],
            }
        )
    return {
        "format": "llm4eda-staged-circt-agent-context-v1",
        "hierarchy_authority": {
            "provided_json_complete": evidence["hierarchy_completeness"]["pass"],
            "provided_json_nodes": evidence["hierarchy_completeness"]["provided_json_nodes"],
            "surelog_instances": evidence["hierarchy_completeness"]["surelog_elaborated_instances"],
        },
        "circt_structure": {
            "modules": inventory["module_names"],
            "instances": inventory["instances"],
        },
        "dialect_partitions": inventory["stage_partitions"],
        "candidates": candidates,
    }
