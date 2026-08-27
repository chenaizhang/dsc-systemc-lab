#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _basename(name: str) -> str:
    return name.rsplit("@", 1)[-1]


def _walk(node: dict):
    yield node
    for child in node.get("children", []):
        yield from _walk(child)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="核对转换顶层及其 UHDM 直接子模块覆盖范围"
    )
    parser.add_argument("--hierarchy", type=Path, required=True)
    parser.add_argument("--top", required=True)
    parser.add_argument("--interop-modules", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    data = json.loads(args.hierarchy.read_text(encoding="utf-8"))
    top_node = None
    module_definitions = {
        _basename(name)
        for design in data.get("designs", [])
        for name in design.get("module_definitions", [])
    }
    for design in data.get("designs", []):
        for root in design.get("top_modules", []):
            for candidate in _walk(root):
                if _basename(candidate.get("definition_name", "")) == args.top:
                    top_node = candidate
                    break
            if top_node:
                break
        if top_node:
            break
    if top_node is None:
        print(f"UHDM 层次中没有顶层 {args.top}", file=sys.stderr)
        return 1

    direct_children = sorted(
        {
            _basename(child.get("definition_name", ""))
            for child in top_node.get("children", [])
            if child.get("definition_name")
        }
    )
    selected = sorted(
        {name.strip() for name in args.interop_modules.split(",") if name.strip()}
    )
    unknown = sorted(set(selected) - module_definitions)
    selected_non_direct = sorted(set(selected) - set(direct_children))
    missing = sorted(set(direct_children) - set(selected))
    report = {
        "conversion_top": args.top,
        "uhdm_direct_child_modules": direct_children,
        "selected_interop_modules": selected,
        "unknown_interop_modules": unknown,
        "selected_non_direct_modules": selected_non_direct,
        "native_direct_child_modules": missing,
        "top_found": True,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    if unknown:
        print(
            f"UHDM 中没有这些 interop 模块定义: {', '.join(unknown)}",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
