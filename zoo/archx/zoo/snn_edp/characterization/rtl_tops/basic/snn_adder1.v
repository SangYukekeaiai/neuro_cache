module snn_adder1 (
    input wire i_clk,
    input wire i_rst_n,
    input wire [1-1 : 0] iDataA,
    input wire [1-1 : 0] iDataB,
    output wire [1 : 0] oData
);

    assign oData = iDataA + iDataB;
    
endmodule
