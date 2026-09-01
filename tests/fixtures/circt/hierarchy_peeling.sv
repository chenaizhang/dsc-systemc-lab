module hierarchy_leaf (
    input  logic       clk,
    input  logic       reset_n,
    input  logic [7:0] a,
    output logic [7:0] y
);
    logic [7:0] memory [0:3];
    logic [1:0] address;
    always_ff @(posedge clk or negedge reset_n) begin
        if (!reset_n) begin
            address <= '0;
            y <= '0;
        end else begin
            memory[address] <= a;
            y <= memory[address];
            address <= address + 1'b1;
        end
    end
endmodule

module hierarchy_mid (
    input  logic       clk,
    input  logic       reset_n,
    input  logic [7:0] a,
    output logic [7:0] y
);
    hierarchy_leaf leaf(.clk(clk), .reset_n(reset_n), .a(a), .y(y));
endmodule

module hierarchy_top (
    input  logic       clk,
    input  logic       reset_n,
    input  logic [7:0] a,
    output logic [7:0] y
);
    hierarchy_mid mid(.clk(clk), .reset_n(reset_n), .a(a), .y(y));
endmodule
