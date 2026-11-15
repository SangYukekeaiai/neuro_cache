module snn_register3 
    (input  logic               i_clk,
    input   logic               i_rst_n,
    input   logic   [3-1:0]    d,
    output  logic   [3-1:0]    q,
    input   logic               wen);

    always_ff @(posedge i_clk) begin
        if (~i_rst_n)
            q <= 'b0;
        else begin
            if (wen)
                q <= d;
        end
    end
endmodule: snn_register3
