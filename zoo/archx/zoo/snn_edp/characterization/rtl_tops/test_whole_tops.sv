`timescale 1ns/1ps
// Independent behavioral references are testbench-only. No DUT arithmetic is
// reused as a reference. Run through test_whole_tops.py with Icarus/Verilator.
module test_whole_tops;
    logic [31:0] a32, b32, mask32;
    logic [15:0] mask16;
    wire cmp_lt, cmp_eq, cmp_gt, cmp_ge, disjoint;
    wire b16_valid, b32_valid, leading_valid;
    wire [3:0] b16_index;
    wire [4:0] b32_index, leading_index, count16;
    wire [15:0] b16_onehot, b16_remaining;
    wire [31:0] b32_onehot, b32_remaining, leading_onehot;
    wire [191:0] inclusive;
    wire [159:0] exclusive;
    wire [5:0] total;
    logic [12:0] key13_a, key13_b;
    wire [12:0] key13_low, key13_high;
    logic [127:0] min_keys;
    logic [3:0] min_valid;
    wire [31:0] min_key;
    wire [1:0] min_index;
    wire min_found;
    logic merge_valid_a, merge_valid_b, merge_lane_a, merge_lane_b;
    wire [31:0] merge_key_a, merge_key_b;
    wire merge_out_valid_a, merge_out_valid_b, merge_out_lane_a, merge_out_lane_b;
    logic [31:0] state_in, threshold;
    logic [15:0] input_value;
    logic shift2, clk, rst_n, step;
    wire [31:0] state_core, state_saved;
    wire spike_core, spike_saved;
    logic [15:0] original;
    logic [255:0] subset_matches, processed;
    logic [3327:0] prune_keys;
    logic [4095:0] original_rows;
    wire [15:0] residual;
    wire prune_valid;
    wire [7:0] prune_index;

    cmp32 u_cmp (.iDataA(a32), .iDataB(b32), .oLt(cmp_lt), .oEq(cmp_eq), .oGt(cmp_gt), .oGe(cmp_ge));
    spike_mask_overlap32 u_overlap (.iDataA(a32), .iDataB(b32), .oDisjoint(disjoint));
    bsf16 u_bsf16 (.iData(mask16), .oValid(b16_valid), .oIndex(b16_index), .oOnehot(b16_onehot), .oRemaining(b16_remaining));
    bsf32 u_bsf32 (.iData(mask32), .oValid(b32_valid), .oIndex(b32_index), .oOnehot(b32_onehot), .oRemaining(b32_remaining));
    leading_spike_detector32 u_leading (.iData(mask32), .oValid(leading_valid), .oIndex(leading_index), .oOnehot(leading_onehot));
    popcount16 u_popcount (.iData(mask16), .oCount(count16));
    spike_prefix_scan32 u_prefix (.iData(mask32), .oInclusive(inclusive), .oExclusive(exclusive), .oTotal(total));
    bitonic_cmp13 u_bitonic (.iKeyA(key13_a), .iKeyB(key13_b), .oKeyLow(key13_low), .oKeyHigh(key13_high));
    min_tree4 u_min (.iKeys(min_keys), .iValid(min_valid), .oKey(min_key), .oIndex(min_index), .oValid(min_found));
    merger_tree2 u_merge (.iKeyA(a32), .iKeyB(b32), .iLaneA(merge_lane_a), .iLaneB(merge_lane_b),
        .iValidA(merge_valid_a), .iValidB(merge_valid_b), .oKeyA(merge_key_a), .oKeyB(merge_key_b),
        .oLaneA(merge_out_lane_a), .oLaneB(merge_out_lane_b), .oValidA(merge_out_valid_a), .oValidB(merge_out_valid_b));
    lif_core u_core (.iState(state_in), .iThreshold(threshold), .iInput(input_value),
        .iLeakShift2(shift2), .oState(state_core), .oSpike(spike_core));
    lif_stateful u_stateful (.i_clk(clk), .i_rst_n(rst_n), .iStep(step),
        .iThreshold(threshold), .iInput(input_value), .iLeakShift2(shift2), .oState(state_saved), .oSpike(spike_saved));
    pruner u_pruner (.iOriginal(original), .iSubsetMatch(subset_matches), .iProcessedValid(processed),
        .iKeys(prune_keys), .iOriginalRows(original_rows), .oResidual(residual), .oValid(prune_valid), .oIndex(prune_index));

    logic [31:0] rng = 32'h95a71326;
    integer cmp_checks = 0, word16_checks = 0, word32_checks = 0;
    integer min_checks = 0, merge_checks = 0, lif_checks = 0, state_checks = 0, prune_checks = 0;
    logic [31:0] expected_state;
    logic expected_spike;

    function automatic logic [31:0] next_random();
        rng = rng * 32'd1664525 + 32'd1013904223;
        return rng;
    endfunction

    function automatic integer pop16(input logic [15:0] word_value);
        integer n;
        pop16 = 0;
        for (n = 0; n < 16; n = n + 1) pop16 = pop16 + int'(word_value[n]);
    endfunction

    function automatic logic [32:0] lif_reference(
        input logic [31:0] state_value, threshold_value,
        input logic [15:0] input_word,
        input logic shift_two
    );
        logic signed [31:0] leaked, extended_input, integrated;
        logic fires;
        leaked = $signed(state_value) >>> (shift_two ? 2 : 1);
        extended_input = {{16{input_word[15]}}, input_word};
        integrated = leaked + extended_input;
        fires = integrated >= $signed(threshold_value);
        return {fires, fires ? 32'b0 : integrated};
    endfunction

    task automatic check_compare();
        #1;
        if ({cmp_lt, cmp_eq, cmp_gt, cmp_ge} !==
            {$signed(a32) < $signed(b32), a32 == b32, $signed(a32) > $signed(b32), $signed(a32) >= $signed(b32)})
            $fatal(1, "cmp32 a=%h b=%h got=%b%b%b%b", a32, b32, cmp_lt, cmp_eq, cmp_gt, cmp_ge);
        if (disjoint !== ((a32 & b32) == 0)) $fatal(1, "overlap a=%h b=%h", a32, b32);
        if (key13_low !== ((key13_a > key13_b) ? key13_b : key13_a) ||
            key13_high !== ((key13_a > key13_b) ? key13_a : key13_b))
            $fatal(1, "bitonic keyA=%h keyB=%h", key13_a, key13_b);
        cmp_checks = cmp_checks + 1;
    endtask

    task automatic check_word16();
        integer idx, j, count;
        logic [15:0] onehot;
        #1;
        idx = 0;
        onehot = 0;
        for (j = 15; j >= 0; j = j - 1) if (mask16[j]) idx = j;
        if (mask16 != 0) onehot[idx] = 1'b1;
        count = pop16(mask16);
        if (b16_valid !== (mask16 != 0) || b16_index !== idx[3:0] ||
            b16_onehot !== onehot || b16_remaining !== (mask16 ^ onehot))
            $fatal(1, "bsf16 mask=%h", mask16);
        if (count16 !== count[4:0]) $fatal(1, "popcount16 mask=%h got=%d expected=%d", mask16, count16, count);
        word16_checks = word16_checks + 1;
    endtask

    task automatic check_word32();
        integer idx, j, running;
        logic [31:0] onehot;
        #1;
        idx = 0;
        onehot = 0;
        for (j = 31; j >= 0; j = j - 1) if (mask32[j]) idx = j;
        if (mask32 != 0) onehot[idx] = 1'b1;
        if (b32_valid !== (mask32 != 0) || b32_index !== idx[4:0] ||
            b32_onehot !== onehot || b32_remaining !== (mask32 ^ onehot))
            $fatal(1, "bsf32 mask=%h", mask32);
        if (leading_valid !== (mask32 != 0) || leading_index !== idx[4:0] || leading_onehot !== onehot)
            $fatal(1, "leading detector mask=%h", mask32);
        running = 0;
        for (j = 0; j < 32; j = j + 1) begin
            if (exclusive[5*j +: 5] !== running[4:0])
                $fatal(1, "exclusive mask=%h position=%d", mask32, j);
            running = running + int'(mask32[j]);
            if (inclusive[6*j +: 6] !== running[5:0])
                $fatal(1, "inclusive mask=%h position=%d", mask32, j);
        end
        if (total !== running[5:0]) $fatal(1, "prefix total mask=%h", mask32);
        word32_checks = word32_checks + 1;
    endtask

    task automatic check_min();
        integer best, j;
        logic [31:0] best_key, candidate;
        #1;
        best = -1;
        best_key = 0;
        for (j = 0; j < 4; j = j + 1) begin
            candidate = min_keys[32*j +: 32];
            if (min_valid[j] && (best < 0 || candidate < best_key)) begin
                best = j;
                best_key = candidate;
            end
        end
        if (min_found !== (best >= 0)) $fatal(1, "min validity mask=%b", min_valid);
        if (best >= 0 && (min_index !== best[1:0] || min_key !== best_key))
            $fatal(1, "min keys=%h mask=%b got_index=%d expected=%d", min_keys, min_valid, min_index, best);
        min_checks = min_checks + 1;
    endtask

    task automatic check_merge();
        logic swap;
        logic [33:0] left, right;
        #1;
        swap = merge_valid_b && (!merge_valid_a || a32 > b32);
        left = {merge_valid_a, merge_lane_a, a32};
        right = {merge_valid_b, merge_lane_b, b32};
        if ({merge_out_valid_a, merge_out_lane_a, merge_key_a} !== (swap ? right : left) ||
            {merge_out_valid_b, merge_out_lane_b, merge_key_b} !== (swap ? left : right))
            $fatal(1, "merger a=%h b=%h valids=%b%b", a32, b32, merge_valid_a, merge_valid_b);
        merge_checks = merge_checks + 1;
    endtask

    task automatic check_lif_core();
        logic [32:0] expected;
        #1;
        expected = lif_reference(state_in, threshold, input_value, shift2);
        if ({spike_core, state_core} !== expected)
            $fatal(1, "lif core state=%h threshold=%h input=%h shift2=%b", state_in, threshold, input_value, shift2);
        lif_checks = lif_checks + 1;
    endtask

    task automatic tick_stateful();
        logic [32:0] expected;
        if (!rst_n) begin
            expected_state = 0;
            expected_spike = 0;
        end else if (step) begin
            expected = lif_reference(expected_state, threshold, input_value, shift2);
            expected_state = expected[31:0];
            expected_spike = expected[32];
        end
        #1 clk = 1;
        #1;
        if ({spike_saved, state_saved} !== {expected_spike, expected_state})
            $fatal(1, "lif stateful rst=%b step=%b got=%h expected=%h", rst_n, step,
                {spike_saved, state_saved}, {expected_spike, expected_state});
        clk = 0;
        state_checks = state_checks + 1;
    endtask

    task automatic check_pruner();
        integer best, j;
        logic [12:0] best_key, candidate;
        logic [15:0] expected;
        #1;
        best = -1;
        best_key = 0;
        for (j = 0; j < 256; j = j + 1) begin
            candidate = prune_keys[13*j +: 13];
            if (subset_matches[j] && processed[j] && (best < 0 || candidate > best_key)) begin
                best = j;
                best_key = candidate;
            end
        end
        expected = original;
        if (best >= 0) expected = original ^ original_rows[16*best +: 16];
        if (prune_valid !== (best >= 0) || residual !== expected)
            $fatal(1, "pruner valid/residual got=%b/%h expected=%b/%h", prune_valid, residual, best >= 0, expected);
        if (best >= 0 && prune_index !== best[7:0])
            $fatal(1, "pruner index got=%d expected=%d", prune_index, best);
        prune_checks = prune_checks + 1;
    endtask

    logic [31:0] edges [0:7];
    logic [31:0] random_word, held_state;
    logic held_spike;
    logic [15:0] row_value;
    integer i, j, t, n;
    initial begin
        a32 = 0; b32 = 0; mask32 = 0; mask16 = 0;
        key13_a = 0; key13_b = 0; min_keys = 0; min_valid = 0;
        merge_valid_a = 0; merge_valid_b = 0; merge_lane_a = 0; merge_lane_b = 1;
        state_in = 0; threshold = 0; input_value = 0; shift2 = 0;
        clk = 0; rst_n = 0; step = 0; expected_state = 0; expected_spike = 0;
        original = 0; subset_matches = 0; processed = 0; prune_keys = 0; original_rows = 0;
        edges[0] = 0; edges[1] = 1; edges[2] = 32'hffffffff;
        edges[3] = 32'h80000000; edges[4] = 32'h7fffffff;
        edges[5] = 32'h80000001; edges[6] = 32'h7ffffffe; edges[7] = 32'hffff8000;
        tick_stateful();
        rst_n = 1;

        for (i = 0; i < 8; i = i + 1) begin
            for (j = 0; j < 8; j = j + 1) begin
                a32 = edges[i]; b32 = edges[j]; key13_a = a32[12:0]; key13_b = b32[12:0];
                check_compare();
                for (t = 0; t < 4; t = t + 1) begin
                    merge_valid_a = t[0]; merge_valid_b = t[1];
                    check_merge();
                end
                state_in = edges[i]; threshold = edges[j]; input_value = edges[j][15:0];
                shift2 = 0; check_lif_core();
                shift2 = 1; check_lif_core();
            end
        end
        // Every16-bit word exercises popcount carry and priority/clear behavior.
        for (i = 0; i < 65536; i = i + 1) begin
            mask16 = i[15:0];
            check_word16();
        end
        mask32 = 0; check_word32();
        mask32 = 32'hffffffff; check_word32();
        mask32 = 32'haaaaaaaa; check_word32();
        mask32 = 32'h55555555; check_word32();
        for (i = 0; i < 32; i = i + 1) begin
            mask32 = 32'b1 << i; check_word32();
            mask32 = (32'b1 << i) | 32'h80000000; check_word32();
        end
        for (i = 0; i < 16; i = i + 1) begin
            min_valid = i[3:0]; min_keys = {4{32'd7}}; check_min();
            min_keys = {32'hffffffff, 32'h80000000, 32'h7fffffff, 32'd0}; check_min();
            min_keys = {32'd0, 32'd0, 32'hffffffff, 32'd1}; check_min();
        end
        for (i = 0; i < 1024; i = i + 1) begin
            a32 = next_random(); b32 = next_random();
            random_word = next_random(); key13_a = random_word[12:0];
            random_word = next_random(); key13_b = random_word[12:0];
            check_compare();
            mask32 = next_random(); check_word32();
            for (j = 0; j < 4; j = j + 1) min_keys[32*j +: 32] = next_random();
            random_word = next_random(); min_valid = random_word[7:4]; check_min();
            merge_valid_a = random_word[8]; merge_valid_b = random_word[9];
            merge_lane_a = random_word[10]; merge_lane_b = random_word[11]; check_merge();
            state_in = next_random(); threshold = next_random();
            random_word = next_random(); input_value = random_word[15:0]; shift2 = random_word[18];
            check_lif_core(); step = random_word[19]; tick_stateful();
        end
        // A saved spike and potential must both hold when step=0.
        rst_n = 0; tick_stateful(); rst_n = 1;
        step = 1; threshold = 0; input_value = 1; shift2 = 0; tick_stateful();
        step = 0; threshold = 32'h7fffffff; input_value = 16'h8000; tick_stateful();
        // Prove reset is synchronous and has precedence over wen=0.
        step = 1; threshold = 32'h7fffffff; input_value = 16'd27; tick_stateful();
        held_state = state_saved; held_spike = spike_saved;
        step = 0; rst_n = 0; #1;
        if ({spike_saved, state_saved} !== {held_spike, held_state}) $fatal(1, "reset acted asynchronously");
        tick_stateful(); rst_n = 1; tick_stateful();

        original = 16'ha55a; subset_matches = '1; processed = 0; check_pruner();
        subset_matches = 0; processed = '1; check_pruner();
        // Equal rows ARE eligible: a full duplicate gives zero residual.
        original = 16'hf03c; subset_matches = 0; processed = 0;
        original_rows[16*255 +: 16] = original;
        prune_keys[13*255 +: 13] = {5'd8, 8'd255};
        subset_matches[255] = 1; processed[255] = 1; check_pruner();
        if (residual !== 16'b0) $fatal(1, "equal-row dedup failed");
        // Duplicate identical keys choose the lowest physical slot.
        original = 16'hffff; subset_matches = 0; processed = 0; prune_keys = 0;
        subset_matches[2] = 1; subset_matches[200] = 1; processed = subset_matches;
        original_rows[16*2 +: 16] = 16'h0003; original_rows[16*200 +: 16] = 16'h000c;
        prune_keys[13*2 +: 13] = {5'd2, 8'd9}; prune_keys[13*200 +: 13] = {5'd2, 8'd9};
        check_pruner();
        // A larger key without processed-valid must not dominate.
        subset_matches[255] = 1; processed[255] = 0; prune_keys[13*255 +: 13] = 13'h1fff;
        check_pruner();
        for (t = 0; t < 128; t = t + 1) begin
            random_word = next_random(); original = random_word[31:16];
            for (j = 0; j < 256; j = j + 1) begin
                random_word = next_random(); row_value = random_word[31:16];
                // Alternate free rows and forced subsets, including zero rows.
                if (j[0]) row_value = row_value & original;
                original_rows[16*j +: 16] = row_value;
                n = pop16(row_value);
                prune_keys[13*j +: 13] = {n[4:0], j[7:0]};
                subset_matches[j] = (row_value & ~original) == 0;
                processed[j] = random_word[20];
            end
            check_pruner();
        end
        $display("PASS all13 tops: compare/overlap/bitonic=%0d bsf16/popcount=%0d bsf32/leading/prefix=%0d min=%0d merger=%0d lif_core=%0d lif_stateful=%0d pruner=%0d",
            cmp_checks, word16_checks, word32_checks, min_checks, merge_checks, lif_checks, state_checks, prune_checks);
        $finish;
    end

    initial begin
        #1000000;
        $fatal(1, "testbench timeout");
    end
endmodule
