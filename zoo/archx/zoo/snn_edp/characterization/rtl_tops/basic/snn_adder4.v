module snn_adder4 (
    input wire i_clk,
    input wire i_rst_n,
    input wire [4-1 : 0] iDataA,
    input wire [4-1 : 0] iDataB,
    output wire [4 : 0] oData
);

    assign oData = iDataA + iDataB;
    
endmodule
