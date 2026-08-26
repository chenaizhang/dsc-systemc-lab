`timescale 1ns/1ps

module cdc_shim_tb;
    logic sync_clk = 1'b0;
    logic reset_n = 1'b0;
    logic async_in = 1'b0;
    logic single_out;
    logic [1:0] double_out;

    gprim_sync_stage single_stage (
        .sync_clk(sync_clk),
        .reset_n(reset_n),
        .async_in(async_in),
        .sync_out(single_out)
    );

    gprim_sync2_stage double_stage (
        .sync_clk(sync_clk),
        .reset_n(reset_n),
        .async_in(async_in),
        .sync_out(double_out)
    );

    always #5 sync_clk = ~sync_clk;

    task automatic expect_outputs(
        input logic expected_single,
        input logic [1:0] expected_double,
        input string phase
    );
        #1;
        if (single_out !== expected_single || double_out !== expected_double) begin
            $error(
                "%s: single=%b expected=%b double=%b expected=%b",
                phase,
                single_out,
                expected_single,
                double_out,
                expected_double
            );
            $fatal(1);
        end
    endtask

    initial begin
        @(posedge sync_clk);
        expect_outputs(1'b0, 2'b00, "reset");

        reset_n = 1'b1;
        async_in = 1'b1;
        @(posedge sync_clk);
        expect_outputs(1'b1, 2'b01, "first sample");
        @(posedge sync_clk);
        expect_outputs(1'b1, 2'b11, "second sample");

        async_in = 1'b0;
        @(posedge sync_clk);
        expect_outputs(1'b0, 2'b10, "falling first sample");
        @(posedge sync_clk);
        expect_outputs(1'b0, 2'b00, "falling second sample");

        $display("CDC_SHIM_TEST=PASS");
        $finish;
    end
endmodule
