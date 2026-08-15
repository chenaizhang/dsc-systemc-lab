"""UHDM-backed staged CIRCT/SystemC and Verilator interoperability flow."""

from .evidence import analyze_inputs
from .mlir import analyze_core_ir, classify_circt_failure

__all__ = ["analyze_core_ir", "analyze_inputs", "classify_circt_failure"]
