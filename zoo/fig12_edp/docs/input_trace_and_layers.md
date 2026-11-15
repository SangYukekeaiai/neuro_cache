# Input traces and layer scope

Source trace dataset (read-only): `/work/nvme/bebv/yyu9/input_trace_delta/<ID>/<benchmark>/` holding the captured spike/weight streams and `meta.json` per benchmark; 500 samples each. Per case, the simulator input is a generated WCTS stream written to `<case>/sample_<k>/sample_<k>.wcts` (command, record count and SHA-256 recorded in `generation.json`; the stream is deleted after the durable result commit, provenance retained).

Exclusion rule (user decision B, 2026-11-13): fully connected layers are out of every whole-model sum; attention projections are spiking-GEMM and stay; convolutions stay. Rule: KEEP if name ends in attention_(self_query|self_key|self_value|output_dense); SKIP if it ends in _mlp_fc2_linear, _mlp_fc_conv1/2, _core_classifier, _core_others_N, _intermediate_dense, _output_dense; KEEP otherwise.


## A02/spikformer_4_384_cifar100_T4_n500

Trace: `/work/nvme/bebv/yyu9/input_trace_delta/A02/spikformer_4_384_cifar100_T4_n500` (500 samples)

| Layer | KHxKW | CIN | COUT | HOxWO | T | Status | Reason |
|---|---|---|---|---|---|---|---|
| layer_01_patch_embed_proj_conv1 | 3x3 | 48 | 96 | 32x32 | 4 | kept | spiking-CNN/GEMM |
| layer_02_patch_embed_proj_conv2 | 3x3 | 96 | 192 | 32x32 | 4 | kept | spiking-CNN/GEMM |
| layer_03_patch_embed_proj_conv3 | 3x3 | 192 | 384 | 16x16 | 4 | kept | spiking-CNN/GEMM |
| layer_04_patch_embed_rpe_conv | 3x3 | 384 | 384 | 8x8 | 4 | kept | spiking-CNN/GEMM |
| layer_05_block_0_attn_proj_linear | 1x1 | 384 | 384 | 64x1 | 4 | kept | spiking-CNN/GEMM |
| layer_06_block_0_mlp_fc2_linear | 1x1 | 1536 | 384 | 64x1 | 4 | SKIPPED | transformer FFN/MLP (FC) |
| layer_07_block_1_attn_proj_linear | 1x1 | 384 | 384 | 64x1 | 4 | kept | spiking-CNN/GEMM |
| layer_08_block_1_mlp_fc2_linear | 1x1 | 1536 | 384 | 64x1 | 4 | SKIPPED | transformer FFN/MLP (FC) |
| layer_09_block_2_attn_proj_linear | 1x1 | 384 | 384 | 64x1 | 4 | kept | spiking-CNN/GEMM |
| layer_10_block_2_mlp_fc2_linear | 1x1 | 1536 | 384 | 64x1 | 4 | SKIPPED | transformer FFN/MLP (FC) |
| layer_11_block_3_attn_proj_linear | 1x1 | 384 | 384 | 64x1 | 4 | kept | spiking-CNN/GEMM |
| layer_12_block_3_mlp_fc2_linear | 1x1 | 1536 | 384 | 64x1 | 4 | SKIPPED | transformer FFN/MLP (FC) |

## A04/sdt_2_512_cifar100_T4_n500

Trace: `/work/nvme/bebv/yyu9/input_trace_delta/A04/sdt_2_512_cifar100_T4_n500` (500 samples)

