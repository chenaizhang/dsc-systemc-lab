from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .utils import read_json, sha256_file


def clean_definition(name: str) -> str:
    return name.rsplit("@", 1)[-1]


def _flatten_nodes(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    flattened: list[dict[str, Any]] = []

    def visit(node: dict[str, Any], depth: int) -> None:
        flattened.append(
            {
                "instance_name": node.get("instance_name"),
                "definition_name": node.get("definition_name"),
                "full_name": node.get("full_name"),
                "depth": depth,
            }
        )
        for child in node.get("children", []):
            if isinstance(child, dict):
                visit(child, depth + 1)

    for node in nodes:
        if isinstance(node, dict):
            visit(node, 0)
    return flattened


def parse_filelist(path: Path) -> dict[str, Any]:
    sources: list[str] = []
    include_dirs: list[str] = []
    options: list[str] = []
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith(("//", "#")):
            continue
        if line.startswith("+incdir+"):
            include_dirs.extend(item for item in line[len("+incdir+") :].split("+") if item)
        elif line.startswith(("-", "+")):
            options.append(line)
        else:
            sources.append(line)
    return {
        "path": str(path.resolve()),
        "sha256": sha256_file(path),
        "sources": sources,
        "include_dirs": include_dirs,
        "options": options,
    }


def parse_surelog_summary(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8", errors="replace")

    def number(pattern: str) -> int | None:
        matches = re.findall(pattern, text)
        return int(matches[-1]) if matches else None

    return {
        "path": str(path.resolve()),
        "sha256": sha256_file(path),
        "top_modules": number(r"Nb Top level modules:\s*(\d+)"),
        "max_instance_depth": number(r"Max instance depth:\s*(\d+)"),
        "instances": number(r"Nb instances:\s*(\d+)"),
        "leaf_instances": number(r"Nb leaf instances:\s*(\d+)"),
        "fatal": number(r"\[\s*FATAL\]\s*:\s*(\d+)"),
        "syntax": number(r"\[\s*SYNTAX\]\s*:\s*(\d+)"),
        "errors": number(r"\[\s*ERROR\]\s*:\s*(\d+)"),
        "warnings": number(r"\[WARNING\]\s*:\s*(\d+)"),
    }


def analyze_hierarchy(path: Path) -> dict[str, Any]:
    data = read_json(path)
    designs = data.get("designs")
    if not isinstance(designs, list) or len(designs) != 1 or not isinstance(designs[0], dict):
        raise ValueError("当前流程要求 UHDM hierarchy JSON 恰好包含一个 design")
    design = designs[0]
    definitions = [str(item) for item in design.get("module_definitions", [])]
    nodes = _flatten_nodes(design.get("top_modules", []))
    invocations = design.get("invocations", [])
    instantiated_definitions = sorted(
        {
            clean_definition(str(node["definition_name"]))
            for node in nodes
            if node.get("definition_name")
        }
    )
    return {
        "path": str(path.resolve()),
        "sha256": sha256_file(path),
        "source": data.get("source"),
        "definition_count": len(definitions),
        "definitions": definitions,
        "hierarchy_node_count": len(nodes),
        "invocation_count": len(invocations),
        "maximum_exported_depth": max((int(node["depth"]) for node in nodes), default=0),
        "instantiated_definitions": instantiated_definitions,
        "nodes": nodes,
        "invocations": invocations,
    }


def build_source_plan(
    root: Path,
    filelist: dict[str, Any],
    hierarchy: dict[str, Any],
    exclusions: list[dict[str, Any]],
) -> dict[str, Any]:
    all_sources = list(filelist["sources"])
    instantiated = set(hierarchy["instantiated_definitions"])
    excluded_paths: set[str] = set()
    exclusion_reports: list[dict[str, Any]] = []
    for exclusion in exclusions:
        source = str(exclusion["source"])
        definition = str(exclusion["definition"])
        source_path = root / source
        definition_present = any(
            clean_definition(item) == definition for item in hierarchy["definitions"]
        )
        definition_instantiated = definition in instantiated
        allowed = (
            source in all_sources
            and source_path.is_file()
            and definition_present
            and not definition_instantiated
        )
        exclusion_reports.append(
            {
                "source": source,
                "definition": definition,
                "reason": exclusion.get("reason"),
                "source_exists": source_path.is_file(),
                "definition_present": definition_present,
                "definition_instantiated_in_provided_json": definition_instantiated,
                "exclusion_allowed": allowed,
            }
        )
        if allowed:
            excluded_paths.add(source)
    reachable_sources = [item for item in all_sources if item not in excluded_paths]
    return {
        "all_sources": all_sources,
        "reachable_sources": reachable_sources,
        "excluded_sources": sorted(excluded_paths),
        "exclusions": exclusion_reports,
        "all_sources_exist": all((root / item).is_file() for item in all_sources),
        "all_exclusions_proven": all(item["exclusion_allowed"] for item in exclusion_reports),
    }


def analyze_inputs(root: Path, config: dict[str, Any]) -> dict[str, Any]:
    inputs = config["inputs"]
    filelist_path = root / str(inputs["filelist"])
    hierarchy_path = root / str(inputs["hierarchy_json"])
    surelog_log_path = root / str(inputs["surelog_log"])
    for path in (filelist_path, hierarchy_path, surelog_log_path):
        if not path.is_file():
            raise FileNotFoundError(path)
    filelist = parse_filelist(filelist_path)
    hierarchy = analyze_hierarchy(hierarchy_path)
    surelog = parse_surelog_summary(surelog_log_path)
    source_plan = build_source_plan(
        root,
        filelist,
        hierarchy,
        list(config.get("frontend", {}).get("exclude_uninstantiated_sources", [])),
    )
    expected = config.get("expected", {})
    checks = {
        "source_root_exists": root.is_dir(),
        "all_sources_exist": source_plan["all_sources_exist"],
        "hierarchy_sha256_matches": hierarchy["sha256"]
        == expected.get("hierarchy_sha256", hierarchy["sha256"]),
        "definition_count_matches": hierarchy["definition_count"]
        == int(expected.get("definition_count", hierarchy["definition_count"])),
        "provided_node_count_matches": hierarchy["hierarchy_node_count"]
        == int(expected.get("provided_hierarchy_nodes", hierarchy["hierarchy_node_count"])),
        "surelog_zero_errors": all(
            surelog.get(key) == 0 for key in ("fatal", "syntax", "errors", "warnings")
        ),
        "surelog_instance_count_matches": surelog.get("instances")
        == int(expected.get("surelog_instances", surelog.get("instances") or 0)),
        "exclusions_proven_uninstantiated": source_plan["all_exclusions_proven"],
    }
    hierarchy_complete = hierarchy["hierarchy_node_count"] == surelog.get("instances")
    return {
        "format": "llm4eda-verilog-dsc-input-evidence-v1",
        "source_root": str(root.resolve()),
        "filelist": filelist,
        "hierarchy": hierarchy,
        "surelog": surelog,
        "source_plan": source_plan,
        "hierarchy_completeness": {
            "pass": hierarchy_complete,
            "provided_json_nodes": hierarchy["hierarchy_node_count"],
            "surelog_elaborated_instances": surelog.get("instances"),
            "missing_or_unrepresented_nodes": (
                None
                if surelog.get("instances") is None
                else surelog["instances"] - hierarchy["hierarchy_node_count"]
            ),
            "reason": (
                None
                if hierarchy_complete
                else "provided exporter only recurses vpiModule and omits generate-scope hierarchy"
            ),
        },
        "checks": checks,
        "pass": all(checks.values()),
        "canonical_hierarchy_ready": all(checks.values()) and hierarchy_complete,
    }
