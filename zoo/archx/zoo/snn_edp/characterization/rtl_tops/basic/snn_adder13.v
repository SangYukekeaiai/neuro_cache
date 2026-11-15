module snn_adder13 (
    input wire i_clk,
    input wire i_rst_n,
    input wire [13-1 : 0] iDataA,
    input wire [13-1 : 0] iDataB,
    output wire [13 : 0] oData
);

    assign oData = iDataA + iDataB;
    
endmodule
