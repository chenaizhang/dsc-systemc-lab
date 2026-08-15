from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MODEL = ROOT / "configs" / "model_boundaries.json"
SOURCE = ROOT / "models" / "dataflow_systemc" / "dsc_tlm.hpp"
FUNCTION_SOURCE = ROOT / "models" / "function_tlm" / "include" / "dsc_function_tlm.hpp"


class DscHybridArchitectureTests(unittest.TestCase):
    def setUp(self) -> None:
        self.model = json.loads(MODEL.read_text(encoding="utf-8"))
        self.source = SOURCE.read_text(encoding="utf-8")
        self.function_source = FUNCTION_SOURCE.read_text(encoding="utf-8")

    def test_model_separates_tlm_boundary_from_internal_processes(self) -> None:
        function = self.model["models"]["function_tlm"]
        dataflow = self.model["models"]["dataflow_systemc"]
        self.assertFalse(function["internal_hierarchy"])
        self.assertTrue(function["golden_candidate"])
        self.assertTrue(dataflow["internal_hierarchy"])
        self.assertEqual("placeholder only", dataflow["algorithm"])
        self.assertIn("single transaction-driven module", self.function_source)
        self.assertNotIn("SC_THREAD(", self.function_source)

    def test_systemc_top_exposes_stream_sockets_and_keeps_internal_fifos(self) -> None:
        self.assertIn("tlm::tlm_target_socket<192> pixel_stream_in", self.source)
        self.assertIn("tlm::tlm_initiator_socket<192> bitstream_out", self.source)
        self.assertIn("AxiStreamInputTlmWrapper input_wrapper", self.source)
        self.assertIn("sc_core::sc_fifo<PixelBeat> input_to_frontend", self.source)
        self.assertIn("SC_METHOD(update_irq)", self.source)
        self.assertIn("SC_THREAD(run)", self.source)


if __name__ == "__main__":
    unittest.main()
