module snn_or_gate  (
    input wire i_clk,
    input wire i_rst_n,input wire iDataA, iDataB, output wire oData); assign oData = iDataA | iDataB; endmodule
