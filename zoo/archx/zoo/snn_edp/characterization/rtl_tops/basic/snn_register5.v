module snn_register5 
    (input  logic               i_clk,
    input   logic               i_rst_n,
    input   logic   [5-1:0]    d,
    output  logic   [5-1:0]    q,
    input   logic               wen);

    always_ff @(posedge i_clk) begin
        if (~i_rst_n)
            q <= 'b0;
        else begin
            if (wen)
                q <= d;
        end
    end
endmodule: snn_register5
