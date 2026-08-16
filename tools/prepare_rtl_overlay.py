#!/usr/bin/env python3
"""Create a narrowly scoped simulation overlay without modifying licensed RTL."""

from __future__ import annotations

import argparse
from pathlib import Path

OLD_TRANSFER_LAST = """if (i_rate_word_complete == 1'b1 && i_rate_buffer_empty == 1'b1) begin
                                axi_tvalid_out <= 1'b1;
                                i_data_state <= eDS_TRANSFER_LAST;
                            end // if"""

NEW_TRANSFER_LAST = """if (i_rate_word_complete == 1'b1 && i_rate_buffer_empty == 1'b1) begin
                                // The current ready/valid edge already transferred the final word.
                                // Do not present the same payload for a second transfer.
                                axi_tvalid_out <= 1'b0;
                                i_data_state <= eDS_EMPTY;
                            end // if"""

OLD_FORMAT_DELAY_GATE = """if (i_axi_raddr != i_axi_waddr) begin"""
NEW_FORMAT_DELAY_GATE = """if (i_axi_xmit_okay == 1'b1 && i_axi_raddr != i_axi_waddr) begin"""

FORMAT_COUNTER_DECLARATION = """    logic [15:0]                    i_axi_chunk_bytes;
    logic [15:0]                    i_muxword_bytes;
"""

FORMAT_COUNTER_PROCESS = """
    // Chunk boundaries are defined by PPS.chunk_size, not by a temporary FIFO empty condition.
    always_ff @(posedge axi_clk or negedge axi_reset_n) begin : ChunkTracker
        if (axi_reset_n == 1'b0 || i_axi_start_of_frame == 1'b1) begin
            i_axi_chunk_bytes <= 16'd0;
        end else if (axi_tvalid_out == 1'b1 && axi_tready_out == 1'b1) begin
            if (axi_last_out == 1'b1)
                i_axi_chunk_bytes <= 16'd0;
            else
                i_axi_chunk_bytes <= i_axi_chunk_bytes + i_muxword_bytes;
        end
    end : ChunkTracker

"""

OLD_SLICE_MUX_TRANSFER_LAST = """                    kSST_LAST:  begin
                        axi_tvalid_out <= 1'b1;
                        if (axi_tvalid_out == 1'b1 && axi_tready_out == 1'b1) begin
                            i_slice_state <= kSST_HBLANK;
                        end // if
                    end // kSST_LAST"""

NEW_SLICE_MUX_TRANSFER_LAST = """                    kSST_LAST:  begin
                        // Keep the final muxword stable under backpressure, but retire it on
                        // the first ready/valid edge.  Leaving valid asserted after that edge
                        // transfers the same 48-bit word twice.
                        axi_tvalid_out <= 1'b1;
                        if (axi_tvalid_out == 1'b1 && axi_tready_out == 1'b1) begin
                            axi_tvalid_out <= 1'b0;
                            i_slice_state <= kSST_HBLANK;
                        end // if
                    end // kSST_LAST"""

OLD_MUXWORD_FLUSH_SETTING = "    localparam int kUSE_FLUSH_LOGIC = 0;"
NEW_MUXWORD_FLUSH_SETTING = """    // CBR chunks must flush each component substream at the line boundary.
    localparam int kUSE_FLUSH_LOGIC = 1;"""


def repair_bypass(source: str) -> str:
    count = source.count(OLD_TRANSFER_LAST)
    if count != 1:
        raise ValueError(f"expected one transfer-last pattern, found {count}")
    return source.replace(OLD_TRANSFER_LAST, NEW_TRANSFER_LAST)


