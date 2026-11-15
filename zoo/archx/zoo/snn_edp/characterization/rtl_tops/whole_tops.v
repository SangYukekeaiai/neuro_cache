// Thirteen whole-top contracts from MODULE_MAPPING.md / STRUCTURAL_AUDIT.json.
// All array ports are flat: entry0 occupies the least-significant slice.
// Combinational tops have no artificial clock. lif_stateful uses i_clk and
// synchronous active-low i_rst_n through the unchanged repository register.
module cmp32 (
    input wire [31:0] iDataA, iDataB,
    output wire oLt, oEq, oGt, oGe
);
    snn_numeric_compare #(.WIDTH(32), .SIGNED_MODE(1)) u_compare (
        .iDataA(iDataA), .iDataB(iDataB), .oLt(oLt), .oEq(oEq), .oGt(oGt), .oGe(oGe)
    );
endmodule

// Four unsigned timestamps, invalid-lane suppression, stable low-index ties.
module min_tree4 (
    input wire [127:0] iKeys,
    input wire [3:0] iValid,
    output wire [31:0] oKey,
    output wire [1:0] oIndex,
    output wire oValid
);
    wire [31:0] key01, key23;
    wire [1:0] index01, index23;
    wire valid01, valid23;
    snn_winner u_pair01 (.iKeyA(iKeys[31:0]), .iKeyB(iKeys[63:32]),
        .iIndexA(2'd0), .iIndexB(2'd1), .iValidA(iValid[0]), .iValidB(iValid[1]),
        .oKey(key01), .oIndex(index01), .oValid(valid01));
    snn_winner u_pair23 (.iKeyA(iKeys[95:64]), .iKeyB(iKeys[127:96]),
        .iIndexA(2'd2), .iIndexB(2'd3), .iValidA(iValid[2]), .iValidB(iValid[3]),
        .oKey(key23), .oIndex(index23), .oValid(valid23));
    snn_winner u_final (.iKeyA(key01), .iKeyB(key23),
        .iIndexA(index01), .iIndexB(index23), .iValidA(valid01), .iValidB(valid23),
        .oKey(oKey), .oIndex(oIndex), .oValid(oValid));
endmodule

// Input scaling is already folded into weights. iLeakShift2=0/1 selects
// arithmetic state shift1/2; sum truncates to32 before signed >= threshold.
module lif_core (
    input wire [31:0] iState, iThreshold,
    input wire [15:0] iInput,
    input wire iLeakShift2,
    output wire [31:0] oState,
    output wire oSpike
);
    wire [31:0] shifted_state, extended_input;
    wire [32:0] integrated;
    assign extended_input = {{16{iInput[15]}}, iInput};
    snn_mux_word #(.WIDTH(32)) u_leak (
        .iDataA({iState[31], iState[31:1]}),
        .iDataB({{2{iState[31]}}, iState[31:2]}),
        .iSel(iLeakShift2), .oData(shifted_state)
    );
    adder #(.BITWIDTH(32)) u_integrate (.iDataA(shifted_state), .iDataB(extended_input), .oData(integrated));
    snn_numeric_compare #(.WIDTH(32), .SIGNED_MODE(1)) u_threshold (
        .iDataA(integrated[31:0]), .iDataB(iThreshold), .oLt(), .oEq(), .oGt(), .oGe(oSpike)
    );
    snn_mux_word #(.WIDTH(32)) u_hard_reset (
        .iDataA(integrated[31:0]), .iDataB(32'b0), .iSel(oSpike), .oData(oState)
    );
endmodule

module lif_stateful (
    input wire i_clk, i_rst_n, iStep,
    input wire [31:0] iThreshold,
    input wire [15:0] iInput,
    input wire iLeakShift2,
    output wire [31:0] oState,
    output wire oSpike
);
    wire [31:0] next_state;
    wire next_spike;
    lif_core u_core (.iState(oState), .iThreshold(iThreshold), .iInput(iInput),
        .iLeakShift2(iLeakShift2), .oState(next_state), .oSpike(next_spike));
    register #(.WL(32)) u_state (.aclk(i_clk), .rst(i_rst_n), .d(next_state), .q(oState), .wen(iStep));
    register #(.WL(1)) u_spike (.aclk(i_clk), .rst(i_rst_n), .d(next_spike), .q(oSpike), .wen(iStep));
endmodule

module spike_mask_overlap32 (
    input wire [31:0] iDataA, iDataB,
    output wire oDisjoint
);
    wire [31:0] overlap_bits;
    wire overlap;
    genvar i;
    generate
        for (i = 0; i < 32; i = i + 1) begin : g_bit
            and_gate u_and (.iDataA(iDataA[i]), .iDataB(iDataB[i]), .oData(overlap_bits[i]));
        end
    endgenerate
    snn_or_reduce #(.WIDTH(32)) u_overlap (.iData(overlap_bits), .oData(overlap));
    not_gate u_disjoint (.iData(overlap), .oData(oDisjoint));
