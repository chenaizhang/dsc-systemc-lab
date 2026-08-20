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


def repair_muxword_flush_dedup(source: str) -> str:
    """Diagnostic line-end experiment retained as negative evidence.

    The x86 trace proved this branch never fires for the current RTL because
    the VLC reports a full word at line end.  Do not treat this overlay as an
    accepted repair; it remains reproducible so the rejected hypothesis cannot
    silently re-enter the flow.
    """
    old_block = (
        "                if (kUSE_FLUSH_LOGIC == 1) begin\n"
        "                    if (i_word_complete == 1'b1 || dsc_vlc_last_in == 1'b1) begin\n"
        "                        i_muxword_staging_valid <= 1'b1;\n"
        "                        i_muxword_staging <= i_output_word;\n"
        "                        i_mux_buffer <= i_remainder_word;\n"
        "                        i_bits_in_word <= (dsc_vlc_last_in == 1'b1) ? 7'd0 : i_bits_in_next_word - i_max_bits_per_word;\n"
        "\n"
        "                        if (i_word_complete == 1'b1 && dsc_vlc_last_in == 1'b1 && i_bits_in_next_word != i_max_bits_per_word) begin\n"
        "                            i_muxword_flush <= 1'b1;\n"
        "                        end // if\n"
        "                    end else begin\n"
    )
    new_block = (
        "                if (kUSE_FLUSH_LOGIC == 1) begin\n"
        "                    if (dsc_vlc_last_in == 1'b1 && i_bits_in_next_word != 7'd0) begin\n"
        "                        // Final word of the line is partial: the accumulated\n"
        "                        // bits never reach a full word, so emit them directly\n"
        "                        // (zero-padded by the 64-bit staging width). Contract:\n"
        "                        // exactly 16 muxwords per line per slice.\n"
        "                        i_muxword_staging_valid <= 1'b1;\n"
        "                        i_muxword_staging <= i_input_word;\n"
        "                        i_muxword_staging_last <= 1'b1;\n"
        "                        i_mux_buffer <= 64'd0;\n"
        "                        i_bits_in_word <= 7'd0;\n"
        "                        i_muxword_flush <= 1'b0;\n"
        "                    end else if (i_word_complete == 1'b1) begin\n"
        "                        i_muxword_staging_valid <= 1'b1;\n"
        "                        i_muxword_staging <= i_output_word;\n"
        "                        i_muxword_staging_last <= dsc_vlc_last_in;\n"
        "                        i_mux_buffer <= i_remainder_word;\n"
        "                        i_bits_in_word <= i_bits_in_next_word - i_max_bits_per_word;\n"
        "                    end else begin\n"
    )
    if source.count(old_block) != 1:
        raise ValueError("expected one muxword flush block, found "
                         + str(source.count(old_block)))
    return source.replace(old_block, new_block)


def repair_muxword_contract(source: str) -> str:
    """Combined contract fix for the muxword: enable the flush, deduplicate
    the double emission at line ends, and add the last output with proper
    staging so the downstream builder sees the line boundaries."""
    # 1) Enable the flush.
    source = enable_muxword_flush(source)
    # 2) Deduplicate: at a partial final word, stage the remainder directly.
    source = repair_muxword_flush_dedup(source)
    # 3) Add the last output port/register and wire the staging/forwarding.
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
    for name, (old, new) in anchors.items():
        count = source.count(old)
        if count != 1:
            raise ValueError("expected one muxword-contract " + name +
                             " anchor, found " + str(count))
        source = source.replace(old, new)
    return source


def repair_fifo_input_ready(source: str) -> str:
    """Add an input-side accept (not-full) output to the stream FIFO so the
    muxword can hold its staged word when the FIFO is full."""
    port_old = (
        "    output logic [63:0]             dsc_muxword_out             // muxword output\n"
        ");\n"
    )
    port_new = (
        "    output logic [63:0]             dsc_muxword_out,            // muxword output\n"
        "    output logic                    dsc_muxword_accept_out      // input-side not-full\n"
        ");\n"
    )
    if source.count(port_old) != 1:
        raise ValueError("expected one fifo port anchor, found " + str(source.count(port_old)))
    source = source.replace(port_old, port_new)
    map_old = (
        "        i_muxword_read = (dsc_muxword_valid_out == 1'b1 && dsc_muxword_ready_out == 1'b1 && i_muxword_write_ptr != i_muxword_read_ptr) ||\n"
    )
    map_new = (
        "        dsc_muxword_accept_out = ~i_muxword_full;\n"
        "\n"
        "        i_muxword_read = (dsc_muxword_valid_out == 1'b1 && dsc_muxword_ready_out == 1'b1 && i_muxword_write_ptr != i_muxword_read_ptr) ||\n"
    )
    if source.count(map_old) != 1:
        raise ValueError("expected one fifo signal-map anchor")
    return source.replace(map_old, map_new)


