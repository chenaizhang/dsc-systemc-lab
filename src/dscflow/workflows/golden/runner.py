from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any

FORMAT = "llm4eda-dsc-result-set"
STAGE_KINDS = {
    "software": ("authoritative_vectors", "software_function"),
    "dataflow": ("software_function", "dataflow_systemc"),
    "hybrid": ("software_function", "hybrid_verilator"),
    "rtl": ("software_function", "rtl_verilator"),
}


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"result-set root must be an object: {path}")
    if value.get("format") != FORMAT:
        raise ValueError(f"unsupported result-set format: {value.get('format')}")
    producer = value.get("producer")
    if not isinstance(producer, dict) or not isinstance(producer.get("kind"), str):
        raise TypeError(f"result set has no producer.kind: {path}")
    cases = value.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError(f"result set must contain at least one case: {path}")
    seen: set[str] = set()
    for index, case in enumerate(cases):
        if not isinstance(case, dict):
            raise TypeError(f"case {index} is not an object: {path}")
        case_id = case.get("id")
        if not isinstance(case_id, str) or not case_id or case_id in seen:
            raise ValueError(f"case {index} has an invalid or duplicate id: {case_id}")
        seen.add(case_id)
        for key in ("stimulus_sha256", "pps_sha256", "bitstream_sha256"):
            digest = case.get(key)
            if not isinstance(digest, str) or len(digest) != 64:
                raise ValueError(f"{case_id}.{key} must be a SHA-256 digest")
        if not isinstance(case.get("status"), str):
            raise TypeError(f"{case_id}.status must be a string")
        bitstream_hex = case.get("bitstream_hex")
        if bitstream_hex is not None:
            if not isinstance(bitstream_hex, str):
                raise ValueError(f"{case_id}.bitstream_hex must be a string")
            try:
                bitstream = bytes.fromhex(bitstream_hex)
            except ValueError as exc:
                raise ValueError(f"{case_id}.bitstream_hex is invalid") from exc
            if _sha256_bytes(bitstream) != case["bitstream_sha256"]:
                raise ValueError(f"{case_id}.bitstream_sha256 does not match bitstream_hex")
    return value


def compare_result_sets(
    reference: dict[str, Any], candidate: dict[str, Any], stage: str
) -> dict[str, Any]:
    if stage not in STAGE_KINDS:
        raise ValueError(f"unknown stage: {stage}")
    expected_reference, expected_candidate = STAGE_KINDS[stage]
    reference_kind = reference["producer"]["kind"]
    candidate_kind = candidate["producer"]["kind"]
    errors: list[str] = []
    if reference_kind != expected_reference:
        errors.append(
            f"stage {stage} requires reference kind {expected_reference}, got {reference_kind}"
        )
    if candidate_kind != expected_candidate:
        errors.append(
            f"stage {stage} requires candidate kind {expected_candidate}, got {candidate_kind}"
        )
    if stage != "software" and reference["producer"].get("golden_qualified") is not True:
        errors.append("software reference is not golden-qualified by authoritative vectors")

    reference_cases = {item["id"]: item for item in reference["cases"]}
    candidate_cases = {item["id"]: item for item in candidate["cases"]}
    if reference_cases.keys() != candidate_cases.keys():
        errors.append(
            "case IDs differ: "
            f"only_reference={sorted(reference_cases.keys() - candidate_cases.keys())}, "
            f"only_candidate={sorted(candidate_cases.keys() - reference_cases.keys())}"
        )
    differences: list[dict[str, Any]] = []
    fields = ("stimulus_sha256", "pps_sha256", "status", "bitstream_sha256")
    for case_id in sorted(reference_cases.keys() & candidate_cases.keys()):
        for field in fields:
            if reference_cases[case_id][field] != candidate_cases[case_id][field]:
                differences.append(
                    {
                        "id": case_id,
                        "field": field,
                        "reference": reference_cases[case_id][field],
                        "candidate": candidate_cases[case_id][field],
                    }
                )
    return {
        "format": "llm4eda-dsc-stage-comparison",
        "version": "1.0.0",
        "stage": stage,
        "reference_kind": reference_kind,
        "candidate_kind": candidate_kind,
        "case_count": len(reference_cases),
        "errors": errors,
        "differences": differences,
        "pass": not errors and not differences,
    }


def status(case_root: Path) -> dict[str, Any]:
    datasets = case_root / "datasets"
    function_model = case_root / "models" / "function_tlm"
    if not function_model.is_dir():
        function_model = case_root / "function_tlm"
    authoritative = datasets / "authoritative_vectors.results.json"
    software = datasets / "software_function.results.json"
    vesa_differential = function_model / "x86_reference_differential.json"
    if not vesa_differential.is_file():
        vesa_differential = case_root / "evidence" / "results" / "vesa_function_tlm_x86.json"
    vesa_reference_passed = False
    if vesa_differential.is_file():
        value = json.loads(vesa_differential.read_text(encoding="utf-8"))
        vesa_reference_passed = (
            value.get("format") == "llm4eda-dsc-reference-differential"
            and value.get("host_architecture") == "x86_64"
            and value.get("pass") is True
        )
    result: dict[str, Any] = {
        "format": "llm4eda-dsc-function-tlm-status",
        "case_root": str(case_root.resolve()),
        "interface_model": str(function_model.resolve()),
        "authoritative_vectors_present": authoritative.is_file(),
        "software_results_present": software.is_file(),
        "vesa_reference_differential_present": vesa_differential.is_file(),
        "vesa_reference_passed_on_x86": vesa_reference_passed,
        "golden_ready": False,
    }
    if not authoritative.is_file():
        if vesa_reference_passed:
            result["status"] = "vesa_reference_ready_company_vectors_missing"
            result["next_action"] = (
                "provide or confirm company input/PPS/expected-bitstream vectors"
            )
        else:
            result["status"] = "blocked_missing_authoritative_vectors"
            result["next_action"] = (
                "provide licensed/authoritative DSC vectors and their expected bitstreams"
            )
        return result
    if not software.is_file():
        result["status"] = "blocked_missing_software_codec_results"
        result["next_action"] = "connect a DSC software codec and run it on the vectors"
        return result
    comparison = compare_result_sets(_load(authoritative), _load(software), "software")
    result["software_comparison"] = comparison
    result["golden_ready"] = comparison["pass"]
    result["status"] = "golden_ready" if comparison["pass"] else "software_codec_mismatch"
    return result


def _write(path: Path | None, value: dict[str, Any]) -> None:
    payload = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    if path is None:
        print(payload, end="")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(payload, encoding="utf-8")
    print(path)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate DSC software-golden, data-flow SystemC and Verilator stages."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    status_parser = subparsers.add_parser("status")
    status_parser.add_argument("--case", type=Path, required=True)
    status_parser.add_argument("--output", type=Path)
    compare_parser = subparsers.add_parser("compare")
    compare_parser.add_argument("--stage", choices=sorted(STAGE_KINDS), required=True)
    compare_parser.add_argument("--reference", type=Path, required=True)
    compare_parser.add_argument("--candidate", type=Path, required=True)
    compare_parser.add_argument("--output", type=Path)
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    try:
        if args.command == "status":
            result = status(args.case.resolve())
        else:
            result = compare_result_sets(_load(args.reference), _load(args.candidate), args.stage)
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"pass": False, "error": str(exc)}, ensure_ascii=False, indent=2))
        return 2
    _write(args.output, result)
    return 0 if result.get("pass", result.get("golden_ready", False)) else 1


if __name__ == "__main__":
    raise SystemExit(main())
