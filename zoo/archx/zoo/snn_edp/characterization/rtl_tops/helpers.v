// Structural helpers; compile as SystemVerilog for the unchanged repo register.
// Datapath operations are primitive instances; arithmetic in generate indices
// and parameter expressions is elaboration-only.
module snn_or_reduce #(parameter WIDTH = 2) (
    input wire [WIDTH-1:0] iData,
    output wire oData
);
    wire [2*WIDTH-2:0] tree;
    genvar i;
    generate
        for (i = 0; i < WIDTH; i = i + 1) begin : g_leaf
            assign tree[WIDTH-1+i] = iData[i];
        end
        for (i = 0; i < WIDTH-1; i = i + 1) begin : g_node
            or_gate u_or (.iDataA(tree[2*i+1]), .iDataB(tree[2*i+2]), .oData(tree[i]));
        end
    endgenerate
    assign oData = tree[0];
endmodule

module snn_mux_word #(parameter WIDTH = 1) (
    input wire [WIDTH-1:0] iDataA, iDataB,
    input wire iSel,
    output wire [WIDTH-1:0] oData
);
    genvar i;
    generate
        for (i = 0; i < WIDTH; i = i + 1) begin : g_bit
            mux2 u_mux (.iDataA(iDataA[i]), .iDataB(iDataB[i]), .iSel(iSel), .oData(oData[i]));
        end
    endgenerate
endmodule

module snn_numeric_compare #(parameter WIDTH = 32, parameter SIGNED_MODE = 0) (
    input wire [WIDTH-1:0] iDataA, iDataB,
    output wire oLt, oEq, oGt, oGe
);
    wire [WIDTH-1:0] inverted_b, different_bits;
    wire [WIDTH:0] sum;
    wire different, unsigned_ge, unsigned_lt;
    genvar i;
    generate
        for (i = 0; i < WIDTH; i = i + 1) begin : g_bit
            not_gate u_not_b (.iData(iDataB[i]), .oData(inverted_b[i]));
            xor_gate u_xor (.iDataA(iDataA[i]), .iDataB(iDataB[i]), .oData(different_bits[i]));
        end
    endgenerate
    // No cin exists: carry(a + ~b) means strictly greater, not greater/equal.
    adder #(.BITWIDTH(WIDTH)) u_subtract_carry (
        .iDataA(iDataA), .iDataB(inverted_b), .oData(sum)
    );
    snn_or_reduce #(.WIDTH(WIDTH)) u_different (.iData(different_bits), .oData(different));
    not_gate u_equal (.iData(different), .oData(oEq));
    or_gate u_unsigned_ge (.iDataA(sum[WIDTH]), .iDataB(oEq), .oData(unsigned_ge));
    not_gate u_unsigned_lt (.iData(unsigned_ge), .oData(unsigned_lt));
    generate
        if (SIGNED_MODE != 0) begin : g_signed
            wire signs_differ, positive_a;
            xor_gate u_signs (.iDataA(iDataA[WIDTH-1]), .iDataB(iDataB[WIDTH-1]), .oData(signs_differ));
            not_gate u_positive (.iData(iDataA[WIDTH-1]), .oData(positive_a));
            mux2 u_lt (.iDataA(unsigned_lt), .iDataB(iDataA[WIDTH-1]), .iSel(signs_differ), .oData(oLt));
            mux2 u_gt (.iDataA(sum[WIDTH]), .iDataB(positive_a), .iSel(signs_differ), .oData(oGt));
            or_gate u_ge (.iDataA(oGt), .iDataB(oEq), .oData(oGe));
        end else begin : g_unsigned
            assign oLt = unsigned_lt;
            assign oGt = sum[WIDTH];
            assign oGe = unsigned_ge;
        end
    endgenerate
endmodule

