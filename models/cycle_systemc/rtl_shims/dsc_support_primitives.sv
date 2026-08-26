`timescale 1ns/1ps

// Simulation replacements for implementation-specific primitives omitted from
// the delivered reference RTL.  The private source remains untouched; the x86
// verification file list substitutes this file explicitly.

module gprim_sync_stage
(
    input  logic sync_clk,
    input  logic reset_n,
    input  logic async_in,
    output logic sync_out
);
    always_ff @(posedge sync_clk or negedge reset_n) begin
        if (!reset_n)
            sync_out <= 1'b0;
        else
            sync_out <= async_in;
    end
endmodule : gprim_sync_stage


module gprim_sync2_stage
(
    input  logic       sync_clk,
    input  logic       reset_n,
    input  logic       async_in,
    output logic [1:0] sync_out
);
    always_ff @(posedge sync_clk or negedge reset_n) begin
        if (!reset_n)
            sync_out <= 2'b00;
        else
            sync_out <= {sync_out[0], async_in};
    end
endmodule : gprim_sync2_stage


module gram_bist_1r1w
#(
    parameter integer pRW_CHECK = 0,
    parameter integer pADDRESS_BITS,
    parameter integer pDATA_BITS
)
(
    input  logic                     clk_r,
    input  logic                     en_r,
    input  logic [pADDRESS_BITS-1:0] addr_r,
    output logic [pDATA_BITS-1:0]    data_r,
    input  logic                     clk_w,
    input  logic [pADDRESS_BITS-1:0] addr_w,
    input  logic                     we_w,
    input  logic [pDATA_BITS-1:0]    data_w,
    input  logic [11:0]              bist_in,
    output logic [11:0]              bist_out
);
    localparam integer pDEPTH = 1 << pADDRESS_BITS;
    logic [pDATA_BITS-1:0] memory [0:pDEPTH-1];

    // The delivered primitive has no reset port, so its power-up contents are
    // intentionally unspecified.  Avoid an initial loop: CIRCT represents it
    // as a coroutine, which is unrelated to the synchronous 1R1W behavior.
    always @(posedge clk_w) begin
        if (we_w)
            memory[addr_w] <= data_w;
    end

    always @(posedge clk_r) begin
        if (en_r)
            data_r <= memory[addr_r];
    end

    // The omitted proprietary block contains BIST behavior.  Functional DSC
    // regressions do not assert BIST, so expose a deterministic inactive value.
    always_comb begin
        bist_out = 12'h000;
    end

    logic unused;
    always_comb begin
        unused = ^{pRW_CHECK, bist_in};
    end
endmodule : gram_bist_1r1w