def repair_format_buffer(source: str) -> str:
    gate_count = source.count(OLD_FORMAT_DELAY_GATE)
    if gate_count != 1:
        raise ValueError(f"expected one transmit-delay gate, found {gate_count}")
    declaration = "    logic                           i_axi_start_of_frame;\n"
    signal_map = "        axi_muxword_out = i_axi_muxword;\n"
    insertion = "    // ------------------------------------------------------------------------------------------------------------\n    //                                             buffer instance\n"
    if (
        source.count(declaration) != 1
        or source.count(signal_map) != 1
        or source.count(insertion) != 1
    ):
        raise ValueError("format-buffer structural anchor mismatch")
    if source.count("            axi_last_out <= 1'b0;\n") != 2:
        raise ValueError("expected two procedural LAST clears")
    source = source.replace(declaration, declaration + FORMAT_COUNTER_DECLARATION)
    source = source.replace(
        signal_map,
        signal_map
        + "        i_muxword_bytes = (i_bits_per_component < 4'd12) ? 16'd6 : 16'd8;\n"
        + "        axi_last_out = axi_tvalid_out && ((i_axi_chunk_bytes + i_muxword_bytes) >= cfg_pps.chunk_size);\n",
    )
    source = source.replace("            axi_last_out <= 1'b0;\n", "")
    source = source.replace(insertion, FORMAT_COUNTER_PROCESS + insertion)
    return source.replace(OLD_FORMAT_DELAY_GATE, NEW_FORMAT_DELAY_GATE)


def repair_slice_mux(source: str) -> str:
    count = source.count(OLD_SLICE_MUX_TRANSFER_LAST)
    if count != 1:
        raise ValueError(f"expected one slice-mux transfer-last block, found {count}")
    return source.replace(OLD_SLICE_MUX_TRANSFER_LAST, NEW_SLICE_MUX_TRANSFER_LAST)


def enable_muxword_flush(source: str) -> str:
    count = source.count(OLD_MUXWORD_FLUSH_SETTING)
    if count != 1:
        raise ValueError(f"expected one muxword flush setting, found {count}")
    return source.replace(OLD_MUXWORD_FLUSH_SETTING, NEW_MUXWORD_FLUSH_SETTING)


def repair_muxword_last(source: str) -> str:
    anchors = {
        "port": (
            "    output logic                    dsc_muxword_valid_out,  // valid predicted pixels out\n",
            (
                "    output logic                    dsc_muxword_valid_out,  // valid predicted pixels out\n"
                "    output logic                    dsc_muxword_last_out,   // final muxword in this chunk\n"
            ),
        ),
        "decl": (
            "    logic                           i_muxword_staging_valid;\n",
            (
                "    logic                           i_muxword_staging_valid;\n"
                "    logic                           i_muxword_staging_last;\n"
            ),
        ),
        "reset_output": (
            "            dsc_muxword_valid_out <= 1'b0;\n            dsc_muxword_out <= 64'd0;\n",
            (
                "            dsc_muxword_valid_out <= 1'b0;\n"
                "            dsc_muxword_last_out <= 1'b0;\n"
                "            dsc_muxword_out <= 64'd0;\n"
            ),
        ),
        "reset_stage": (
            "            i_muxword_staging_valid <= 1'b0;\n            i_muxword_staging <= 64'd0;\n",
            (
                "            i_muxword_staging_valid <= 1'b0;\n"
                "            i_muxword_staging_last <= 1'b0;\n"
                "            i_muxword_staging <= 64'd0;\n"
            ),
        ),
        "defaults": (
            "            dsc_muxword_valid_out <= 1'b0;\n            i_muxword_staging_valid <= 1'b0;\n",
            (
                "            dsc_muxword_valid_out <= 1'b0;\n"
                "            dsc_muxword_last_out <= 1'b0;\n"
                "            i_muxword_staging_valid <= 1'b0;\n"
                "            i_muxword_staging_last <= 1'b0;\n"
            ),
        ),
        "flush": (
            "                i_muxword_staging <= i_mux_buffer;\n                i_bits_in_word <= 7'd0;\n",
            (
                "                i_muxword_staging <= i_mux_buffer;\n"
                "                i_muxword_staging_last <= 1'b1;\n"
                "                i_bits_in_word <= 7'd0;\n"
            ),
        ),
        "forward": (
            (
                "                    dsc_muxword_valid_out <= 1'b1;\n"
                "                    dsc_muxword_out <= i_muxword_staging;\n"
            ),
            (
                "                    dsc_muxword_valid_out <= 1'b1;\n"
                "                    dsc_muxword_last_out <= i_muxword_staging_last;\n"
                "                    dsc_muxword_out <= i_muxword_staging;\n"
            ),
        ),
    }
    stage_old = (
        "                        i_muxword_staging <= i_output_word;\n"
        "                        i_mux_buffer <= i_remainder_word;\n"
    )
    stage_new = (
        "                        i_muxword_staging <= i_output_word;\n"
        "                        i_muxword_staging_last <= dsc_vlc_last_in &&\n"
        "                            !(i_word_complete && i_bits_in_next_word != i_max_bits_per_word);\n"
        "                        i_mux_buffer <= i_remainder_word;\n"
    )
    if source.count(stage_old) != 2:
        raise ValueError("expected enabled and disabled muxword stage anchors")
    source = source.replace(stage_old, stage_new, 1)
    for name, (old, new) in anchors.items():
        count = source.count(old)
        if count != 1:
            raise ValueError(f"expected one muxword-last {name} anchor, found {count}")
        source = source.replace(old, new)
    return source