// WIDTH is 16 or 32; priority is toward the lowest numbered bit.
module snn_priority #(parameter WIDTH = 32, parameter INDEX_WIDTH = $clog2(WIDTH)) (
    input wire [WIDTH-1:0] iData,
    output wire oValid,
    output wire [WIDTH-1:0] oOnehot,
    output wire [INDEX_WIDTH-1:0] oIndex
);
    wire [WIDTH:0] prefix;
    wire [WIDTH-1:0] no_lower;
    assign prefix[0] = 1'b0;
    genvar i, b, j;
    generate
        for (i = 0; i < WIDTH; i = i + 1) begin : g_priority
            if (i == 0) begin : g_first
                assign prefix[i+1] = iData[i];
            end else begin : g_later
                or_gate u_prefix (.iDataA(prefix[i]), .iDataB(iData[i]), .oData(prefix[i+1]));
            end
            not_gate u_not (.iData(prefix[i]), .oData(no_lower[i]));
            and_gate u_select (.iDataA(iData[i]), .iDataB(no_lower[i]), .oData(oOnehot[i]));
        end
        for (b = 0; b < INDEX_WIDTH; b = b + 1) begin : g_index
            wire [WIDTH/2-1:0] terms;
            for (j = 0; j < WIDTH/2; j = j + 1) begin : g_term
                localparam POSITION = (j / (1 << b)) * (1 << (b+1)) + (1 << b) + (j % (1 << b));
                assign terms[j] = oOnehot[POSITION];
            end
            snn_or_reduce #(.WIDTH(WIDTH/2)) u_reduce (.iData(terms), .oData(oIndex[b]));
        end
    endgenerate
    assign oValid = prefix[WIDTH];
endmodule

// Left input wins equal valid keys. Invalid keys are never eligible to win
// over valid keys; if both are invalid the data/index output is unspecified.
module snn_winner #(parameter KEY_WIDTH = 32, parameter INDEX_WIDTH = 2, parameter SELECT_MAX = 0) (
    input wire [KEY_WIDTH-1:0] iKeyA, iKeyB,
    input wire [INDEX_WIDTH-1:0] iIndexA, iIndexB,
    input wire iValidA, iValidB,
    output wire [KEY_WIDTH-1:0] oKey,
    output wire [INDEX_WIDTH-1:0] oIndex,
    output wire oValid
);
    wire lt, gt, better_right, invalid_left, eligible_right, choose_right;
    snn_numeric_compare #(.WIDTH(KEY_WIDTH)) u_compare (
        .iDataA(iKeyA), .iDataB(iKeyB), .oLt(lt), .oEq(), .oGt(gt), .oGe()
    );
    generate
        if (SELECT_MAX != 0) begin : g_max
            assign better_right = lt;
        end else begin : g_min
            assign better_right = gt;
        end
    endgenerate
    not_gate u_invalid_left (.iData(iValidA), .oData(invalid_left));
    or_gate u_eligible_right (.iDataA(invalid_left), .iDataB(better_right), .oData(eligible_right));
    and_gate u_choose_right (.iDataA(iValidB), .iDataB(eligible_right), .oData(choose_right));
    or_gate u_valid (.iDataA(iValidA), .iDataB(iValidB), .oData(oValid));
    snn_mux_word #(.WIDTH(KEY_WIDTH)) u_key (.iDataA(iKeyA), .iDataB(iKeyB), .iSel(choose_right), .oData(oKey));
    snn_mux_word #(.WIDTH(INDEX_WIDTH)) u_index (.iDataA(iIndexA), .iDataB(iIndexB), .iSel(choose_right), .oData(oIndex));
endmodule

// Flat input word0 occupies the least-significant WIDTH bits. ENTRIES=2^A.
module snn_select_word #(parameter WIDTH = 16, parameter ADDRESS_WIDTH = 8) (
    input wire [WIDTH*(1 << ADDRESS_WIDTH)-1:0] iWords,
    input wire [ADDRESS_WIDTH-1:0] iAddress,
    output wire [WIDTH-1:0] oData
);
    localparam ENTRIES = 1 << ADDRESS_WIDTH;
    wire [WIDTH-1:0] stage [0:ADDRESS_WIDTH][0:ENTRIES-1];
    genvar i, level;
    generate
        for (i = 0; i < ENTRIES; i = i + 1) begin : g_word
            assign stage[0][i] = iWords[i*WIDTH +: WIDTH];
        end
        for (level = 0; level < ADDRESS_WIDTH; level = level + 1) begin : g_level
            for (i = 0; i < ENTRIES; i = i + 1) begin : g_select
                if (i < (ENTRIES >> (level+1))) begin : g_live
                    snn_mux_word #(.WIDTH(WIDTH)) u_mux (
                        .iDataA(stage[level][2*i]), .iDataB(stage[level][2*i+1]),
                        .iSel(iAddress[level]), .oData(stage[level+1][i])
                    );
                end else begin : g_unused
                    assign stage[level+1][i] = {WIDTH{1'b0}};
                end
            end
        end
    endgenerate
    assign oData = stage[ADDRESS_WIDTH][0];
endmodule