| Layer | KHxKW | CIN | COUT | HOxWO | T | Status | Reason |
|---|---|---|---|---|---|---|---|
| layer_01_patch_embed_proj_conv1 | 3x3 | 64 | 128 | 32x32 | 4 | kept | spiking-CNN/GEMM |
| layer_02_patch_embed_proj_conv2 | 3x3 | 128 | 256 | 32x32 | 4 | kept | spiking-CNN/GEMM |
| layer_03_patch_embed_proj_conv3 | 3x3 | 256 | 512 | 16x16 | 4 | kept | spiking-CNN/GEMM |
| layer_04_patch_embed_rpe_conv | 3x3 | 512 | 512 | 8x8 | 4 | kept | spiking-CNN/GEMM |
| layer_05_block_0_attn_q_conv | 1x1 | 512 | 512 | 8x8 | 4 | kept | spiking-CNN/GEMM |
| layer_06_block_0_attn_k_conv | 1x1 | 512 | 512 | 8x8 | 4 | kept | spiking-CNN/GEMM |
| layer_07_block_0_attn_v_conv | 1x1 | 512 | 512 | 8x8 | 4 | kept | spiking-CNN/GEMM |
| layer_08_block_0_attn_proj_conv | 1x1 | 512 | 512 | 8x8 | 4 | kept | spiking-CNN/GEMM |
| layer_09_block_0_mlp_fc_conv1 | 1x1 | 512 | 2048 | 8x8 | 4 | SKIPPED | transformer FFN/MLP (FC) |
| layer_10_block_0_mlp_fc_conv2 | 1x1 | 2048 | 512 | 8x8 | 4 | SKIPPED | transformer FFN/MLP (FC) |
| layer_11_block_1_attn_q_conv | 1x1 | 512 | 512 | 8x8 | 4 | kept | spiking-CNN/GEMM |
| layer_12_block_1_attn_k_conv | 1x1 | 512 | 512 | 8x8 | 4 | kept | spiking-CNN/GEMM |
| layer_13_block_1_attn_v_conv | 1x1 | 512 | 512 | 8x8 | 4 | kept | spiking-CNN/GEMM |
| layer_14_block_1_attn_proj_conv | 1x1 | 512 | 512 | 8x8 | 4 | kept | spiking-CNN/GEMM |
| layer_15_block_1_mlp_fc_conv1 | 1x1 | 512 | 2048 | 8x8 | 4 | SKIPPED | transformer FFN/MLP (FC) |
| layer_16_block_1_mlp_fc_conv2 | 1x1 | 2048 | 512 | 8x8 | 4 | SKIPPED | transformer FFN/MLP (FC) |

## A07/spikinglm_t4_T4_n500

Trace: `/work/nvme/bebv/yyu9/input_trace_delta/A07/spikinglm_t4_T4_n500` (500 samples)

