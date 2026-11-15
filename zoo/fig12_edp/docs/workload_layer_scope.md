# Workload layer scope: skip fully connected layers (user decision B, 2026-11-13)

Figure 12 evaluates spiking-CNN and spiking-GEMM layers only. Fully connected
layers are excluded from every benchmark's whole-model sums, coverage
denominators and figures:

- classifier heads (`core_classifier`, C01 `core_others_*`: kernel-1 FC heads);
- transformer FFN/MLP layers (spikformer `mlp_fc2_linear`, SDT `mlp_fc_conv1/2`,
  spikinglm `intermediate_dense` / `output_dense`).

Attention projections (`attention_self_query/key/value`,
`attention_output_dense`) are spiking-GEMM and are KEPT. Convolutions,
patch-embed convs and residual-block convs are spiking-CNN and are KEPT.

Canonical rule (layer-name regex; keep wins when both match):

```
KEEP  if  attention_(self_(query|key|value)|output_dense)$
SKIP  if  (_mlp_fc2_linear|_mlp_fc_conv[12]|_core_classifier|_core_others_\d+|_intermediate_dense|_output_dense)$
KEEP  otherwise
```

Totals: 113 layers kept, 38 skipped (of 151); 559 kept feasible
architecture x layer pairs (of 749). The six infeasible Prosperity A08
schedules are conv layers and stay in the kept nominal coverage. Simulation
of skipped layers is not deleted; they are simply not collected into
whole-model totals. Collection, figures and the T87 Stage-A specification
consume this file's rule.

## A02/spikformer_4_384_cifar100_T4_n500

Kept (8):

- layer_01_patch_embed_proj_conv1
- layer_02_patch_embed_proj_conv2
- layer_03_patch_embed_proj_conv3
- layer_04_patch_embed_rpe_conv
- layer_05_block_0_attn_proj_linear
- layer_07_block_1_attn_proj_linear
- layer_09_block_2_attn_proj_linear
- layer_11_block_3_attn_proj_linear

Skipped (4):

- layer_06_block_0_mlp_fc2_linear
- layer_08_block_1_mlp_fc2_linear
- layer_10_block_2_mlp_fc2_linear
- layer_12_block_3_mlp_fc2_linear

## A04/sdt_2_512_cifar100_T4_n500

Kept (12):

- layer_01_patch_embed_proj_conv1
- layer_02_patch_embed_proj_conv2
- layer_03_patch_embed_proj_conv3
- layer_04_patch_embed_rpe_conv
- layer_05_block_0_attn_q_conv
- layer_06_block_0_attn_k_conv
- layer_07_block_0_attn_v_conv
- layer_08_block_0_attn_proj_conv
- layer_11_block_1_attn_q_conv
- layer_12_block_1_attn_k_conv
- layer_13_block_1_attn_v_conv
- layer_14_block_1_attn_proj_conv

Skipped (4):

- layer_09_block_0_mlp_fc_conv1
- layer_10_block_0_mlp_fc_conv2
- layer_15_block_1_mlp_fc_conv1
- layer_16_block_1_mlp_fc_conv2

## A07/spikinglm_t4_T4_n500

Kept (48):

- layer_01_core_bert_encoder_layer_0_attention_self_query
- layer_02_core_bert_encoder_layer_0_attention_self_key
- layer_03_core_bert_encoder_layer_0_attention_self_value
- layer_04_core_bert_encoder_layer_0_attention_output_dense
- layer_07_core_bert_encoder_layer_1_attention_self_query
- layer_08_core_bert_encoder_layer_1_attention_self_key
- layer_09_core_bert_encoder_layer_1_attention_self_value
- layer_10_core_bert_encoder_layer_1_attention_output_dense
- layer_13_core_bert_encoder_layer_2_attention_self_query
- layer_14_core_bert_encoder_layer_2_attention_self_key
- layer_15_core_bert_encoder_layer_2_attention_self_value
- layer_16_core_bert_encoder_layer_2_attention_output_dense
- layer_19_core_bert_encoder_layer_3_attention_self_query
- layer_20_core_bert_encoder_layer_3_attention_self_key
- layer_21_core_bert_encoder_layer_3_attention_self_value
- layer_22_core_bert_encoder_layer_3_attention_output_dense
- layer_25_core_bert_encoder_layer_4_attention_self_query
- layer_26_core_bert_encoder_layer_4_attention_self_key
- layer_27_core_bert_encoder_layer_4_attention_self_value
- layer_28_core_bert_encoder_layer_4_attention_output_dense
- layer_31_core_bert_encoder_layer_5_attention_self_query
- layer_32_core_bert_encoder_layer_5_attention_self_key
- layer_33_core_bert_encoder_layer_5_attention_self_value
- layer_34_core_bert_encoder_layer_5_attention_output_dense
- layer_37_core_bert_encoder_layer_6_attention_self_query
- layer_38_core_bert_encoder_layer_6_attention_self_key
- layer_39_core_bert_encoder_layer_6_attention_self_value
- layer_40_core_bert_encoder_layer_6_attention_output_dense
- layer_43_core_bert_encoder_layer_7_attention_self_query
- layer_44_core_bert_encoder_layer_7_attention_self_key
- layer_45_core_bert_encoder_layer_7_attention_self_value
- layer_46_core_bert_encoder_layer_7_attention_output_dense
- layer_49_core_bert_encoder_layer_8_attention_self_query
- layer_50_core_bert_encoder_layer_8_attention_self_key
- layer_51_core_bert_encoder_layer_8_attention_self_value
- layer_52_core_bert_encoder_layer_8_attention_output_dense
- layer_55_core_bert_encoder_layer_9_attention_self_query
- layer_56_core_bert_encoder_layer_9_attention_self_key
- layer_57_core_bert_encoder_layer_9_attention_self_value
- layer_58_core_bert_encoder_layer_9_attention_output_dense
- layer_61_core_bert_encoder_layer_10_attention_self_query
- layer_62_core_bert_encoder_layer_10_attention_self_key
- layer_63_core_bert_encoder_layer_10_attention_self_value
- layer_64_core_bert_encoder_layer_10_attention_output_dense
- layer_67_core_bert_encoder_layer_11_attention_self_query
- layer_68_core_bert_encoder_layer_11_attention_self_key
- layer_69_core_bert_encoder_layer_11_attention_self_value
- layer_70_core_bert_encoder_layer_11_attention_output_dense

