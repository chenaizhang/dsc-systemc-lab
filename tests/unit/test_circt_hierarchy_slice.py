import json
import subprocess
import sys
from pathlib import Path


def test_hierarchy_slice_verifier_accepts_matching_artifacts(tmp_path: Path):
    manifest = {
        "schema": "circt.hw.hierarchy-slice.v1",
        "top": "Top",
        "max_depth": 1,
        "retained_modules": ["Top", "Leaf"],
        "frontier_modules": ["Leaf"],
        "removed_modules": [],
        "modules": [],
        "instances": [
            {
                "parent": "Top",
                "instance": "leaf",
                "target": "Leaf",
                "parent_depth": 0,
                "retained": True,
            }
        ],
    }
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    hw_path = tmp_path / "slice.mlir"
    hw_path.write_text(
        'hw.module @Top() {\n  hw.instance "leaf" @Leaf() -> ()\n}\n'
        'hw.module.extern private @Leaf()\n',
        encoding="utf-8",
    )
    systemc_path = tmp_path / "slice.hpp"
    systemc_path.write_text("SC_MODULE(Leaf) {};\nSC_MODULE(Top) {};\n", encoding="utf-8")
    report_path = tmp_path / "report.json"

    subprocess.run(
        [
            sys.executable,
            "tools/verify_circt_hierarchy_slice.py",
            "--manifest",
            str(manifest_path),
            "--hw-mlir",
            str(hw_path),
            "--systemc",
            str(systemc_path),
            "--report",
            str(report_path),
        ],
        check=True,
    )
    assert json.loads(report_path.read_text(encoding="utf-8"))["status"] == "pass"


def test_hierarchy_slice_verifier_rejects_missing_systemc_module(tmp_path: Path):
    manifest = {
        "schema": "circt.hw.hierarchy-slice.v1",
        "top": "Top",
        "max_depth": 0,
        "retained_modules": ["Top"],
        "frontier_modules": ["Top"],
        "removed_modules": [],
        "modules": [],
        "instances": [],
    }
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    hw_path = tmp_path / "slice.mlir"
    hw_path.write_text("hw.module.extern @Top()\n", encoding="utf-8")
    systemc_path = tmp_path / "slice.hpp"
    systemc_path.write_text("", encoding="utf-8")
    report_path = tmp_path / "report.json"

    result = subprocess.run(
        [
            sys.executable,
            "tools/verify_circt_hierarchy_slice.py",
            "--manifest",
            str(manifest_path),
            "--hw-mlir",
            str(hw_path),
            "--systemc",
            str(systemc_path),
            "--report",
            str(report_path),
        ],
        check=False,
    )
    assert result.returncode == 1