| Layer | KHxKW | CIN | COUT | HOxWO | T | Status | Reason |
|---|---|---|---|---|---|---|---|
| layer_01_core_bert_encoder_layer_0_attention_self_query | 1x1 | 768 | 768 | 128x1 | 4 | kept | spiking-GEMM attention projection |
| layer_02_core_bert_encoder_layer_0_attention_self_key | 1x1 | 768 | 768 | 128x1 | 4 | kept | spiking-GEMM attention projection |
| layer_03_core_bert_encoder_layer_0_attention_self_value | 1x1 | 768 | 768 | 128x1 | 4 | kept | spiking-GEMM attention projection |
| layer_04_core_bert_encoder_layer_0_attention_output_dense | 1x1 | 768 | 768 | 128x1 | 4 | kept | spiking-GEMM attention projection |
| layer_05_core_bert_encoder_layer_0_intermediate_dense | 1x1 | 768 | 3072 | 128x1 | 4 | SKIPPED | FC dense |
| layer_06_core_bert_encoder_layer_0_output_dense | 1x1 | 3072 | 768 | 128x1 | 4 | SKIPPED | FC dense |
| layer_07_core_bert_encoder_layer_1_attention_self_query | 1x1 | 768 | 768 | 128x1 | 4 | kept | spiking-GEMM attention projection |
| layer_08_core_bert_encoder_layer_1_attention_self_key | 1x1 | 768 | 768 | 128x1 | 4 | kept | spiking-GEMM attention projection |
| layer_09_core_bert_encoder_layer_1_attention_self_value | 1x1 | 768 | 768 | 128x1 | 4 | kept | spiking-GEMM attention projection |
| layer_10_core_bert_encoder_layer_1_attention_output_dense | 1x1 | 768 | 768 | 128x1 | 4 | kept | spiking-GEMM attention projection |
| layer_11_core_bert_encoder_layer_1_intermediate_dense | 1x1 | 768 | 3072 | 128x1 | 4 | SKIPPED | FC dense |
| layer_12_core_bert_encoder_layer_1_output_dense | 1x1 | 3072 | 768 | 128x1 | 4 | SKIPPED | FC dense |
| layer_13_core_bert_encoder_layer_2_attention_self_query | 1x1 | 768 | 768 | 128x1 | 4 | kept | spiking-GEMM attention projection |
| layer_14_core_bert_encoder_layer_2_attention_self_key | 1x1 | 768 | 768 | 128x1 | 4 | kept | spiking-GEMM attention projection |
| layer_15_core_bert_encoder_layer_2_attention_self_value | 1x1 | 768 | 768 | 128x1 | 4 | kept | spiking-GEMM attention projection |
| layer_16_core_bert_encoder_layer_2_attention_output_dense | 1x1 | 768 | 768 | 128x1 | 4 | kept | spiking-GEMM attention projection |
| layer_17_core_bert_encoder_layer_2_intermediate_dense | 1x1 | 768 | 3072 | 128x1 | 4 | SKIPPED | FC dense |
| layer_18_core_bert_encoder_layer_2_output_dense | 1x1 | 3072 | 768 | 128x1 | 4 | SKIPPED | FC dense |
| layer_19_core_bert_encoder_layer_3_attention_self_query | 1x1 | 768 | 768 | 128x1 | 4 | kept | spiking-GEMM attention projection |
| layer_20_core_bert_encoder_layer_3_attention_self_key | 1x1 | 768 | 768 | 128x1 | 4 | kept | spiking-GEMM attention projection |
| layer_21_core_bert_encoder_layer_3_attention_self_value | 1x1 | 768 | 768 | 128x1 | 4 | kept | spiking-GEMM attention projection |
| layer_22_core_bert_encoder_layer_3_attention_output_dense | 1x1 | 768 | 768 | 128x1 | 4 | kept | spiking-GEMM attention projection |
| layer_23_core_bert_encoder_layer_3_intermediate_dense | 1x1 | 768 | 3072 | 128x1 | 4 | SKIPPED | FC dense |
| layer_24_core_bert_encoder_layer_3_output_dense | 1x1 | 3072 | 768 | 128x1 | 4 | SKIPPED | FC dense |
| layer_25_core_bert_encoder_layer_4_attention_self_query | 1x1 | 768 | 768 | 128x1 | 4 | kept | spiking-GEMM attention projection |
| layer_26_core_bert_encoder_layer_4_attention_self_key | 1x1 | 768 | 768 | 128x1 | 4 | kept | spiking-GEMM attention projection |
| layer_27_core_bert_encoder_layer_4_attention_self_value | 1x1 | 768 | 768 | 128x1 | 4 | kept | spiking-GEMM attention projection |
| layer_28_core_bert_encoder_layer_4_attention_output_dense | 1x1 | 768 | 768 | 128x1 | 4 | kept | spiking-GEMM attention projection |
| layer_29_core_bert_encoder_layer_4_intermediate_dense | 1x1 | 768 | 3072 | 128x1 | 4 | SKIPPED | FC dense |
| layer_30_core_bert_encoder_layer_4_output_dense | 1x1 | 3072 | 768 | 128x1 | 4 | SKIPPED | FC dense |
| layer_31_core_bert_encoder_layer_5_attention_self_query | 1x1 | 768 | 768 | 128x1 | 4 | kept | spiking-GEMM attention projection |
| layer_32_core_bert_encoder_layer_5_attention_self_key | 1x1 | 768 | 768 | 128x1 | 4 | kept | spiking-GEMM attention projection |
| layer_33_core_bert_encoder_layer_5_attention_self_value | 1x1 | 768 | 768 | 128x1 | 4 | kept | spiking-GEMM attention projection |
| layer_34_core_bert_encoder_layer_5_attention_output_dense | 1x1 | 768 | 768 | 128x1 | 4 | kept | spiking-GEMM attention projection |
| layer_35_core_bert_encoder_layer_5_intermediate_dense | 1x1 | 768 | 3072 | 128x1 | 4 | SKIPPED | FC dense |
| layer_36_core_bert_encoder_layer_5_output_dense | 1x1 | 3072 | 768 | 128x1 | 4 | SKIPPED | FC dense |
| layer_37_core_bert_encoder_layer_6_attention_self_query | 1x1 | 768 | 768 | 128x1 | 4 | kept | spiking-GEMM attention projection |
| layer_38_core_bert_encoder_layer_6_attention_self_key | 1x1 | 768 | 768 | 128x1 | 4 | kept | spiking-GEMM attention projection |
| layer_39_core_bert_encoder_layer_6_attention_self_value | 1x1 | 768 | 768 | 128x1 | 4 | kept | spiking-GEMM attention projection |
| layer_40_core_bert_encoder_layer_6_attention_output_dense | 1x1 | 768 | 768 | 128x1 | 4 | kept | spiking-GEMM attention projection |
| layer_41_core_bert_encoder_layer_6_intermediate_dense | 1x1 | 768 | 3072 | 128x1 | 4 | SKIPPED | FC dense |
| layer_42_core_bert_encoder_layer_6_output_dense | 1x1 | 3072 | 768 | 128x1 | 4 | SKIPPED | FC dense |
| layer_43_core_bert_encoder_layer_7_attention_self_query | 1x1 | 768 | 768 | 128x1 | 4 | kept | spiking-GEMM attention projection |
| layer_44_core_bert_encoder_layer_7_attention_self_key | 1x1 | 768 | 768 | 128x1 | 4 | kept | spiking-GEMM attention projection |
| layer_45_core_bert_encoder_layer_7_attention_self_value | 1x1 | 768 | 768 | 128x1 | 4 | kept | spiking-GEMM attention projection |
| layer_46_core_bert_encoder_layer_7_attention_output_dense | 1x1 | 768 | 768 | 128x1 | 4 | kept | spiking-GEMM attention projection |
| layer_47_core_bert_encoder_layer_7_intermediate_dense | 1x1 | 768 | 3072 | 128x1 | 4 | SKIPPED | FC dense |
| layer_48_core_bert_encoder_layer_7_output_dense | 1x1 | 3072 | 768 | 128x1 | 4 | SKIPPED | FC dense |
| layer_49_core_bert_encoder_layer_8_attention_self_query | 1x1 | 768 | 768 | 128x1 | 4 | kept | spiking-GEMM attention projection |
| layer_50_core_bert_encoder_layer_8_attention_self_key | 1x1 | 768 | 768 | 128x1 | 4 | kept | spiking-GEMM attention projection |
| layer_51_core_bert_encoder_layer_8_attention_self_value | 1x1 | 768 | 768 | 128x1 | 4 | kept | spiking-GEMM attention projection |
| layer_52_core_bert_encoder_layer_8_attention_output_dense | 1x1 | 768 | 768 | 128x1 | 4 | kept | spiking-GEMM attention projection |
| layer_53_core_bert_encoder_layer_8_intermediate_dense | 1x1 | 768 | 3072 | 128x1 | 4 | SKIPPED | FC dense |
| layer_54_core_bert_encoder_layer_8_output_dense | 1x1 | 3072 | 768 | 128x1 | 4 | SKIPPED | FC dense |
| layer_55_core_bert_encoder_layer_9_attention_self_query | 1x1 | 768 | 768 | 128x1 | 4 | kept | spiking-GEMM attention projection |
| layer_56_core_bert_encoder_layer_9_attention_self_key | 1x1 | 768 | 768 | 128x1 | 4 | kept | spiking-GEMM attention projection |
| layer_57_core_bert_encoder_layer_9_attention_self_value | 1x1 | 768 | 768 | 128x1 | 4 | kept | spiking-GEMM attention projection |
| layer_58_core_bert_encoder_layer_9_attention_output_dense | 1x1 | 768 | 768 | 128x1 | 4 | kept | spiking-GEMM attention projection |
| layer_59_core_bert_encoder_layer_9_intermediate_dense | 1x1 | 768 | 3072 | 128x1 | 4 | SKIPPED | FC dense |
| layer_60_core_bert_encoder_layer_9_output_dense | 1x1 | 3072 | 768 | 128x1 | 4 | SKIPPED | FC dense |
| layer_61_core_bert_encoder_layer_10_attention_self_query | 1x1 | 768 | 768 | 128x1 | 4 | kept | spiking-GEMM attention projection |
| layer_62_core_bert_encoder_layer_10_attention_self_key | 1x1 | 768 | 768 | 128x1 | 4 | kept | spiking-GEMM attention projection |
| layer_63_core_bert_encoder_layer_10_attention_self_value | 1x1 | 768 | 768 | 128x1 | 4 | kept | spiking-GEMM attention projection |
| layer_64_core_bert_encoder_layer_10_attention_output_dense | 1x1 | 768 | 768 | 128x1 | 4 | kept | spiking-GEMM attention projection |
| layer_65_core_bert_encoder_layer_10_intermediate_dense | 1x1 | 768 | 3072 | 128x1 | 4 | SKIPPED | FC dense |
| layer_66_core_bert_encoder_layer_10_output_dense | 1x1 | 3072 | 768 | 128x1 | 4 | SKIPPED | FC dense |
| layer_67_core_bert_encoder_layer_11_attention_self_query | 1x1 | 768 | 768 | 128x1 | 4 | kept | spiking-GEMM attention projection |
| layer_68_core_bert_encoder_layer_11_attention_self_key | 1x1 | 768 | 768 | 128x1 | 4 | kept | spiking-GEMM attention projection |
| layer_69_core_bert_encoder_layer_11_attention_self_value | 1x1 | 768 | 768 | 128x1 | 4 | kept | spiking-GEMM attention projection |
| layer_70_core_bert_encoder_layer_11_attention_output_dense | 1x1 | 768 | 768 | 128x1 | 4 | kept | spiking-GEMM attention projection |
| layer_71_core_bert_encoder_layer_11_intermediate_dense | 1x1 | 768 | 3072 | 128x1 | 4 | SKIPPED | FC dense |
| layer_72_core_bert_encoder_layer_11_output_dense | 1x1 | 3072 | 768 | 128x1 | 4 | SKIPPED | FC dense |

