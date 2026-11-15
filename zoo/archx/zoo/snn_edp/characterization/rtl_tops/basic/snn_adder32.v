module snn_adder32 (
    input wire i_clk,
    input wire i_rst_n,
    input wire [32-1 : 0] iDataA,
    input wire [32-1 : 0] iDataB,
    output wire [32 : 0] oData
);

    assign oData = iDataA + iDataB;
    
endmodule
