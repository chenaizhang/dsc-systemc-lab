#!/usr/bin/env python3
"""Cross-fill UHDM port widths from CIRCT HW IR port signatures.

UHDM 1.84 does not populate vpiSize for module ports (every port exports as
width 0), so the bit width of each port is recovered from the corresponding
hw.module signature in the CIRCT core IR. UHDM remains the authority for
hierarchy, port names, directions and connections; CIRCT supplies the types.

Usage:
  fill_uhdm_widths.py UHDM_HIERARCHY_JSON CIRCT_CORE_IR OUTPUT_JSON
"""

import hashlib
import json
import pathlib
import re
import sys

# --- CIRCT core IR parsing --------------------------------------------------

_MODULE_RE = re.compile(r"hw\.module(?:\.extern)?(?:\s+private)?\s+@(\w+)")
_ATTRNAME_RE = re.compile(r"hw\.attrname\s*=\s*\"([^\"]+)\"")
_DIR_RE = re.compile(r"(in|out|inout)\s+(%?\w+)\s*:")
_INT_RE = re.compile(r"^i(\d+)$")
_ARRAY_RE = re.compile(r"^(?:!hw\.)?array<(\d+)x(.+)>$")
_STRUCT_RE = re.compile(r"^(?:!hw\.)?struct<(.+)>$")


def compute_width(type_string: str) -> int:
    """Compute the flattened bit width of a CIRCT HW type string."""
    type_string = type_string.strip()
    if match := _INT_RE.match(type_string):
        return int(match.group(1))
    if match := _ARRAY_RE.match(type_string):
        count = int(match.group(1))
        return count * compute_width(match.group(2))
    if match := _STRUCT_RE.match(type_string):
        fields = _split_fields(match.group(1))
        total = 0
        for field in fields:
            _, field_type = _split_field(field)
            total += compute_width(field_type)
        return total
    raise ValueError(f"unsupported CIRCT type: {type_string}")


def _split_fields(fields_string: str):
    """Split a struct field list on top-level commas."""
    fields = []
    depth = 0
    current = []
    for char in fields_string:
        if char in "<(":
            depth += 1
        elif char in ">)":
            depth -= 1
        if char == "," and depth == 0:
            fields.append("".join(current).strip())
            current = []
        else:
            current.append(char)
    if current:
        fields.append("".join(current).strip())
    return fields


def _split_field(field: str):
    """Split 'name: type' at the top-level colon."""
    depth = 0
    for index, char in enumerate(field):
        if char in "<(":
            depth += 1
        elif char in ">)":
            depth -= 1
        elif char == ":" and depth == 0:
            return field[:index].strip(), field[index + 1 :].strip()
    return field.strip(), ""


def _read_type(signature: str, start: int):
    """Read a type string starting at `start`, consuming balanced angle
    brackets, and return (type_string, end_index)."""
    index = start
    depth = 0
    while index < len(signature):
        char = signature[index]
        if char == "<":
            depth += 1
        elif char == ">":
            depth -= 1
        elif char == "," and depth == 0:
            break
        elif char == ")" and depth == 0:
            break
        elif depth == 0 and signature.startswith("loc(", index):
            break
        index += 1
    return signature[start:index].strip(), index


def parse_circt_ports(ir_path):
    """Return {module_name: {port_name: (direction, type_string, width)}}."""
    signatures = {}
    text = pathlib.Path(ir_path).read_text(errors="replace")
    for module_match in _MODULE_RE.finditer(text):
        module_name = module_match.group(1)
        # The signature continues to the first '{' or newline.
        start = module_match.end()
        end = min(text.find("{", start), text.find("\n", start))
        if end < 0:
            continue
        signature = text[start:end]
        ports = {}
        cursor = 0
        while True:
            match = _DIR_RE.search(signature, cursor)
            if not match:
                break
            direction = match.group(1)
            name = match.group(2).lstrip("%")
            type_start = match.end()
            type_string, type_end = _read_type(signature, type_start)
            cursor = type_end
            # An attr list may follow the type; prefer hw.attrname for the
            # canonical port name.
            attr_end = signature.find("}", type_end)
            if attr_end >= 0 and signature[type_end : attr_end].find("{") >= 0:
                attr_text = signature[type_end : attr_end + 1]
                if attr_match := _ATTRNAME_RE.search(attr_text):
                    name = attr_match.group(1)
            try:
                width = compute_width(type_string)
            except ValueError as error:
                print(f"warning: {module_name}.{name}: {error}", file=sys.stderr)
                continue
            ports[name] = (direction, type_string, width)
        if ports:
            signatures[module_name] = ports
    return signatures


# --- UHDM hierarchy merging -------------------------------------------------