## A08/vgg16_cifar10_loas_T32_n500

Trace: `/work/nvme/bebv/yyu9/input_trace_delta/A08/vgg16_cifar10_loas_T32_n500` (500 samples)

| Layer | KHxKW | CIN | COUT | HOxWO | T | Status | Reason |
|---|---|---|---|---|---|---|---|
| layer_01_core_features_3 | 3x3 | 64 | 64 | 32x32 | 32 | kept | spiking-CNN/GEMM |
| layer_02_core_features_7 | 3x3 | 64 | 128 | 16x16 | 32 | kept | spiking-CNN/GEMM |
| layer_03_core_features_10 | 3x3 | 128 | 128 | 16x16 | 32 | kept | spiking-CNN/GEMM |
| layer_04_core_features_14 | 3x3 | 128 | 256 | 8x8 | 32 | kept | spiking-CNN/GEMM |
| layer_05_core_features_17 | 3x3 | 256 | 256 | 8x8 | 32 | kept | spiking-CNN/GEMM |
| layer_06_core_features_20 | 3x3 | 256 | 256 | 8x8 | 32 | kept | spiking-CNN/GEMM |
| layer_07_core_features_24 | 3x3 | 256 | 512 | 4x4 | 32 | kept | spiking-CNN/GEMM |
| layer_08_core_features_27 | 3x3 | 512 | 512 | 4x4 | 32 | kept | spiking-CNN/GEMM |
| layer_09_core_features_30 | 3x3 | 512 | 512 | 4x4 | 32 | kept | spiking-CNN/GEMM |
| layer_10_core_features_34 | 3x3 | 512 | 512 | 2x2 | 32 | kept | spiking-CNN/GEMM |
| layer_11_core_features_37 | 3x3 | 512 | 512 | 2x2 | 32 | kept | spiking-CNN/GEMM |
| layer_12_core_features_40 | 3x3 | 512 | 512 | 2x2 | 32 | kept | spiking-CNN/GEMM |
| layer_13_core_classifier | 1x1 | 512 | 10 | 1x1 | 32 | SKIPPED | FC classifier head |

