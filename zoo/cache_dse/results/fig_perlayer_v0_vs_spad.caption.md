# Caption: fig_perlayer_v0_vs_spad

Per-layer latency of the cacheA (V0) cache hierarchy (cachesim) against the
multi-node scratchpad baseline (nocsim) on the loas architecture at the
ASAP7-synthesis-derived 500 MHz clock. Lines are means over the 8 input
samples common to both campaigns; bands are 95% confidence intervals
(t-interval, n=8). Top: vgg16 (B09/loas_vgg16_T4_n500, 12 layers). Bottom:
spikinglm (A07/spikinglm_t4_T4_n500, the 48 of 72 layers simulated by both
tools). Caveat: the two series come from different simulators that share the
same trace captures, energy table, and clock, not from a single model.

Headline numbers (regen: `conda run -n base python
zoo/cache_dse/fig_perlayer_v0_vs_spad.py`):
- geomean per-layer spad/cacheA latency ratio: 1.517 (vgg16), 1.409 (spikinglm)
- end-to-end latency sums: vgg16 3.71 ms (cacheA) vs 5.24 ms (spad) = 1.41x;
  spikinglm 31.0 ms vs 36.9 ms = 1.19x
- weakest case (shown, not hidden): vgg16 layer 9, where cacheA is slower
  than the scratchpad; spikinglm heavy layers are latency-equal, the win
  comes from the light layers where spad stays pinned at its flat ~0.6 ms.
