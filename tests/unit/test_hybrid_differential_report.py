from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "hybrid_report", ROOT / "tools" / "finalize_hybrid_differential_report.py"
)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_first_difference_reports_content_and_length() -> None:
    assert MODULE.first_difference(b"abc", b"abc") is None
    assert MODULE.first_difference(b"abc", b"axc") == {
        "byte": 1,
        "reference": ord("b"),
        "candidate": ord("x"),
    }
    assert MODULE.first_difference(b"ab", b"abc") == {
        "byte": 2,
        "reference": None,
        "candidate": ord("c"),
        "reason": "length_mismatch",
    }


def test_stream_diagnostics_counts_pair_repetition() -> None:
    payload = b"abcdabcdwxyz"
    assert MODULE.stream_diagnostics(payload, word_bytes=4) == {
        "word_bytes": 4,
        "words": 3,
        "adjacent_duplicate_words": 1,
        "paired_duplicate_words": 1,
    }
