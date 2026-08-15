from __future__ import annotations

import os
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


EDA_SANDBOX_REPOSITORY = "https://github.com/trv3wood/eda-sandbox.git"
EDA_SANDBOX_BRANCH = "dev"
DEFAULT_REQUIRED_SKILLS = (
    "eda-tool-assistant",
    "modeling-systemc-tlm",
    "modeling-systemverilog",
)


def codex_skills_dir(codex_home: Path | None = None) -> Path:
    if codex_home is not None:
        return codex_home.expanduser().resolve() / "skills"
    configured = os.environ.get("CODEX_HOME")
    root = Path(configured).expanduser() if configured else Path.home() / ".codex"
    return root.resolve() / "skills"


def check_required_skills(
    required: list[str] | tuple[str, ...] | None = None,
    codex_home: Path | None = None,
) -> dict[str, Any]:
    names = tuple(required or DEFAULT_REQUIRED_SKILLS)
    skills_dir = codex_skills_dir(codex_home)
    installed: list[str] = []
    invalid: list[str] = []
    missing: list[str] = []

    for name in names:
        skill_file = skills_dir / name / "SKILL.md"
        if not skill_file.is_file():
            missing.append(name)
            continue
        text = skill_file.read_text(errors="replace")
        if not text.startswith("---\n") or f"name: {name}" not in text.split("---", 2)[1]:
            invalid.append(name)
            continue
        installed.append(name)

    return {
        "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "status": "ready" if not missing and not invalid else "missing",
        "skills_dir": str(skills_dir),
        "required": list(names),
        "installed": installed,
        "missing": missing,
        "invalid": invalid,
        "source": {
            "repository": EDA_SANDBOX_REPOSITORY,
            "branch": EDA_SANDBOX_BRANCH,
        },
    }


def install_required_skills(
    required: list[str] | tuple[str, ...] | None = None,
    codex_home: Path | None = None,
) -> dict[str, Any]:
    names = tuple(required or DEFAULT_REQUIRED_SKILLS)
    before = check_required_skills(names, codex_home)
    if before["status"] == "ready":
        before["install_performed"] = False
        return before

    skills_dir = codex_skills_dir(codex_home)
    skills_dir.mkdir(parents=True, exist_ok=True)
    checkout = skills_dir.parent / "vendor" / "eda-sandbox"
    if not (checkout / ".git").is_dir():
        checkout.parent.mkdir(parents=True, exist_ok=True)
        clone = subprocess.run(
            [
                "git",
                "clone",
                "--depth",
                "1",
                "--branch",
                EDA_SANDBOX_BRANCH,
                EDA_SANDBOX_REPOSITORY,
                str(checkout),
            ],
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
        )
        if clone.returncode != 0:
            raise RuntimeError(f"failed to download eda-sandbox: {clone.stderr.strip()}")
    revision = subprocess.run(
        ["git", "-C", str(checkout), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    ).stdout.strip()

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    for name in names:
        source = checkout / "skills" / name
        destination = skills_dir / name
        if destination.exists() or destination.is_symlink():
            if name not in before.get("invalid", []):
                continue
            backup = destination.with_name(f"{destination.name}.backup.{timestamp}")
            shutil.move(str(destination), str(backup))
        if not (source / "SKILL.md").is_file():
            raise FileNotFoundError(f"upstream skill is missing: {source}")
        destination.symlink_to(source, target_is_directory=True)

    after = check_required_skills(names, codex_home)
    after["install_performed"] = True
    after["revision"] = revision
    after["checkout"] = str(checkout)
    if after["status"] != "ready":
        raise RuntimeError(f"skill installation incomplete: {after}")
    return after


def missing_skill_message(report: dict[str, Any]) -> str:
    missing = ", ".join(report.get("missing", []) + report.get("invalid", []))
    return (
        f"AutoResearch 所需 EDA skill 缺失或无效：{missing}.\n"
        f"下载来源：{EDA_SANDBOX_REPOSITORY}（分支 {EDA_SANDBOX_BRANCH}）。\n"
        "可运行：dscflow skills --install。安装成功后后续流程直接使用，不需要每轮重复安装。"
    )
