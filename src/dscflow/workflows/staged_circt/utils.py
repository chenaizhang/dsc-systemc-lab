from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"JSON 顶层必须是对象: {path}")
    return value


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def resolve_tool(name: str, explicit: str | None = None) -> Path | None:
    candidates: list[Path] = []
    if explicit:
        candidates.append(Path(os.path.expandvars(explicit)).expanduser())
    environment_name = name.upper().replace("-", "_")
    if configured := os.environ.get(environment_name):
        candidates.append(Path(configured).expanduser())
    if discovered := shutil.which(name):
        candidates.append(Path(discovered))
    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved.is_file() and os.access(resolved, os.X_OK):
            return resolved
    return None


def tool_record(
    path: Path | None,
    version_args: list[str],
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    if path is None:
        return {"available": False, "path": None, "version": []}
    completed = subprocess.run(
        [str(path), *version_args],
        env=env,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
    )
    lines = (completed.stdout + completed.stderr).strip().splitlines()
    return {
        "available": True,
        "path": str(path),
        "sha256": sha256_file(path),
        "version": lines[:12],
        "returncode": completed.returncode,
    }


def run_command(
    name: str,
    argv: list[str],
    *,
    cwd: Path,
    output_dir: Path,
    timeout: int,
    artifact: Path | None = None,
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    try:
        completed = subprocess.run(
            argv,
            cwd=cwd,
            env=env,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            check=False,
            timeout=timeout,
        )
        returncode = completed.returncode
        stdout = completed.stdout
        stderr = completed.stderr
        timed_out = False
    except subprocess.TimeoutExpired as exc:
        returncode = 124
        stdout = exc.stdout or ""
        stderr = exc.stderr or ""
        if isinstance(stdout, bytes):
            stdout = stdout.decode(errors="replace")
        if isinstance(stderr, bytes):
            stderr = stderr.decode(errors="replace")
        stderr += f"\ntimeout after {timeout}s"
        timed_out = True
    stdout_path = output_dir / f"{name}.stdout.log"
    stderr_path = output_dir / f"{name}.stderr.log"
    stdout_path.write_text(stdout, encoding="utf-8")
    stderr_path.write_text(stderr, encoding="utf-8")
    artifact_exists = artifact.is_file() if artifact else None
    passed = returncode == 0 and artifact_exists is not False
    report: dict[str, Any] = {
        "name": name,
        "status": "passed" if passed else ("timeout" if timed_out else "failed"),
        "pass": passed,
        "argv": argv,
        "cwd": str(cwd),
        "returncode": returncode,
        "stdout_log": str(stdout_path.resolve()),
        "stderr_log": str(stderr_path.resolve()),
        "stderr_preview": stderr.strip().splitlines()[:24],
    }
    if artifact is not None:
        report["artifact"] = str(artifact.resolve())
        report["artifact_exists"] = artifact_exists
        if artifact_exists:
            report["artifact_sha256"] = sha256_file(artifact)
            report["artifact_bytes"] = artifact.stat().st_size
    write_json(output_dir / f"{name}.json", report)
    return report


def blocked_stage(name: str, blocked_by: str) -> dict[str, Any]:
    return {
        "name": name,
        "status": "blocked",
        "pass": False,
        "blocked_by": blocked_by,
        "argv": [],
        "returncode": None,
    }