## B09/loas_vgg16_T4_n500

Trace: `/work/nvme/bebv/yyu9/input_trace_delta/B09/loas_vgg16_T4_n500` (500 samples)

| Layer | KHxKW | CIN | COUT | HOxWO | T | Status | Reason |
|---|---|---|---|---|---|---|---|
| layer_01_core_features_3 | 3x3 | 64 | 64 | 32x32 | 4 | kept | spiking-CNN/GEMM |
| layer_02_core_features_7 | 3x3 | 64 | 128 | 16x16 | 4 | kept | spiking-CNN/GEMM |
| layer_03_core_features_10 | 3x3 | 128 | 128 | 16x16 | 4 | kept | spiking-CNN/GEMM |
| layer_04_core_features_14 | 3x3 | 128 | 256 | 8x8 | 4 | kept | spiking-CNN/GEMM |
| layer_05_core_features_17 | 3x3 | 256 | 256 | 8x8 | 4 | kept | spiking-CNN/GEMM |
| layer_06_core_features_20 | 3x3 | 256 | 256 | 8x8 | 4 | kept | spiking-CNN/GEMM |
| layer_07_core_features_24 | 3x3 | 256 | 512 | 4x4 | 4 | kept | spiking-CNN/GEMM |
| layer_08_core_features_27 | 3x3 | 512 | 512 | 4x4 | 4 | kept | spiking-CNN/GEMM |
| layer_09_core_features_30 | 3x3 | 512 | 512 | 4x4 | 4 | kept | spiking-CNN/GEMM |
| layer_10_core_features_34 | 3x3 | 512 | 512 | 2x2 | 4 | kept | spiking-CNN/GEMM |
| layer_11_core_features_37 | 3x3 | 512 | 512 | 2x2 | 4 | kept | spiking-CNN/GEMM |
| layer_12_core_features_40 | 3x3 | 512 | 512 | 2x2 | 4 | kept | spiking-CNN/GEMM |
| layer_13_core_classifier | 1x1 | 512 | 10 | 1x1 | 4 | SKIPPED | FC classifier head |

