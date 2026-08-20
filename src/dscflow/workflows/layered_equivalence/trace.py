from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any


def _read_rows(path: Path) -> list[dict[str, str]]:
    if path.suffix == ".jsonl":
        return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    with path.open(newline="", encoding="utf-8") as stream:
        return [dict(row) for row in csv.DictReader(stream)]


def compare_traces(
    reference_path: Path,
    candidate_path: Path,
    keys: list[str],
    ignore: list[str] | None = None,
) -> dict[str, Any]:
    reference = _read_rows(reference_path)
    candidate = _read_rows(candidate_path)
    ignored = set(ignore or [])
    errors: list[dict[str, Any]] = []
    for index, (expected, actual) in enumerate(zip(reference, candidate, strict=False)):
        identity = {key: expected.get(key) for key in keys}
        if any(expected.get(key) != actual.get(key) for key in keys):
            errors.append({"row": index, "kind": "key_mismatch", "reference": identity, "candidate": {key: actual.get(key) for key in keys}})
            break
        fields = sorted((set(expected) | set(actual)) - set(keys) - ignored)
        mismatch = {
            field: {"reference": expected.get(field), "candidate": actual.get(field)}
            for field in fields
            if expected.get(field) != actual.get(field)
        }
        if mismatch:
            errors.append({"row": index, "kind": "value_mismatch", "key": identity, "fields": mismatch})
            break
    if len(reference) != len(candidate):
        errors.append({"kind": "length_mismatch", "reference": len(reference), "candidate": len(candidate)})
    return {
        "pass": not errors,
        "reference": str(reference_path),
        "candidate": str(candidate_path),
        "reference_rows": len(reference),
        "candidate_rows": len(candidate),
        "keys": keys,
        "ignored_fields": sorted(ignored),
        "first_error": errors[0] if errors else None,
    }

