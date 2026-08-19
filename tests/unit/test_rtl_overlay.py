from pathlib import Path

import pytest

from tools.prepare_rtl_overlay import (
    NEW_FORMAT_DELAY_GATE,
    NEW_MUXWORD_FLUSH_SETTING,
    NEW_SLICE_MUX_TRANSFER_LAST,
    NEW_TRANSFER_LAST,
    OLD_MUXWORD_FLUSH_SETTING,
    OLD_SLICE_MUX_TRANSFER_LAST,
    OLD_TRANSFER_LAST,
    enable_muxword_flush,
    repair_bypass,
    repair_format_buffer,
    repair_format_last_wiring,
    repair_muxword_last,
    repair_slice_mux,
    repair_stream_builder_last,
    repair_stream_fifo_last,
)


def test_repair_bypass_replaces_exactly_one_transfer_last_sequence() -> None:
    source = f"prefix\n{OLD_TRANSFER_LAST}\nsuffix\n"
    repaired = repair_bypass(source)
    assert OLD_TRANSFER_LAST not in repaired
    assert repaired == f"prefix\n{NEW_TRANSFER_LAST}\nsuffix\n"


def test_repair_bypass_rejects_missing_or_ambiguous_pattern() -> None:
    for source in ("missing", OLD_TRANSFER_LAST + OLD_TRANSFER_LAST):
        try:
            repair_bypass(source)
        except ValueError:
            pass
        else:
            raise AssertionError("repair must fail closed")


def test_repair_format_buffer_generates_chunk_last_without_changing_ready_valid_state() -> None:
    source = """    logic                           i_axi_start_of_frame;
        axi_muxword_out = i_axi_muxword;
            axi_last_out <= 1'b0;
            axi_last_out <= 1'b0;
if (i_axi_raddr != i_axi_waddr) begin
format transfer state is preserved
    // ------------------------------------------------------------------------------------------------------------
    //                                             buffer instance
"""
    repaired = repair_format_buffer(source)
    assert NEW_FORMAT_DELAY_GATE in repaired
    assert "format transfer state is preserved" in repaired
    assert "axi_last_out = axi_tvalid_out" in repaired
    assert "ChunkTracker" in repaired


def test_repair_slice_mux_retires_last_word_on_first_handshake() -> None:
    source = f"prefix\n{OLD_SLICE_MUX_TRANSFER_LAST}\nsuffix\n"
    repaired = repair_slice_mux(source)
    assert OLD_SLICE_MUX_TRANSFER_LAST not in repaired
    assert repaired == f"prefix\n{NEW_SLICE_MUX_TRANSFER_LAST}\nsuffix\n"


def test_enable_muxword_flush_replaces_compile_time_setting() -> None:
    source = f"prefix\n{OLD_MUXWORD_FLUSH_SETTING}\nsuffix\n"
    repaired = enable_muxword_flush(source)
    assert OLD_MUXWORD_FLUSH_SETTING not in repaired
    assert repaired == f"prefix\n{NEW_MUXWORD_FLUSH_SETTING}\nsuffix\n"


def test_inferred_last_chain_overlays_match_delivered_rtl_anchors() -> None:
    rtl = Path("inputs/private/rtl")
    if not rtl.is_dir():
        pytest.skip("private RTL is not installed")

    muxword = enable_muxword_flush((rtl / "dsce_muxword.sv").read_text(encoding="utf-8"))
    assert "dsc_muxword_last_out" in repair_muxword_last(muxword)
    assert "i_last_mw" in repair_format_last_wiring(
        (rtl / "dsce_format.sv").read_text(encoding="utf-8")
    )
    assert "i_muxword_last_buffer" in repair_stream_fifo_last(
        (rtl / "dsce_stream_fifo.sv").read_text(encoding="utf-8")
    )
    assert "i_muxword_chunk_done" in repair_stream_builder_last(
        (rtl / "dsce_stream_builder.sv").read_text(encoding="utf-8")
    )
from tools.prepare_rtl_overlay import repair_muxword_flush_dedup


def test_flush_dedup_replaces_double_emit_branch() -> None:
    source = """    always_ff @(posedge dsc_clk or negedge dsc_reset_n) begin
                if (kUSE_FLUSH_LOGIC == 1) begin
                    if (i_word_complete == 1'b1 || dsc_vlc_last_in == 1'b1) begin
                        i_muxword_staging_valid <= 1'b1;
                        i_muxword_staging <= i_output_word;
                        i_mux_buffer <= i_remainder_word;
                        i_bits_in_word <= (dsc_vlc_last_in == 1'b1) ? 7'd0 : i_bits_in_next_word - i_max_bits_per_word;

                        if (i_word_complete == 1'b1 && dsc_vlc_last_in == 1'b1 && i_bits_in_next_word != i_max_bits_per_word) begin
                            i_muxword_flush <= 1'b1;
                        end // if
                    end else begin
"""
    repaired = repair_muxword_flush_dedup(source)
    assert "i_muxword_staging <= i_remainder_word;" in repaired
    assert "i_muxword_staging_last <= 1'b1;" in repaired
    # The partial-final-word path no longer asserts the separate flush flag.
    assert repaired.count("i_muxword_flush <= 1'b1;") == 0
