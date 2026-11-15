module snn_adder16 (
    input wire i_clk,
    input wire i_rst_n,
    input wire [16-1 : 0] iDataA,
    input wire [16-1 : 0] iDataB,
    output wire [16 : 0] oData
);

    assign oData = iDataA + iDataB;
    
endmodule