def walk_nodes(nodes):
    for node in nodes:
        yield node
        yield from walk_nodes(node.get("children", []))


def definition_key(name: str) -> str:
    """Strip the 'work@' library prefix from UHDM definition names."""
    return name.split("@", 1)[-1]


def main():
    if len(sys.argv) != 4:
        print(
            "usage: fill_uhdm_widths.py UHDM_HIERARCHY_JSON CIRCT_CORE_IR OUTPUT",
            file=sys.stderr,
        )
        return 2

    hierarchy_path = pathlib.Path(sys.argv[1])
    ir_path = pathlib.Path(sys.argv[2])
    output_path = pathlib.Path(sys.argv[3])

    hierarchy = json.loads(hierarchy_path.read_text())
    circt_ports = parse_circt_ports(ir_path)
    ir_hash = hashlib.sha256(pathlib.Path(ir_path).read_bytes()).hexdigest()

    def repo_relative(path: pathlib.Path) -> str:
        try:
            return str(path.resolve().relative_to(pathlib.Path.cwd().resolve()))
        except ValueError:
            return str(path)

    filled = 0
    missing = []
    mismatched = []

    def fill_node(node):
        nonlocal filled
        definition = definition_key(node.get("definition_name", ""))
        circt_table = circt_ports.get(definition, {})
        for port in node.get("ports", []):
            name = port.get("name", "")
            entry = circt_table.get(name)
            if entry is None:
                missing.append((definition, name))
                continue
            direction, type_string, width = entry
            port["hw_type"] = type_string
            port["width_bits"] = width
            port["type_source"] = "circt-hw-ir"
            filled += 1

    designs = hierarchy.get("designs", [])
    for design in designs:
        for node in walk_nodes(design.get("top_modules", [])):
            fill_node(node)

    # Per-definition port signature table (UHDM names/directions/connections
    # are authoritative; types come from CIRCT).
    definitions = {}
    for design in designs:
        for name in design.get("module_definitions", []):
            definitions.setdefault(definition_key(name), name)

    modules = []
    definition_ports = {}
    for design in designs:
        for node in walk_nodes(design.get("top_modules", [])):
            key = definition_key(node.get("definition_name", ""))
            if key not in definition_ports:
                definition_ports[key] = node.get("ports", [])

    for key, definition_name in sorted(definitions.items()):
        ports = []
        for port in definition_ports.get(key, []):
            ports.append(
                {
                    "name": port.get("name"),
                    "direction": port.get("direction"),
                    "hw_type": port.get("hw_type"),
                    "width_bits": port.get("width_bits"),
                }
            )
        modules.append({"name": key, "ports": ports})

    # Connections summary (UHDM vpiHighConn bindings).
    instances = []
    for design in designs:
        instances.extend(walk_nodes(design.get("top_modules", [])))
    child_nodes = instances[1:] if instances else []
    named_bindings = []
    for node in child_nodes:
        for port in node.get("ports", []):
            if port.get("connection_name") or port.get("connection_full_name"):
                named_bindings.append(
                    {
                        "instance": node.get("instance_name"),
                        "definition": definition_key(node.get("definition_name", "")),
                        "port": port.get("name"),
                        "connection_name": port.get("connection_name"),
                        "connection_full_name": port.get("connection_full_name"),
                    }
                )

    total_ports = sum(len(node.get("ports", [])) for node in instances)
    output = {
        "format": "llm4eda-uhdm-dual-framework",
        "version": "2.0.0",
        "top": "dsc_encoder",
        "authority": {
            "hierarchy": "UHDM canonical graph (Surelog elaboration)",
            "connections": "UHDM vpiHighConn",
            "types": "CIRCT HW IR port signatures",
        },
        "provenance": {
            "uhdm_export": repo_relative(hierarchy_path),
            "uhdm_exporter": "tools/export_uhdm_hierarchy.cpp",
            "hw_mlir": repo_relative(ir_path),
            "hw_mlir_sha256": ir_hash,
            "width_filler": "tools/fill_uhdm_widths.py",
        },
        "structural_fingerprint": hashlib.sha256(
            json.dumps(modules, sort_keys=True).encode()
        ).hexdigest(),
        "modules": modules,
        "bindings": named_bindings,
        "gates": {
            "definitions": len(definitions),
            "instances": len(instances),
            "ports": total_ports,
            "widths_filled": filled,
            "widths_missing": len(missing),
            "named_bindings": len(named_bindings),
        },
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(output, indent=1) + "\n")

    print(
        f"UHDM widths filled: definitions={len(definitions)} "
        f"ports={total_ports} filled={filled} missing={len(missing)}"
    )
    if missing:
        for definition, name in missing[:20]:
            print(f"  missing: {definition}.{name}", file=sys.stderr)
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
