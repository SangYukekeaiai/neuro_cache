# Caption: fig_perlayer_v0_vs_spad

Per-layer latency of fig12's three arms on the loas architecture at the
ASAP7-synthesis-derived 500 MHz clock: the nocsim multi-node scratchpad
baseline (spad) against the two cachesim cache hierarchies (cacheA, which is
the V0 base configuration, and cacheB). Lines are means over the 23 input
samples common to all three arms; bands are 95% confidence intervals
(t-interval, n=23). Top: vgg16 (B09/loas_vgg16_T4_n500, 12 layers). Bottom:
spikinglm (A07/spikinglm_t4_T4_n500, the 48 layers simulated by all arms).
Caveat: spad comes from nocsim while the cache arms come from cachesim; the
simulators share the same trace captures, energy table, and clock, not a
single performance model. The fig12 cacheA rows are bit-identical in T_s to
the cache_dse V0 rows, so this figure and the cache-DSE sweeps describe the
same baseline.

Headline numbers (regen: `conda run -n base python
zoo/cache_dse/fig_perlayer_v0_vs_spad.py`):
- geomean per-layer spad/cache latency ratio, vgg16: 1.518 (cacheA),
  1.408 (cacheB); spikinglm: 1.413 (cacheA), 1.415 (cacheB)
- end-to-end latency sums, vgg16: 5.24 ms (spad) vs 3.70 ms (cacheA) /
  4.05 ms (cacheB); spikinglm: 36.7 ms vs 30.8 ms / 30.8 ms
- weakest case (shown, not hidden): vgg16 layer 9, where both cache arms are
  slower than the scratchpad; spikinglm heavy layers are latency-equal, the
  win comes from the light layers where spad stays pinned at its flat
  ~0.6 ms.
