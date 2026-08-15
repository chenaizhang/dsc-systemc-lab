from __future__ import annotations

import json
import sys
from collections.abc import Callable

from .autoresearch.skill_bootstrap import (
    check_required_skills,
    install_required_skills,
    missing_skill_message,
)
from .workflows.golden.runner import main as golden_main
from .workflows.staged_circt.runner import main as circt_main
from .workflows.uhdm_systemc.runner import main as uhdm_main


def _usage() -> str:
    return """用法：
  dscflow golden <status|compare> ...
  dscflow circt [run] ...
  dscflow uhdm-systemc <prepare|verify|systemc-clang|systemc-clang-install> ...
  dscflow skills [--install]
"""


def _skills(arguments: list[str]) -> int:
    unexpected = [item for item in arguments if item != "--install"]
    if unexpected:
        print(f"未知 skills 参数：{' '.join(unexpected)}", file=sys.stderr)
        return 2
    report = install_required_skills() if "--install" in arguments else check_required_skills()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if report.get("status") != "ready":
        print(missing_skill_message(report), file=sys.stderr)
        return 1
    return 0


def main() -> int:
    if len(sys.argv) < 2 or sys.argv[1] in {"-h", "--help"}:
        print(_usage())
        return 0
    command = sys.argv[1]
    arguments = sys.argv[2:]
    routes: dict[str, Callable[[list[str]], int]] = {
        "golden": lambda args: golden_main(args),
        "circt": lambda args: circt_main(args),
        "uhdm-systemc": lambda args: uhdm_main(args),
        "skills": _skills,
    }
    handler = routes.get(command)
    if handler is None:
        print(f"未知命令：{command}\n\n{_usage()}", file=sys.stderr)
        return 2
    return handler(arguments)