endmodule

module bsf16 (
    input wire [15:0] iData,
    output wire oValid,
    output wire [3:0] oIndex,
    output wire [15:0] oOnehot, oRemaining
);
    snn_priority #(.WIDTH(16)) u_priority (.iData(iData), .oValid(oValid), .oOnehot(oOnehot), .oIndex(oIndex));
    genvar i;
    generate
        for (i = 0; i < 16; i = i + 1) begin : g_clear
            xor_gate u_clear (.iDataA(iData[i]), .iDataB(oOnehot[i]), .oData(oRemaining[i]));
        end
    endgenerate
endmodule

module bsf32 (
    input wire [31:0] iData,
    output wire oValid,
    output wire [4:0] oIndex,
    output wire [31:0] oOnehot, oRemaining
);
    snn_priority #(.WIDTH(32)) u_priority (.iData(iData), .oValid(oValid), .oOnehot(oOnehot), .oIndex(oIndex));
    genvar i;
    generate
        for (i = 0; i < 32; i = i + 1) begin : g_clear
            xor_gate u_clear (.iDataA(iData[i]), .iDataB(oOnehot[i]), .oData(oRemaining[i]));
        end
    endgenerate
endmodule

module leading_spike_detector32 (
    input wire [31:0] iData,
    output wire oValid,
    output wire [4:0] oIndex,
    output wire [31:0] oOnehot
);
    snn_priority #(.WIDTH(32)) u_priority (.iData(iData), .oValid(oValid), .oOnehot(oOnehot), .oIndex(oIndex));
endmodule

// Inclusive count[i] occupies oInclusive[6*i +:6], exclusive rank[i]
// occupies oExclusive[5*i +:5]; total is inclusive[31].
module spike_prefix_scan32 (
    input wire [31:0] iData,
    output wire [191:0] oInclusive,
    output wire [159:0] oExclusive,
    output wire [5:0] oTotal
);
    wire [5:0] stage [0:5][0:31];
    genvar level, i;
    generate
        for (i = 0; i < 32; i = i + 1) begin : g_input
            assign stage[0][i] = {5'b0, iData[i]};
        end
        for (level = 0; level < 5; level = level + 1) begin : g_level
            for (i = 0; i < 32; i = i + 1) begin : g_position
                if (i >= (1 << level)) begin : g_sum
                    wire [level+1:0] sum;
                    adder #(.BITWIDTH(level+1)) u_adder (
                        .iDataA(stage[level][i][level:0]),
                        .iDataB(stage[level][i-(1 << level)][level:0]), .oData(sum)
                    );
                    assign stage[level+1][i] = {{(4-level){1'b0}}, sum};
                end else begin : g_pass
                    assign stage[level+1][i] = stage[level][i];
                end
            end
        end
        for (i = 0; i < 32; i = i + 1) begin : g_output
            assign oInclusive[6*i +: 6] = stage[5][i];
            if (i == 0) begin : g_first
                assign oExclusive[5*i +: 5] = 5'b0;
            end else begin : g_later
                assign oExclusive[5*i +: 5] = stage[5][i-1][4:0];
            end
        end
    endgenerate
    assign oTotal = stage[5][31];
endmodule

module popcount16 (
    input wire [15:0] iData,
    output wire [4:0] oCount
);
    wire [1:0] pairs [0:7];
    wire [2:0] groups4 [0:3];
    wire [3:0] groups8 [0:1];
    genvar i;
    generate
        for (i = 0; i < 8; i = i + 1) begin : g_pair
            adder #(.BITWIDTH(1)) u_add (.iDataA(iData[2*i]), .iDataB(iData[2*i+1]), .oData(pairs[i]));
        end
        for (i = 0; i < 4; i = i + 1) begin : g_four
            adder #(.BITWIDTH(2)) u_add (.iDataA(pairs[2*i]), .iDataB(pairs[2*i+1]), .oData(groups4[i]));
        end
        for (i = 0; i < 2; i = i + 1) begin : g_eight
            adder #(.BITWIDTH(3)) u_add (.iDataA(groups4[2*i]), .iDataB(groups4[2*i+1]), .oData(groups8[i]));
        end
    endgenerate
    adder #(.BITWIDTH(4)) u_final (.iDataA(groups8[0]), .iDataB(groups8[1]), .oData(oCount));
endmodule

module bitonic_cmp13 (
    input wire [12:0] iKeyA, iKeyB,
    output wire [12:0] oKeyLow, oKeyHigh
);
    wire swap;
    snn_numeric_compare #(.WIDTH(13)) u_compare (
        .iDataA(iKeyA), .iDataB(iKeyB), .oLt(), .oEq(), .oGt(swap), .oGe()
    );
    snn_mux_word #(.WIDTH(13)) u_low (.iDataA(iKeyA), .iDataB(iKeyB), .iSel(swap), .oData(oKeyLow));
    snn_mux_word #(.WIDTH(13)) u_high (.iDataA(iKeyB), .iDataB(iKeyA), .iSel(swap), .oData(oKeyHigh));
endmodule

// Two compact unsigned keys K=(kh*KW+kw)*CIN+cin, one-bit lane and valid
// sidebands. Stable input-A ties; both equal-key records remain in outputs.
module merger_tree2 (
    input wire [31:0] iKeyA, iKeyB,
    input wire iLaneA, iLaneB, iValidA, iValidB,
    output wire [31:0] oKeyA, oKeyB,
    output wire oLaneA, oLaneB, oValidA, oValidB
);
    wire gt, invalid_a, right_preferred, swap;
    snn_numeric_compare #(.WIDTH(32)) u_compare (
        .iDataA(iKeyA), .iDataB(iKeyB), .oLt(), .oEq(), .oGt(gt), .oGe()
    );
    not_gate u_invalid_a (.iData(iValidA), .oData(invalid_a));
    or_gate u_prefer (.iDataA(invalid_a), .iDataB(gt), .oData(right_preferred));
    and_gate u_swap (.iDataA(iValidB), .iDataB(right_preferred), .oData(swap));
    snn_mux_word #(.WIDTH(34)) u_a (
        .iDataA({iValidA, iLaneA, iKeyA}), .iDataB({iValidB, iLaneB, iKeyB}),
        .iSel(swap), .oData({oValidA, oLaneA, oKeyA})
    );
    snn_mux_word #(.WIDTH(34)) u_b (
        .iDataA({iValidB, iLaneB, iKeyB}), .iDataB({iValidA, iLaneA, iKeyA}),
        .iSel(swap), .oData({oValidB, oLaneB, oKeyB})
    );
