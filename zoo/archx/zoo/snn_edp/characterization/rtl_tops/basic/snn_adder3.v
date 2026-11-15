module snn_adder3 (
    input wire i_clk,
    input wire i_rst_n,
    input wire [3-1 : 0] iDataA,
    input wire [3-1 : 0] iDataB,
    output wire [3 : 0] oData
);

    assign oData = iDataA + iDataB;
    
endmodule
