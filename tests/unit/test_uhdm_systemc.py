from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from dscflow.workflows.uhdm_systemc.contract import (
    build_uhdm_structure_contract,
)
from dscflow.workflows.uhdm_systemc.prompt_pack import prepare_prompt_pack
from dscflow.workflows.uhdm_systemc.structure_probe import (
    compare_runtime_structure,
    normalize_runtime_ports,
)
from dscflow.workflows.uhdm_systemc.systemc_clang import (
    compare_systemc_clang,
    parse_systemc_clang_output,
)


def sample_ir(width: int = 8) -> dict:
    return {
        "top": "top",
        "authority": {
            "hierarchy": "UHDM canonical graph",
            "connections": "official UHDM Python VPI query",
        },
        "structural_fingerprint": "upstream",
        "modules": [
            {
                "code_name": "leaf",
                "evidence_id": "leaf-evidence",
                "ports": [
                    {"name": "a", "direction": "input", "width_bits": width},
                    {"name": "y", "direction": "output", "width_bits": width},
                ],
                "instances": [],
            },
            {
                "code_name": "top",
                "evidence_id": "top-evidence",
                "ports": [
                    {"name": "a", "direction": "input", "width_bits": width},
                    {"name": "y", "direction": "output", "width_bits": width},
                ],
                "instances": [
                    {
                        "name": "u_leaf",
                        "path": "top.u_leaf",
                        "module": "leaf",
                        "bindings": [
                            {"port": "a", "connection": "a"},
                            {"port": "y", "connection": "y"},
                        ],
                    }
                ],
            },
        ],
    }


class UhdmAgentSystemCTests(unittest.TestCase):
    def test_width_hints_do_not_change_uhdm_structure_fingerprint(self) -> None:
        first = build_uhdm_structure_contract(sample_ir(8))
        second = build_uhdm_structure_contract(sample_ir(16))
        self.assertEqual(
            first["structural_fingerprint"], second["structural_fingerprint"]
        )
        self.assertNotEqual(
            first["non_authoritative_type_hints"],
            second["non_authoritative_type_hints"],
        )

    def test_prompt_pack_contains_complete_sv_and_uhdm_contract(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            rtl = root / "rtl"
            rtl.mkdir()
            sources = {
                "leaf": "module leaf(input logic [7:0] a, output logic [7:0] y); assign y = a; endmodule\n",
                "top": "module top(input logic [7:0] a, output logic [7:0] y); leaf u_leaf(.a(a), .y(y)); endmodule\n",
            }
            entries = []
            for module, text in sources.items():
                path = rtl / f"{module}.sv"
                path.write_text(text, encoding="utf-8")
                entries.append(
                    {
                        "module": module,
                        "path": path.name,
                        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                    }
                )
            (root / "structure.json").write_text(
                json.dumps(sample_ir()), encoding="utf-8"
            )
            config = {
                "schema_version": 1,
                "case": "sample",
                "uhdm": {"structure_ir": "structure.json"},
                "behavior": {"source_root": "rtl", "sources": entries},
            }
            config_path = root / "config.json"
            config_path.write_text(json.dumps(config), encoding="utf-8")
            result = prepare_prompt_pack(config_path, root / "out")

            prompt = (root / "out" / "prompts" / "top.md").read_text()
            self.assertIn(sources["top"].strip(), prompt)
            self.assertIn("UHDM 结构指纹", prompt)
            self.assertTrue(result["generation_policy"]["agent_authored_systemc"])
            self.assertFalse(result["generation_policy"]["circt_translation"])

    def test_runtime_auto_port_names_are_normalized_by_uhdm_order(self) -> None:
        contract = build_uhdm_structure_contract(sample_ir())
        raw = {
            "top.port_0": "sig_a",
            "top.port_1": "sig_y",
            "top.u_leaf.port_0": "sig_a",
            "top.u_leaf.port_1": "sig_y",
        }
        normalized = normalize_runtime_ports(contract, raw)
        self.assertEqual(normalized["top.u_leaf.a"], "sig_a")
        result = compare_runtime_structure(
            contract,
            {"modules": ["top", "top.u_leaf"], "ports": raw},
        )
        self.assertTrue(result["pass"], result["errors"])

    def test_systemc_clang_model_dump_is_compared_with_uhdm(self) -> None:
        output = """Start SCCL
Parsed SystemC model from systemc-clang
Name: leaf
# Port Declaration:
number_of_input_ports: 1
name: a sc_in<sc_bv<8>>
number_of_output_ports: 1
name: y sc_out<sc_bv<8>>
number_of_inout_ports: 0
number_of_processes: 1
leaf_run: SC_CTHREAD leaf_run
 Wait Call: 0x1234
module_name: leaf  instance_name: u_leaf
=======================================================
Name: top
# Port Declaration:
number_of_input_ports: 1
name: a sc_in<sc_bv<8>>
number_of_output_ports: 1
name: y sc_out<sc_bv<8>>
number_of_inout_ports: 0
number_of_processes: 0
module_name: top  instance_name: dut
=======================================================
"""
        observed = parse_systemc_clang_output(output)
        contract = build_uhdm_structure_contract(sample_ir())
        result = compare_systemc_clang(
            contract,
            observed,
            {
                "expected_processes": [
                    {
                        "module": "leaf",
                        "name": "leaf_run",
                        "kind": "SC_CTHREAD",
                        "requires_wait": True,
                    }
                ]
            },
        )
        self.assertTrue(result["pass"], result["errors"])
        leaf = next(item for item in observed["modules"] if item["name"] == "leaf")
        self.assertEqual(leaf["processes"][0]["wait_count"], 1)
        self.assertEqual({item["name"] for item in leaf["ports"]}, {"a", "y"})


if __name__ == "__main__":
    unittest.main()
