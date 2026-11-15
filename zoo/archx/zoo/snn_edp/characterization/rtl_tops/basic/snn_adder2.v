module snn_adder2 (
    input wire i_clk,
    input wire i_rst_n,
    input wire [2-1 : 0] iDataA,
    input wire [2-1 : 0] iDataB,
    output wire [2 : 0] oData
);

    assign oData = iDataA + iDataB;
    
endmodule
