module snn_fifo16x8 (
    input wire i_clk, 
    input wire i_rst_n,
    input wire iEnW, 
    input wire iEnR,
    input wire iClr,
    input wire [16-1:0] iData,
    output reg [16-1:0] oData
);

    reg [3:0] w_ptr; // addition bit to detect oFull/oEmpty condition
    reg [3:0] r_ptr; // addition bit to detect oFull/oEmpty condition
    reg [16-1:0] fifo [8-1:0];
    wire wrap_around;
    wire oFull;
    wire oEmpty;
    
    wire [3-1:0] w_ptr_valid;
    wire [3-1:0] r_ptr_valid;
    wire ptr_valid_identical;
    wire w_valid;
    wire r_valid;

    assign w_ptr_valid = w_ptr[3-1:0];
    assign r_ptr_valid = r_ptr[3-1:0];
    assign w_valid = iEnW & ~oFull;
    assign r_valid = iEnR & ~oEmpty;

    integer i;

    always@(posedge i_clk or negedge i_rst_n) begin
        if(~i_rst_n) begin
            w_ptr <= 0;
        end else begin
            if (iClr) begin
                w_ptr <= 0;
            end else begin
                if(w_valid == 1'b1)begin
                    w_ptr <= w_ptr + 1;
                end
            end
        end
    end

    always@(posedge i_clk or negedge i_rst_n) begin
        if(~i_rst_n) begin
            r_ptr <= 0;
        end else begin
            if (iClr) begin
                r_ptr <= 0;
            end else begin
                if(r_valid)begin
                    r_ptr <= r_ptr + 1;
                end
            end
        end
    end

    // write data to FIFO
    always@(posedge i_clk or negedge i_rst_n) begin
        if(~i_rst_n) begin
            for(i = 0; i < 8; i = i + 1) begin
                fifo[i] <= {16{1'b0}};
            end
        end else begin
            if (iClr) begin
                for(i = 0; i < 8; i = i + 1) begin
                    fifo[i] <= {16{1'b0}};
                end
            end else begin
                if(w_valid)begin
                    fifo[w_ptr_valid] <= iData;
                end
            end
        end
    end

    always@(posedge i_clk or negedge i_rst_n) begin
        if(~i_rst_n) begin
            oData <= {16{1'b0}};
        end else begin
            if (iClr) begin
                oData <= {16{1'b0}};
            end else begin
                if(r_valid)begin
                    oData <= fifo[r_ptr_valid];
                end
            end
        end
    end

    assign wrap_around = w_ptr[3] ^ r_ptr[3]; // To check MSB of write and read pointers are different
    assign ptr_valid_identical = w_ptr_valid == r_ptr_valid;

    //oFull condition: MSB of write and read pointers are different and remainimg bits are same.
    assign oFull = wrap_around & ptr_valid_identical;

    //oEmpty condition: All bits of write and read pointers are same.
    assign oEmpty = ~wrap_around & ptr_valid_identical;

endmodule
