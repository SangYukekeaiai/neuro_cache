module mux2     (input wire iDataA, iDataB, iSel, output wire oData); assign oData = iSel ? iDataB : iDataA; endmodule
