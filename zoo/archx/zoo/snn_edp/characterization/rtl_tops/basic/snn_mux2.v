module snn_mux2     (
    input wire i_clk,
    input wire i_rst_n,input wire iDataA, iDataB, iSel, output wire oData); assign oData = iSel ? iDataB : iDataA; endmodule