def repair_muxword_backpressure(source: str) -> str:
    """Add a ready input to the muxword and hold the staged word (and the
    packing state) when the downstream cannot accept it. This restores the
    backpressure path that the delivered RTL deleted."""
    port_old = (
        "    output logic                    dsc_muxword_valid_out,  // valid predicted pixels out\n"
    )
    port_new = (
        "    output logic                    dsc_muxword_valid_out,  // valid predicted pixels out\n"
        "    input  logic                    dsc_muxword_ready_in,   // downstream accept (FIFO not full)\n"
    )
    if source.count(port_old) != 1:
        raise ValueError("expected one muxword valid port anchor")
    source = source.replace(port_old, port_new)
    hold_old = (
        "        end else begin\n"
        "\n"
        "            // --------------------------------------\n"
        "            //  muxword size selection\n"
        "            // --------------------------------------\n"
    )
    hold_new = (
        "        end else begin\n"
        "\n"
        "            if (i_muxword_staging_valid == 1'b1 && dsc_muxword_ready_in == 1'b0) begin\n"
        "                // Backpressure: hold the staged word and stall the\n"
        "                // packing until the downstream accepts it.\n"
        "            end else begin\n"
        "\n"
        "            // --------------------------------------\n"
        "            //  muxword size selection\n"
        "            // --------------------------------------\n"
    )
    if source.count(hold_old) != 1:
        raise ValueError("expected one muxword packing anchor")
    source = source.replace(hold_old, hold_new)
    # Close the added if before the output staging section: the packing block
    # ends right before the "// ----- staging output ----- //" comment.
    close_old = (
        "            end // if\n"
        "\n"
        "            // --------------------------------------\n"
        "            //  output muxwords on a group boundary\n"
        "            // --------------------------------------\n"
    )
    close_new = (
        "            end // if\n"
        "            end // backpressure hold\n"
        "\n"
        "            // --------------------------------------\n"
        "            //  output muxwords on a group boundary\n"
        "            // --------------------------------------\n"
    )
    if source.count(close_old) != 1:
        raise ValueError("expected one muxword close anchor")
    return source.replace(close_old, close_new)


def repair_builder_accept_passthrough(source: str) -> str:
    """Pass the FIFO input-side accept out of the stream builder so the
    format stage can drive the muxword ready inputs. Expects
    repair_fifo_input_ready to have run on dsce_stream_fifo.sv."""
    builder_old = (
        "    output logic [63:0]             dsc_muxword_out                 // muxword output\n"
        ");\n"
    )
    builder_new = (
        "    output logic [63:0]             dsc_muxword_out,                // muxword output\n"
        "    output logic [2:0]              dsc_muxword_accept_out          // input-side not-full per substream\n"
        ");\n"
    )
    if source.count(builder_old) != 1:
        raise ValueError("expected one builder port anchor")
    source = source.replace(builder_old, builder_new)
    fifo_port_old = (
        "            .dsc_muxword_out            (i_muxword[gx])\n"
    )
    fifo_port_new = (
        "            .dsc_muxword_out            (i_muxword[gx]),\n"
        "            .dsc_muxword_accept_out     (dsc_muxword_accept_out[gx])\n"
    )
    if source.count(fifo_port_old) != 1:
        raise ValueError("expected one builder fifo port anchor")
    return source.replace(fifo_port_old, fifo_port_new)


def repair_format_backpressure_wiring(source: str) -> str:
    """Connect the builder accept outputs to the muxword ready inputs in
    dsce_format. Expects repair_builder_accept_passthrough and
    repair_muxword_backpressure to have run."""
    fmt_builder_old = (
        "        .dsc_muxword_out            (i_muxword_sb)\n"
        "    );\n"
    )
    fmt_builder_new = (
        "        .dsc_muxword_out            (i_muxword_sb),\n"
        "        .dsc_muxword_accept_out     (i_muxword_accept)\n"
        "    );\n"
    )
    if source.count(fmt_builder_old) != 1:
        raise ValueError("expected one format builder wiring anchor")
    source = source.replace(fmt_builder_old, fmt_builder_new)
    decl_old = (
        "    logic                           i_muxword_last_sb;\n"
    )
    decl_new = (
        "    logic                           i_muxword_last_sb;\n"
        "    logic [2:0]                     i_muxword_accept;\n"
    )
    if source.count(decl_old) != 1:
        raise ValueError("expected one format last_sb decl anchor")
    source = source.replace(decl_old, decl_new)
    mux_ready_old = (
        "            .dsc_muxword_valid_out  (i_valid_mw[mx]),\n"
    )
    mux_ready_new = (
        "            .dsc_muxword_valid_out  (i_valid_mw[mx]),\n"
        "            .dsc_muxword_ready_in   (i_muxword_accept[mx]),\n"
    )
    if source.count(mux_ready_old) != 1:
        raise ValueError("expected one muxword valid wiring anchor")
    return source.replace(mux_ready_old, mux_ready_new)


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
            "muxword-flush-dedup",
            "fifo-input-ready",
            "muxword-backpressure",
            "muxword-contract",
            "format-backpressure-wiring",
            "builder-accept-passthrough",
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
        "muxword-flush-dedup": repair_muxword_flush_dedup,
        "fifo-input-ready": repair_fifo_input_ready,
        "muxword-backpressure": repair_muxword_backpressure,
        "muxword-contract": repair_muxword_contract,
        "format-backpressure-wiring": repair_format_backpressure_wiring,
        "builder-accept-passthrough": repair_builder_accept_passthrough,
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
