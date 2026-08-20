from __future__ import annotations

import csv
from pathlib import Path

from dscflow.workflows.layered_equivalence.plan import build_layer_plan
from dscflow.workflows.layered_equivalence.systemc_skeleton import (
    render_uhdm_systemc_skeleton,
)
from dscflow.workflows.layered_equivalence.trace import compare_traces
from dscflow.workflows.uhdm_systemc.contract import build_uhdm_structure_contract


def _structure() -> dict:
    return {
        "top": "top",
        "authority": {"hierarchy": "UHDM canonical graph"},
        "modules": [
            {
                "name": "top",
                "ports": [
                    {"name": "a", "direction": "input", "width_bits": 8},
                    {"name": "y", "direction": "output", "width_bits": 8},
                ],
            },
            {
                "name": "leaf",
                "ports": [
                    {"name": "a", "direction": "input", "width_bits": 8},
                    {"name": "y", "direction": "output", "width_bits": 8},
                ],
            },
        ],
    }


def _hierarchy() -> dict:
    def port(name: str, direction: str) -> dict:
        return {
            "name": name,
            "direction": direction,
            "connected": True,
            "connection_name": name,
            "connection_full_name": f"work@top.{name}",
        }

    return {
        "designs": [
            {
                "top_modules": [
                    {
                        "instance_name": "work@top",
                        "definition_name": "work@top",
                        "full_name": "",
                        "ports": [port("a", "input"), port("y", "output")],
                        "children": [
                            {
                                "instance_name": "u_leaf",
                                "definition_name": "work@leaf",
                                "full_name": "work@top.u_leaf",
                                "ports": [port("a", "input"), port("y", "output")],
                                "children": [],
                            }
                        ],
                    }
                ]
            }
        ]
    }


def test_contract_and_skeleton_cover_real_instance_graph() -> None:
    contract = build_uhdm_structure_contract(_structure(), _hierarchy())
    assert contract["instance_count"] == 2
    assert contract["binding_count"] == 2
    assert contract["modules"][0]["instances"][0]["module"] == "leaf"
    source = render_uhdm_systemc_skeleton(contract)
    assert "struct top : sc_core::sc_module" in source
    assert 'new leaf("u_leaf")' in source
    assert "u_leaf_instance->a(a);" in source


def test_layer_plan_does_not_count_empty_function_slots_as_implemented() -> None:
    contract = build_uhdm_structure_contract(_structure(), _hierarchy())
    plan = build_layer_plan(
        contract,
        {"implementations": {"top": {"kind": "function", "status": "verified"}}},
    )
    assert plan["depth_summary"][0]["pass"] is True
    assert plan["depth_summary"][1]["missing"] == 1
    assert plan["top_down_complete"] is False


def test_cycle_model_is_not_misreported_as_function_reference() -> None:
    contract = build_uhdm_structure_contract(_structure(), _hierarchy())
    plan = build_layer_plan(
        contract,
        {
            "implementations": {
                "leaf": {"kind": "cycle_systemc", "status": "verified"}
            }
        },
    )

    leaf = next(item for item in plan["instances"] if item["module"] == "leaf")
    assert leaf["implementation_status"] == "verified"
    assert leaf["status"] == "missing_function_reference"
    assert plan["depth_summary"][1]["missing"] == 1


def test_verified_partial_pair_does_not_claim_global_bottom_up_completion() -> None:
    contract = build_uhdm_structure_contract(_structure(), _hierarchy())
    plan = build_layer_plan(
        contract,
        {
            "implementations": {
                "top": {"kind": "function", "status": "verified"},
                "leaf": {"kind": "function", "status": "missing"},
            },
            "semantic_pairs": [{"status": "verified", "scope": "depth_0"}],
        },
    )
    assert plan["declared_semantic_pairs_complete"] is True
    assert plan["top_down_complete"] is False
    assert plan["bottom_up_complete"] is False


def test_trace_comparator_reports_first_cycle_and_field(tmp_path: Path) -> None:
    paths = [tmp_path / "reference.csv", tmp_path / "candidate.csv"]
    for path, values in zip(paths, [["10", "11"], ["10", "12"]], strict=True):
        with path.open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=["cycle", "data"])
            writer.writeheader()
            for cycle, value in enumerate(values):
                writer.writerow({"cycle": cycle, "data": value})
    report = compare_traces(paths[0], paths[1], ["cycle"])
    assert report["pass"] is False
    assert report["first_error"]["row"] == 1
    assert report["first_error"]["fields"]["data"] == {
        "reference": "11",
        "candidate": "12",
    }