Skipped (24):

- layer_05_core_bert_encoder_layer_0_intermediate_dense
- layer_06_core_bert_encoder_layer_0_output_dense
- layer_11_core_bert_encoder_layer_1_intermediate_dense
- layer_12_core_bert_encoder_layer_1_output_dense
- layer_17_core_bert_encoder_layer_2_intermediate_dense
- layer_18_core_bert_encoder_layer_2_output_dense
- layer_23_core_bert_encoder_layer_3_intermediate_dense
- layer_24_core_bert_encoder_layer_3_output_dense
- layer_29_core_bert_encoder_layer_4_intermediate_dense
- layer_30_core_bert_encoder_layer_4_output_dense
- layer_35_core_bert_encoder_layer_5_intermediate_dense
- layer_36_core_bert_encoder_layer_5_output_dense
- layer_41_core_bert_encoder_layer_6_intermediate_dense
- layer_42_core_bert_encoder_layer_6_output_dense
- layer_47_core_bert_encoder_layer_7_intermediate_dense
- layer_48_core_bert_encoder_layer_7_output_dense
- layer_53_core_bert_encoder_layer_8_intermediate_dense
- layer_54_core_bert_encoder_layer_8_output_dense
- layer_59_core_bert_encoder_layer_9_intermediate_dense
- layer_60_core_bert_encoder_layer_9_output_dense
- layer_65_core_bert_encoder_layer_10_intermediate_dense
- layer_66_core_bert_encoder_layer_10_output_dense
- layer_71_core_bert_encoder_layer_11_intermediate_dense
- layer_72_core_bert_encoder_layer_11_output_dense

## A08/vgg16_cifar10_loas_T32_n500

Kept (12):

- layer_01_core_features_3
- layer_02_core_features_7
- layer_03_core_features_10
- layer_04_core_features_14
- layer_05_core_features_17
- layer_06_core_features_20
- layer_07_core_features_24
- layer_08_core_features_27
- layer_09_core_features_30
- layer_10_core_features_34
- layer_11_core_features_37
- layer_12_core_features_40

Skipped (1):

- layer_13_core_classifier

## B09/loas_resnet19_T4_n500

Kept (13):

- layer_02_core_layer1_0_conv2
- layer_04_core_layer1_1_conv1
- layer_05_core_layer1_1_conv2
- layer_06_core_layer1_2_conv1
- layer_07_core_layer1_2_conv2
- layer_09_core_layer2_0_conv2
- layer_11_core_layer2_1_conv1
- layer_12_core_layer2_1_conv2
- layer_13_core_layer2_2_conv1
- layer_14_core_layer2_2_conv2
- layer_16_core_layer3_0_conv2
- layer_18_core_layer3_1_conv1
- layer_19_core_layer3_1_conv2

Skipped: none

## B09/loas_vgg16_T4_n500

Kept (12):

- layer_01_core_features_3
- layer_02_core_features_7
- layer_03_core_features_10
- layer_04_core_features_14
- layer_05_core_features_17
- layer_06_core_features_20
- layer_07_core_features_24
- layer_08_core_features_27
- layer_09_core_features_30
- layer_10_core_features_34
- layer_11_core_features_37
- layer_12_core_features_40

Skipped (1):

- layer_13_core_classifier

## C01/sma_azo_vgg_cifar10_dvs_T10_n500

Kept (4):

- layer_01_core_block2_0_0
- layer_02_core_block3_0_0
- layer_03_core_block4_0_0
- layer_04_core_block5_0_0

Skipped (2):

- layer_05_core_others_5
- layer_06_core_others_8

## C01/sma_azo_vgg_dvs128_gesture_T16_n500

Kept (4):

- layer_01_core_block2_0_0
- layer_02_core_block3_0_0
- layer_03_core_block4_0_0
- layer_04_core_block5_0_0

Skipped (2):

- layer_05_core_others_5
- layer_06_core_others_8