def repair_format_last_wiring(source: str) -> str:
    anchors = {
        "declaration": (
            "    logic [2:0]                     i_valid_mw;\n",
            (
                "    logic [2:0]                     i_valid_mw;\n"
                "    logic [2:0]                     i_last_mw;\n"
            ),
        ),
        "muxword_port": (
            (
                "            .dsc_muxword_valid_out  (i_valid_mw[mx]),\n"
                "            .dsc_muxword_out        (i_muxword[mx])\n"
            ),
            (
                "            .dsc_muxword_valid_out  (i_valid_mw[mx]),\n"
                "            .dsc_muxword_last_out   (i_last_mw[mx]),\n"
                "            .dsc_muxword_out        (i_muxword[mx])\n"
            ),
        ),
        "builder_port": (
            "        .dsc_muxword_last_in        (3'b000),\n",
            "        .dsc_muxword_last_in        (i_last_mw),\n",
        ),
    }
    for name, (old, new) in anchors.items():
        count = source.count(old)
        if count != 1:
            raise ValueError(f"expected one format-last {name} anchor, found {count}")
        source = source.replace(old, new)
    return source


def repair_stream_fifo_last(source: str) -> str:
    anchors = {
        "declaration": (
            "    logic [63:0]                    i_muxword_buffer [kMUXWORD_BUFFER_SIZE-1:0];\n",
            (
                "    logic [63:0]                    i_muxword_buffer [kMUXWORD_BUFFER_SIZE-1:0];\n"
                "    logic                           i_muxword_last_buffer [kMUXWORD_BUFFER_SIZE-1:0];\n"
            ),
        ),
        "reset": (
            "            i_muxword_buffer <= '{default: 64'd0};\n",
            (
                "            i_muxword_buffer <= '{default: 64'd0};\n"
                "            i_muxword_last_buffer <= '{default: 1'b0};\n"
            ),
        ),
        "write": (
            "                i_muxword_buffer[i_muxword_write_ptr] <= dsc_muxword_in;\n",
            (
                "                i_muxword_buffer[i_muxword_write_ptr] <= dsc_muxword_in;\n"
                "                i_muxword_last_buffer[i_muxword_write_ptr] <= dsc_muxword_last_in;\n"
            ),
        ),
        "present": (
            (
                "                    dsc_muxword_valid_out <= 1'b1;\n"
                "                    dsc_muxword_out <= i_muxword_buffer[i_muxword_read_ptr];\n"
            ),
            (
                "                    dsc_muxword_valid_out <= 1'b1;\n"
                "                    dsc_muxword_last_out <= i_muxword_last_buffer[i_muxword_read_ptr];\n"
                "                    dsc_muxword_out <= i_muxword_buffer[i_muxword_read_ptr];\n"
            ),
        ),
        "advance": (
            (
                "                    if (i_muxword_read_ptr == i_muxword_write_ptr)  dsc_muxword_valid_out <= 1'b0;\n"
                "                    dsc_muxword_out <= i_muxword_buffer[i_muxword_read_ptr];\n"
            ),
            (
                "                    if (i_muxword_read_ptr == i_muxword_write_ptr) begin\n"
                "                        dsc_muxword_valid_out <= 1'b0;\n"
                "                        dsc_muxword_last_out <= 1'b0;\n"
                "                    end\n"
                "                    dsc_muxword_last_out <= i_muxword_last_buffer[i_muxword_read_ptr];\n"
                "                    dsc_muxword_out <= i_muxword_buffer[i_muxword_read_ptr];\n"
            ),
        ),
    }
    for name, (old, new) in anchors.items():
        count = source.count(old)
        if count != 1:
            raise ValueError(f"expected one stream-fifo-last {name} anchor, found {count}")
        source = source.replace(old, new)
    return source


