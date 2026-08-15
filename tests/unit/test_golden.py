from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from dscflow.workflows.golden.runner import (
    _load,
    compare_result_sets,
    status,
)


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def result_set(kind: str, *, golden: bool = False, bitstream: bytes = b"abc") -> dict:
    return {
        "format": "llm4eda-dsc-result-set",
        "version": "1.0.0",
        "producer": {"kind": kind, "name": kind, "golden_qualified": golden},
        "cases": [
            {
                "id": "frame-1",
                "stimulus_sha256": "1" * 64,
                "pps_sha256": "2" * 64,
                "status": "ok",
                "bitstream_hex": bitstream.hex(),
                "bitstream_sha256": digest(bitstream),
            }
        ],
    }


class DscFunctionTlmGateTests(unittest.TestCase):
    def test_software_model_must_match_authoritative_vectors(self) -> None:
        comparison = compare_result_sets(
            result_set("authoritative_vectors"), result_set("software_function"), "software"
        )
        self.assertTrue(comparison["pass"])

    def test_dataflow_cannot_use_unqualified_software_reference(self) -> None:
        comparison = compare_result_sets(
            result_set("software_function"), result_set("dataflow_systemc"), "dataflow"
        )
        self.assertFalse(comparison["pass"])
        self.assertIn("not golden-qualified", comparison["errors"][0])

    def test_bitstream_difference_is_reported(self) -> None:
        comparison = compare_result_sets(
            result_set("software_function", golden=True, bitstream=b"abc"),
            result_set("hybrid_verilator", bitstream=b"abd"),
            "hybrid",
        )
        self.assertFalse(comparison["pass"])
        self.assertEqual("bitstream_sha256", comparison["differences"][0]["field"])

    def test_loader_rejects_bitstream_digest_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "bad.json"
            value = result_set("authoritative_vectors")
            value["cases"][0]["bitstream_sha256"] = "0" * 64
            path.write_text(json.dumps(value), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "does not match"):
                _load(path)

    def test_current_case_is_honestly_blocked_without_vectors(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            case = Path(temporary)
            (case / "datasets").mkdir()
            report = status(case)
            self.assertEqual("blocked_missing_authoritative_vectors", report["status"])
            self.assertFalse(report["golden_ready"])

    def test_verified_vesa_reference_is_reported_without_claiming_company_golden(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            case = Path(temporary)
            (case / "datasets").mkdir()
            evidence = case / "function_tlm" / "x86_reference_differential.json"
            evidence.parent.mkdir()
            evidence.write_text(
                json.dumps(
                    {
                        "format": "llm4eda-dsc-reference-differential",
                        "host_architecture": "x86_64",
                        "pass": True,
                    }
                ),
                encoding="utf-8",
            )
            report = status(case)
            self.assertEqual("vesa_reference_ready_company_vectors_missing", report["status"])
            self.assertTrue(report["vesa_reference_passed_on_x86"])
            self.assertFalse(report["golden_ready"])


if __name__ == "__main__":
    unittest.main()
