module snn_and_gate (
    input wire i_clk,
    input wire i_rst_n,
    input wire iDataA,
    input wire iDataB,
    output wire oData
);
    assign oData = iDataA & iDataB;
endmodule