def repair_stream_builder_last(source: str) -> str:
    source = source.replace(
        "        i_send_muxword[0] = (i_fullness[0] < i_max_syntax_size[0]) ? 1'b1 : 1'b0;\n"
        "        i_send_muxword[1] = (i_fullness[1] < i_max_syntax_size[1]) ? 1'b1 : 1'b0;\n"
        "        i_send_muxword[2] = (i_fullness[2] < i_max_syntax_size[1]) ? 1'b1 : 1'b0;\n",
        "        i_send_muxword[0] = (!i_muxword_chunk_done[0] && i_fullness[0] < i_max_syntax_size[0]);\n"
        "        i_send_muxword[1] = (!i_muxword_chunk_done[1] && i_fullness[1] < i_max_syntax_size[1]);\n"
        "        i_send_muxword[2] = (!i_muxword_chunk_done[2] && i_fullness[2] < i_max_syntax_size[1]);\n",
        1,
    )
    anchors = {
        "declaration": (
            "    logic [2:0]                     i_send_muxword;\n",
            (
                "    logic [2:0]                     i_send_muxword;\n"
                "    logic [2:0]                     i_muxword_chunk_done;\n"
            ),
        ),
        "reset": (
            "            i_muxword_tx_select <= 2'd0;\n\n        end else begin\n",
            (
                "            i_muxword_tx_select <= 2'd0;\n"
                "            i_muxword_chunk_done <= 3'b000;\n\n"
                "        end else begin\n"
            ),
        ),
        "defaults": (
            "            dsc_muxword_valid_out <= 1'b0;\n            i_muxword_ready <= 3'b000;\n",
            (
                "            dsc_muxword_valid_out <= 1'b0;\n"
                "            dsc_muxword_last_out <= 1'b0;\n"
                "            i_muxword_ready <= 3'b000;\n"
            ),
        ),
        "slice_reset": (
            "                i_builder_state <= eBS_INIT;\n                i_muxword_tx_select <= 2'd0;\n",
            (
                "                i_builder_state <= eBS_INIT;\n"
                "                i_muxword_tx_select <= 2'd0;\n"
                "                i_muxword_chunk_done <= 3'b000;\n"
            ),
        ),
        "transfer_case": (
            "                        case (i_muxword_tx_select)\n",
            (
                "                        if (i_muxword_last[i_muxword_tx_select] == 1'b1) begin\n"
                "                            case (i_muxword_tx_select)\n"
                "                                2'd2: i_muxword_chunk_done[2] <= 1'b1;\n"
                "                                2'd1: i_muxword_chunk_done[1] <= 1'b1;\n"
                "                                default: i_muxword_chunk_done[0] <= 1'b1;\n"
                "                            endcase\n"
                "                            if ((i_muxword_chunk_done | (3'b001 << i_muxword_tx_select)) == 3'b111) begin\n"
                "                                dsc_muxword_last_out <= 1'b1;\n"
                "                                i_muxword_chunk_done <= 3'b000;\n"
                "                                i_builder_state <= eBS_INIT;\n"
                "                            end\n"
                "                        end\n\n"
                "                        case (i_muxword_tx_select)\n"
            ),
        ),
    }
    for name, (old, new) in anchors.items():
        count = source.count(old)
        if count != 1:
            raise ValueError(f"expected one stream-builder-last {name} anchor, found {count}")
        source = source.replace(old, new)
    if "i_send_muxword[0] = (!i_muxword_chunk_done[0]" not in source:
        raise ValueError("stream-builder-last send-mask anchor mismatch")
    return source


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--repair",
        choices=(
            "bypass",
            "format-buffer",
            "slice-mux",
            "muxword-flush",
            "muxword-last",
            "format-last-wiring",
            "stream-fifo-last",
            "stream-builder-last",
        ),
        required=True,
    )
    arguments = parser.parse_args()

    source = arguments.input.read_text(encoding="utf-8")
    repairs = {
        "bypass": repair_bypass,
        "format-buffer": repair_format_buffer,
        "slice-mux": repair_slice_mux,
        "muxword-flush": enable_muxword_flush,
        "muxword-last": repair_muxword_last,
        "format-last-wiring": repair_format_last_wiring,
        "stream-fifo-last": repair_stream_fifo_last,
        "stream-builder-last": repair_stream_builder_last,
    }
    repaired = repairs[arguments.repair](source)
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(repaired, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
