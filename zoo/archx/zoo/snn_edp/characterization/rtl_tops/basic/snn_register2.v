module snn_register2 
    (input  logic               i_clk,
    input   logic               i_rst_n,
    input   logic   [2-1:0]    d,
    output  logic   [2-1:0]    q,
    input   logic               wen);

    always_ff @(posedge i_clk) begin
        if (~i_rst_n)
            q <= 'b0;
        else begin
            if (wen)
                q <= d;
        end
    end
endmodule: snn_register2
