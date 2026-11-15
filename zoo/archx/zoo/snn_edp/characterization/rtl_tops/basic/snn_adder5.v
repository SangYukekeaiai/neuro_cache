module snn_adder5 (
    input wire i_clk,
    input wire i_rst_n,
    input wire [5-1 : 0] iDataA,
    input wire [5-1 : 0] iDataB,
    output wire [5 : 0] oData
);

    assign oData = iDataA + iDataB;
    
endmodule