## B09/loas_resnet19_T4_n500

Trace: `/work/nvme/bebv/yyu9/input_trace_delta/B09/loas_resnet19_T4_n500` (500 samples)

| Layer | KHxKW | CIN | COUT | HOxWO | T | Status | Reason |
|---|---|---|---|---|---|---|---|
| layer_02_core_layer1_0_conv2 | 3x3 | 128 | 128 | 16x16 | 4 | kept | spiking-CNN/GEMM |
| layer_04_core_layer1_1_conv1 | 3x3 | 128 | 128 | 16x16 | 4 | kept | spiking-CNN/GEMM |
| layer_05_core_layer1_1_conv2 | 3x3 | 128 | 128 | 16x16 | 4 | kept | spiking-CNN/GEMM |
| layer_06_core_layer1_2_conv1 | 3x3 | 128 | 128 | 16x16 | 4 | kept | spiking-CNN/GEMM |
| layer_07_core_layer1_2_conv2 | 3x3 | 128 | 128 | 16x16 | 4 | kept | spiking-CNN/GEMM |
| layer_09_core_layer2_0_conv2 | 3x3 | 256 | 256 | 8x8 | 4 | kept | spiking-CNN/GEMM |
| layer_11_core_layer2_1_conv1 | 3x3 | 256 | 256 | 8x8 | 4 | kept | spiking-CNN/GEMM |
| layer_12_core_layer2_1_conv2 | 3x3 | 256 | 256 | 8x8 | 4 | kept | spiking-CNN/GEMM |
| layer_13_core_layer2_2_conv1 | 3x3 | 256 | 256 | 8x8 | 4 | kept | spiking-CNN/GEMM |
| layer_14_core_layer2_2_conv2 | 3x3 | 256 | 256 | 8x8 | 4 | kept | spiking-CNN/GEMM |
| layer_16_core_layer3_0_conv2 | 3x3 | 512 | 512 | 4x4 | 4 | kept | spiking-CNN/GEMM |
| layer_18_core_layer3_1_conv1 | 3x3 | 512 | 512 | 4x4 | 4 | kept | spiking-CNN/GEMM |
| layer_19_core_layer3_1_conv2 | 3x3 | 512 | 512 | 4x4 | 4 | kept | spiking-CNN/GEMM |