endmodule

// Match bits are supplied by the separately owned TCAM. iKeys entries are
// {popcount5, original_index8}; iOriginalRows contains ORIGINAL, not residual,
// rows. Non-strict subset matches (including equal rows) remain eligible.
module pruner (
    input wire [15:0] iOriginal,
    input wire [255:0] iSubsetMatch, iProcessedValid,
    input wire [3327:0] iKeys,
    input wire [4095:0] iOriginalRows,
    output wire [15:0] oResidual,
    output wire oValid,
    output wire [7:0] oIndex
);
    wire [12:0] key_tree [0:510];
    wire [7:0] index_tree [0:510];
    wire [510:0] valid_tree;
    wire [15:0] selected_row, residual;
    genvar i;
    generate
        for (i = 0; i < 256; i = i + 1) begin : g_leaf
            localparam [7:0] SLOT = i;
            assign key_tree[255+i] = iKeys[13*i +: 13];
            assign index_tree[255+i] = SLOT;
            and_gate u_eligible (.iDataA(iSubsetMatch[i]), .iDataB(iProcessedValid[i]), .oData(valid_tree[255+i]));
        end
        for (i = 0; i < 255; i = i + 1) begin : g_node
            snn_winner #(.KEY_WIDTH(13), .INDEX_WIDTH(8), .SELECT_MAX(1)) u_winner (
                .iKeyA(key_tree[2*i+1]), .iKeyB(key_tree[2*i+2]),
                .iIndexA(index_tree[2*i+1]), .iIndexB(index_tree[2*i+2]),
                .iValidA(valid_tree[2*i+1]), .iValidB(valid_tree[2*i+2]),
                .oKey(key_tree[i]), .oIndex(index_tree[i]), .oValid(valid_tree[i])
            );
        end
        for (i = 0; i < 16; i = i + 1) begin : g_xor
            xor_gate u_xor (.iDataA(iOriginal[i]), .iDataB(selected_row[i]), .oData(residual[i]));
        end
    endgenerate
    assign oValid = valid_tree[0];
    assign oIndex = index_tree[0];
    snn_select_word #(.WIDTH(16), .ADDRESS_WIDTH(8)) u_original_row (
        .iWords(iOriginalRows), .iAddress(oIndex), .oData(selected_row)
    );
    snn_mux_word #(.WIDTH(16)) u_no_match (
        .iDataA(iOriginal), .iDataB(residual), .iSel(oValid), .oData(oResidual)
    );
endmodule