## C01/sma_azo_vgg_cifar10_dvs_T10_n500

Trace: `/work/nvme/bebv/yyu9/input_trace_delta/C01/sma_azo_vgg_cifar10_dvs_T10_n500` (500 samples)

| Layer | KHxKW | CIN | COUT | HOxWO | T | Status | Reason |
|---|---|---|---|---|---|---|---|
| layer_01_core_block2_0_0 | 3x3 | 64 | 128 | 64x64 | 10 | kept | spiking-CNN/GEMM |
| layer_02_core_block3_0_0 | 3x3 | 128 | 256 | 32x32 | 10 | kept | spiking-CNN/GEMM |
| layer_03_core_block4_0_0 | 3x3 | 256 | 512 | 16x16 | 10 | kept | spiking-CNN/GEMM |
| layer_04_core_block5_0_0 | 3x3 | 512 | 512 | 8x8 | 10 | kept | spiking-CNN/GEMM |
| layer_05_core_others_5 | 1x1 | 2048 | 1024 | 1x1 | 10 | SKIPPED | FC classifier head |
| layer_06_core_others_8 | 1x1 | 1024 | 10 | 1x1 | 10 | SKIPPED | FC classifier head |

## C01/sma_azo_vgg_dvs128_gesture_T16_n500

Trace: `/work/nvme/bebv/yyu9/input_trace_delta/C01/sma_azo_vgg_dvs128_gesture_T16_n500` (500 samples)

| Layer | KHxKW | CIN | COUT | HOxWO | T | Status | Reason |
|---|---|---|---|---|---|---|---|
| layer_01_core_block2_0_0 | 3x3 | 64 | 128 | 64x64 | 16 | kept | spiking-CNN/GEMM |
| layer_02_core_block3_0_0 | 3x3 | 128 | 256 | 32x32 | 16 | kept | spiking-CNN/GEMM |
| layer_03_core_block4_0_0 | 3x3 | 256 | 512 | 16x16 | 16 | kept | spiking-CNN/GEMM |
| layer_04_core_block5_0_0 | 3x3 | 512 | 512 | 8x8 | 16 | kept | spiking-CNN/GEMM |
| layer_05_core_others_5 | 1x1 | 2048 | 1024 | 1x1 | 16 | SKIPPED | FC classifier head |
| layer_06_core_others_8 | 1x1 | 1024 | 11 | 1x1 | 16 | SKIPPED | FC classifier head |

Totals: 113 kept, 38 skipped (of 151). Canonical rule and per-benchmark lists also in [workload_layer_scope.md](workload_layer_scope.md).
