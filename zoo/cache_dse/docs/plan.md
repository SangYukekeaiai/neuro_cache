# RQ4 cache design-space plan (redefined) - AWAITING REVIEW, nothing implemented

Target: `\subsection{RQ4: Cache Design Space}`, `sec:eval-cache-dse`,
`src/08_evaluation.tex:202-207` of `/u/yyu9/projects/2027_ASPLOS_neuro_cache`.
Two prose lines (`:205`, `:206`) and a `% TODO: results`.

RQ4 is a single-benchmark, cache-versus-cache study:

- one benchmark, `B09/loas_vgg16_T4_n500`, arch `loas`;
- every design point is **cacheA or a one-knob variant of cacheA**. No spad
  arm, no cross-architecture comparison, no cacheB;
- nine named variants around the operating point, not ten swept axes;
- **two reported metrics only: performance and EDP.** Not hit rate, not
  off-chip traffic, not latency and energy as separate series. Those remain
  as S1 gates and appendix columns; they are not in the figure.

The question the figure answers: **"on the benchmark the paper leads with,
what does each knob of the neuromorphic cache buy in performance and in EDP,
and how far is the chosen point from the bound?"**

Claim the figure should prove: the operating point is not accidental. Each
knob moved off it costs performance, EDP, or both; the prefetch knobs
dominate the capacity knobs; and the distance to the Belady bound is small
enough that replacement is not where the remaining headroom lies.

All writes under `zoo/cache_dse/`, own configs, own retained trace corpus.

---

## Framing fact: there are no cache-parameter CLI flags

Every RQ4 knob is a key in a flat JSON config file. The complete CLI surface
of `cachesim_run` is I/O and row identity only
(`src/lays/cachesim/native/apps/cachesim_run.cpp:163-199`): `--config`,
`--trace`, `--out`, `--hist`, `--cache-state`, `--access-log`,
`--barrier-log`, `--oracle`, `--l2-oracle`, `--line-trace*`, `--arm`,
`--tier`, `--run-id`, `--git-commit`, `--header`/`--no-header`,
`--oracle-only`. `cachesim_sweep` adds `--config-grid`, `--max-engines`
(default 256) and `--progress` (`cachesim_sweep.cpp:97-118`). A plan that
writes `--l1-assoc 4` invents a knob.

Authoritative defaults: `struct RunConfig`,
`src/lays/cachesim/native/include/cachesim/config.h:27-141` - each field's
default is its member initializer. An unknown key is a hard error, not a
warning (`config.h:152-156`, `src/lays/cachesim/native/src/config.cpp:337`).
Enum spellings: `src/lays/cachesim/native/include/cachesim/enum_names.h`.

**Path convention for the citations below.** Every path is repo-relative
from the `neuro_cache` root. After a file has been given once in full, later
citations use its bare name and line: `config.h` and `enum_names.h` are
`src/lays/cachesim/native/include/cachesim/`; `config.cpp` is
`src/lays/cachesim/native/src/`, `engine.cpp` is that plus `core/`, and
`stats.cpp` is that plus `instrument/`; `cachesim_run.cpp`, `cachesim_sweep.cpp`
and `oracle_io.h` are `src/lays/cachesim/native/apps/`; `pricing.py`,
`model.py` and the `characterization/` directory are
`zoo/archx/zoo/snn_edp/`. Replacement-policy files are always
written in full, because their headers and sources sit in different trees.

`docs/atlas/cachesim_native.md:368-401` has a knob table but is stamped at
commit `6e9aca1` (`docs/atlas/README.md:3`) and predates `81ee1e5`, so it
omits `next_line` entirely. Use `config.h`, not the atlas.

## Operating point: measured on this benchmark, not borrowed

**A committed cacheA row exists for this exact benchmark and
architecture**, so the operating point is measured here rather than read off
a row from another benchmark.

`/work/hdd/bebv/yyu9/neuro_cache_figs_20261116/fig12_edp/demo/all_bench/cases/loas/B09/loas_vgg16_T4_n500/layer_08_core_features_27/sample_00000/cache_a.csv`

```
arch=loas  n_cores=16  workload=loas_vgg16_T4_n500  layer=layer_08_core_features_27
l1_size_bytes=16384  l1_assoc=8   l1_num_sets=32
l2_size_bytes=524288 l2_assoc=16  l2_num_sets=512
line_size_bytes=64   cin_block=16 cout_block=4  weight_bytes=1
layout=khkw_split    inclusion=non_inclusive
l1_mshrs=16  l2_mshrs=32  l1_demand_reserve=1  l2_demand_reserve=1
policy=lru   l2_policy=pf_lru   rrip_bits=2
prefetch_policy=next_access     prefetch_distance=4
l2_prefetch_policy=distance_aware  l2_prefetch_distance=1
l2_prefetch_min_touches=9  l2_prefetch_trigger=touch  l2_prefetch_axis=CIN
```

The production config files themselves are **not in this checkout**
(`zoo/fig12_edp/configs/` does not exist; the root `.gitignore` ignores
`*.json`). Their values survive because cachesim echoes every knob back as
an output column (`src/lays/cachesim/native/src/instrument/stats.cpp:141-165`,
`:176-187`), so a
committed result row *is* the record. Their SHA256s are pinned at
`zoo/fig12_edp/energy_driver.py:33-41`.

The same row carries the behaviour this plan has to reason about:

```
l1_accesses=2454656  l1_hit_rate=0.972230
l2_accesses=1152     l2_hit_rate=0.000000
dram_accesses=81471  dram_bytes=5214144
total_cycles=240720  tick_base_total=153416  stretch_cycles=87304
pf_issued=2452608    pf_coverage=0.031235
l2_pf_issued=30734   l2_pf_coverage=13.149306  l2_pf_wasted=1598
max_wait_depth=0     sim_wall_seconds=1.737395
```

### The finding that shapes the whole design: the L2 sees almost no demand

`l2_accesses = 1152` against `l1_accesses = 2454656`. That is not a typo and
it is not an L1 that never misses - the L1 hit rate is 97.2 %, so roughly
68 k references miss.

The mechanism is in the counter definition. `l2_accesses` and `l2_hits` are
incremented only under `if (r.demand)`
(`src/lays/cachesim/native/src/core/engine.cpp:486-488`). At the operating
point the L1 runs `next_access` at distance 4 and issues 2,452,608
prefetches against 2,454,656 accesses - it covers essentially the entire
stream. A demand reference whose line already has a prefetch MSHR in flight
merges onto that entry and **never becomes an L2 demand probe**. What
reaches the L2 as a demand access is the cold residue.

Three consequences, and they are design consequences, not caveats:

1. **`l2_hit_rate` is 0.0 at the operating point.** Any figure that
   normalizes hit rate to cacheA divides by zero on the L2 series. The
   figure sidesteps this entirely - it reports performance and EDP, neither
   of which is a hit rate - but the appendix CSV must report L2 hit rate
   **unnormalized** for the same reason.
2. **The L2 capacity variants (V1) and the Belady variant (V4) are measured
   against a near-empty demand population.** They may move `l2_hit_rate`
   hardly at all while still moving `dram_bytes`, because the L2 continues
   to service prefetch fills (`l2_pf_issued = 30734`). If V1 and V4 come back
   flat, that is a *result about the prefetcher*, not a failed experiment -
   but the caption has to say which. Q2 asks whether a second,
   prefetch-off operating point should be run so the L2 knobs are legible.
3. **`dram_accesses` is the one memory counter that is not demand-only** -
   the comment at `engine.cpp:573-575` says so outright ("Real channel
   traffic, prefetched or not, which is why this is the one memory counter
   that is not demand-only"). So off-chip traffic remains sensitive to every
   variant even where hit rate is not.

### Capacity caveat: resolved, and what it costs the prose

The scratchpad arch the rest of the paper uses is 32 KiB per node and 2 MiB
shared (`zoo/wt500_fig3cfg/arch.yaml:18-32`: 16 `NodeLevel` instances,
`num_pes: 4`, `weight: 32768`, `NoCLevel weight: 2097152`; `BW_WEIGHT: 8` at
`:12`, so entries == bytes). The cache operating point is 16 KiB / 512 KiB - **half the
L1 and a quarter of the L2**. RQ4 is internally consistent either way, but
RQ3's "At equal on-chip capacity and core count" framing
(`08_evaluation.tex:189`) is not, and RQ4's capacity variants will be read
against it.

**Decided by the user (2026-11-16): keep the 16 KiB / 512 KiB operating
point.** This was the plan's Q1 and it is now closed. The consequence to
carry into the prose: RQ3's "at equal on-chip capacity" sentence and RQ4's
capacity variants describe different capacities, so either that sentence is
qualified or the asymmetry is stated where the cache is introduced. Note
that V2b (32 KiB L1) *is* the scratchpad's per-node capacity, so the figure
already contains the matched-L1 point even though the operating point is
not matched. Nothing in this plan now blocks on it.

---

## The nine variants, mapped to real config keys

Every variant below is the operating point with **one** group of keys
changed. Each row names the keys, the legality rule it has to satisfy, and
the derived geometry.

| # | variant | keys changed | derived | legality |
|---|---|---|---|---|
| V0 | **cacheA** (operating point) | - | L1 32 sets x 8, L2 512 sets x 16 | the committed row above |
| V1a | L2 256 KiB | `l2_size_bytes: 262144` | 4096 lines, 256 sets | 4096 % 16 = 0 (`config.cpp:370-374`) |
| V1b | L2 1024 KiB | `l2_size_bytes: 1048576` | 16384 lines, 1024 sets | 16384 % 16 = 0 |
| V2a | L1 8 KiB | `l1_size_bytes: 8192` | 128 lines, 16 sets | 128 % 8 = 0 |
| V2b | L1 32 KiB | `l1_size_bytes: 32768` | 512 lines, 64 sets | 512 % 8 = 0 |
| V3a | **pure LRU** | `policy: lru`, `l2_policy: lru` | - | `l2_policy` explicit, so the sentinel does not apply |
| V3b | **pure LFU** | `policy: lfu`, `l2_policy: lfu` | - | `lfu` legal at both levels (`enum_names.h:43`, `:56`) |
| V4 | **Belady, L2 only** | `l2_policy: belady` + `--l2-oracle` | `policy` stays `lru` | see below |
| V5 | **L1 prefetch next-line** | `prefetch_policy: next_line`, `prefetch_distance: 1` | L2 untouched | `next_line` requires distance >= 1 (`config.cpp:749-751`) |
| V6 | **L1+L2 next-line ("L12")** | V5 plus `l2_prefetch_policy: next_line`, `l2_prefetch_distance: 1` | - | see the trigger trap below |

**Ten configs: the operating point plus nine variants.** ("R-max" appears in
no row; the user dropped it - see the closed **Q7** below.)

**The count, settled.** The scoping message says the x-axis is
"operating-point cacheA plus the user's variants exactly as listed", and
lists nine variants, which gives **ten bars**; the same message then said
"(9 bars)". **The user closed this on 2026-11-16: ten bars, V0 kept**
(**Q10** below). The table above and the mock already draw ten, because the
operating point has to appear for the normalization rule to be visible. The grid is expressed as a **JSON array
of complete configs**, not `cachesim_sweep`'s `axes` form: that form expands
to the full cross product (`config.h:161-180`, `cachesim_sweep.cpp:40-44`),
which is wrong for a set of named one-off variants. The array form reads
through the same key table, so a typo'd key is still refused
(`config.h:175-179`).

### Three traps in that table that will silently produce the wrong config

**V3a is not a no-op at the L1.** The operating point already has
`policy=lru`; what V3a changes is `l2_policy` from `pf_lru` to `lru`. Write
it explicitly rather than by deletion: `l2_policy`'s default is the sentinel
`PolicyKind::RANDOM` meaning "follow `policy`" (`config.h:66-67`), and
`random` itself **throws** if it ever reaches the policy factory
(`src/lays/cachesim/native/src/replacement/policy.cpp:33-35`). Omitting the key happens to give the
right answer here only because `policy` is `lru`; state it, do not rely on it.

**V3b cannot be written as `policy: pf_lru`-anything.** `pf_lru` and
`pf_lru_rand` are refused on the plain `policy` key - "is L2-only: at the L1
nothing ever sets protection, so it would silently run as plain lru"
(`config.cpp:660-664`). V3b is unaffected (it uses `lfu`), but any later
variant that tries to make the L1 prefetch-aware will hit this.

**V6 must omit `l2_prefetch_trigger`.** The operating point carries
`l2_prefetch_trigger: touch`, and the trigger exists only for
`distance_aware` - "no other policy ever fires on a touch"
(`config.h:121-129`). An **explicit** `touch` with a non-`distance_aware`
policy is *refused*; an unset one is quietly settled to `miss`. So V6's
config is V5's with two keys added and one key **removed**. Likewise
`l2_prefetch_min_touches` is "read only by distance_aware, echoed in the CSV
for every policy" (`config.h:118-120`), so the echoed `9` in V6's output row
is inert - the appendix table must not present it as a setting that applied.

**What V6 does *not* break, contrary to the header comment.**
`src/lays/cachesim/native/include/cachesim/replacement/pf_lru.h:3-6`
says the protected class is "lines filled by the L2 `distance_aware`
prefetch", which reads as though V6 (next-line L2 prefetch) would leave the
protected class empty and degenerate `pf_lru` into plain LRU. It does not.
The engine's gate is policy-agnostic: protection is set whenever the fill was
`is_prefetch_at_issue(...) && !e.demand`, under the comment "the line is an
unused L2 prefetch" (`engine.cpp:625-634`). `distance_aware` is named in the
header because it was the plan context, not because it is the condition.
V6 therefore keeps `l2_policy=pf_lru` live, and V6 is a clean one-knob move.

### Belady: how it actually runs, and why L2-only (position restated)

`BeladyPolicy` keeps a per-slot `next_use_` initialised to `kNever =
INT64_MAX` and evicts the maximum (`src/lays/cachesim/native/src/replacement/belady.cpp:12-22`,
`:46-61`). Future knowledge arrives via `note_next_use` (`:42-44`), fed by a
`NextUseOracle`. It is a strict **two-pass** protocol:

1. run the trace with `--access-log PATH` (8 bytes per demand reference,
   `cachesim_run.cpp:116-118`);
2. re-run with `--l2-oracle PATH` (L2 only) or `--oracle PATH` (both levels),
   built by `read_oracle_lines` (`apps/oracle_io.h:46+`).

Three facts decide it, and all three point the same way on this benchmark:

- Oracles are split per core for the private L1s and unsplit for the shared
  L2 (`oracle_io.h:22-28`): an oracle over the merged stream would leak one
  core's future to another.
- **L1 oracles are exact only while nothing blocks**
  (`cachesim_run.cpp:92-97`): a refused request re-probes and is counted
  twice, shifting every later occurrence index. The row's `max_wait_depth`
  must be 0. The committed cacheA row has `max_wait_depth=0`, so this
  benchmark currently satisfies it - but that is a property of the run, not a
  guarantee, and S1 re-checks it per row.
- **The L2 oracle is approximate under a Belady L1**
  (`cachesim_run.cpp:98-101`, `cachesim_sweep.cpp:69-75`): a Belady L1
  changes which references miss, so the L2 sees a different sequence, not a
  reordering.

**Position: Belady at L2 only**, `l2_policy=belady` with `--l2-oracle`, L1
left at `lru`. It is exact, it needs no per-core L1 oracle buckets (which
`oracle_io.h:36-39` measures at 66 MB of a 70 MB peak on one sample), and it
is the bound the paper wants: the replacement question in this design lives
at the L2, where `pf_lru` is.

**Caveat specific to the redefined experiment.** Because the L2 demand
population here is 1,152 accesses (above), a *demand-exact* L2 Belady bound
may be nearly indistinguishable from V0 - the oracle only orders the
references the access log records, and the access log records demand
references only (`engine.cpp:486-491`, the `observe` call sits inside the
same `if (r.demand)`). Prefetch fills, which are the bulk of what occupies
the L2 here, are **not** in the oracle. So V4 as specified bounds *demand*
replacement, not total L2 occupancy management. That is a genuine limit of
what Belady can say about this design, and the caption must say it rather
than letting a flat V4 read as "replacement is already optimal". Q3.

**No Belady run has ever been committed.** There is no row with
`policy=belady` or `l2_policy=belady` in any CSV in the repo or on the Lustre
snapshot, so its wall-clock and peak RSS are unmeasured beyond the allocation
figure above. The first Belady point is a measurement, not a lookup - S1
prices it before S2 commits.

### "R-max": dropped by user decision

The dispatch named a tenth variant, "R-max", without defining it. I searched the cachesim source, the config
key table, the enum spellings, the zoo, the docs and the paper source for
`r-max`, `r_max`, `rmax` and `R_{max}`: **the string occurs nowhere.** It
was not a config key, not an enum value, not a paper symbol, so the plan
listed candidates rather than inventing one - the strongest being
`l2_policy: rrip` at `rrip_bits: 8`, the maximum
(`src/lays/cachesim/native/src/replacement/rrip.cpp:11`, enforced `config.cpp:650-651`; the policy's
own field is literally `max_rrpv_`,
`src/lays/cachesim/native/include/cachesim/replacement/rrip.h:23`), with
`l1_demand_reserve`/`l2_demand_reserve` at the `-1` sentinel - "the trace's
maximum burst span in lines" (`config.h:75-78`) - as the runner-up.

**The user has dropped the variant entirely.** Q7 is closed and no R-max
config is built. Recorded here only so the decision is not relitigated, and
because both candidates remain unexplored knobs if a later section wants
them: `rrip_bits` has never been run at anything but 2, and the demand
reserves have never been run at anything but 1.

---

## Metrics: performance and EDP, defined exactly

The reported set is **two metrics**, and both are derived rather than read
straight off a counter. Writing them down precisely matters more here than
it did with four raw counters, because "performance" is not a column in any
CSV in this project.

**Latency -> seconds.** cachesim reports `total_cycles` (`stats.cpp:168`).
archx converts with a fixed clock: `seconds = cycles / (frequency_MHz * 1e6)`
(`zoo/archx/zoo/snn_edp/pricing.py:72`), at 500 MHz
(`characterization/cache.architecture.yaml:2`, `frequency: 500`; asserted in
`test_legacy_counts.py:64` as `T_s == cycles/(500*1e6)`). The result is the
`T_s` column.

**Performance** is the reciprocal of that latency:

> `performance = 1 / T_s = (frequency_MHz * 1e6) / total_cycles`

reported **normalized to cacheA**, i.e. `T_s(V0) / T_s(variant)`, which is a
speedup: 1.0 is the operating point, above 1.0 is faster. Because the clock
is fixed and identical across every variant, normalized performance is
exactly `total_cycles(V0) / total_cycles(variant)` - the cycle counts alone
decide it, and the frequency cancels. **Relation to latency: it is its
reciprocal.** A variant at 1.25x latency is at 0.80x performance. That
inversion is why the two panels of the figure point in opposite directions
(see "Figure form").

**EDP** is energy x time, and the project already computes it one way:

> `EDP_nJ_s = (E_dyn_nJ + E_leak_nJ) * T_s`

(`zoo/archx/zoo/snn_edp/pricing.py:74`), and the pipeline *asserts* that
identity rather than trusting it - `stage2.py:289-290` raises "layer EDP
differs from energy times latency" if a row violates it to within
`rel_tol=1e-12`. Note `E_leak_nJ` is itself proportional to `T_s`
(`pricing.py:72`, `leakage = power * seconds * 1e6`), so EDP is
super-linear in latency: a slower variant is penalised twice.

**Whole-model EDP follows the paper's rule, not the per-layer sum.** The
paper states `EDP = sum(E) * sum(t)` (`08_evaluation.tex:83-85`, "Whole-model
results sum all kept layers of a network before forming ratios"), and the
pipeline carries both aggregations as distinct fields - `model_EDP_nJ_s`
beside `sum_layer_EDP_nJ_s` (`zoo/fig12_edp/stokes/stage2.py:315`). **Use
`model_EDP_nJ_s`.** They are not equal, and reporting the wrong one is a
silent error that no assertion catches.

### The counters the figure does not plot, and why they still matter

Hit rate, off-chip traffic and the latency decomposition leave the figure
but not the plan. They stay as **S1 gates and appendix columns**:

- `l1_hit_rate = l1_hits / l1_accesses` (`stats.cpp:277`), `l2_hit_rate`
  (`:280`), both demand-only (`engine.cpp:486-488`). `l2_hit_rate` is 0.0 at
  the operating point, which is the diagnostic that explains a flat V1/V4.
- `dram_bytes = dram_accesses * line_size_bytes()` (`stats.cpp:282`), with
  prefetch fills included (`engine.cpp:573-575`). This is the counter that
  *causes* most of the EDP movement, so when a bar moves it is the column a
  reader goes to for the mechanism.
- `stretch_cycles = total_cycles - tick_base_total` (`stats.cpp:167-172`).
  `tick_base_total` is the trace's own timeline and is **identical across
  all ten configs** because the trace is, so every performance difference in
  the figure lives entirely in `stretch_cycles`. At V0 it is 87,304 of
  240,720 cycles, 36 %. This is worth one caption sentence: the bars move by
  at most that 36 % of the total, because the other 64 % is work the memory
  system cannot change.

**Do not confuse the two `dram_bytes`.** cachesim's is older, from `34c9836`
(2026-08-20); commit `4b068a9` added a *nocsim* per-variable `dram_bytes`
(weight/psum/vmem). Same name, different counter, different simulator. RQ4 is
cache-only and means cachesim's.

### Energy: three blockers, and they are smaller than they were

1. **The cache price rows are pinned to one geometry.**
   `zoo/archx/zoo/snn_edp/characterization/cache.architecture.yaml:6` queries
   `cacti_fn` with `{class: cache, size: 131072, width: 512, associativity: 8,
   bank: 1}` and `:13` with `{size: 4194304, width: 512, associativity: 16,
   bank: 1}` - sizes in **bits**, so exactly 16 KiB and 512 KiB. **V1 and V2
   invalidate those rows.** But only V1 and V2 do: V3-V6 change no geometry,
   so **six** of the ten configs - V0, V3a, V3b, V4, V5, V6 - price against
   the existing table unchanged.
   The redefinition cut the re-harvest from 19 geometries to **4**
   (256 KiB, 1 MiB at the L2; 8 KiB, 32 KiB at the L1).
2. Re-pricing is mechanical, not new code: `cacti_fn` is a live model and the
   table is regenerated by
   `zoo/archx/zoo/snn_edp/characterization/shared_harvest.py:24-39`, which
   calls `query` with an arbitrary `{class, size, width, associativity, bank}`.
3. **Prefetch control energy is currently zero.** Nine prefetch operation
   prices are zeroed by `characterization/pricing_policy.json` - the yaml
   says so in its own comment at `cache.architecture.yaml:17` ("Nine
   operation prices are zero by characterization/pricing_policy.json; counts
   remain active") - and several cache rows are unpriced placeholders
   (`"placeholder": "pending-ASAP7-synthesis"`, e.g.
   `zoo/archx/zoo/snn_edp/energy_table.json:287-311`), surfacing as
   `incomplete_reasons` (`pricing.py:75`). **V5 and V6 are the prefetch variants, and on them the
   only energy that moves is DRAM and array accesses.** Since EDP is half
   energy, an RQ4 EDP claim about prefetch policy is, today, a claim about
   the traffic that prefetching causes plus the latency it changes. With
   only two metrics in the figure there is no traffic panel to carry that
   mechanism, so it has to be in the caption. Q4.

Two mechanical guards: `zoo/fig12_edp/energy_driver.py:33-41`
(`CACHE_CONFIG_SHA256` / `check_cache_configs`) **rejects any edit** to the
production configs, so this DSE must use its own config directory rather than
editing those; and `model.py:119` unpacks `row,=`, so a multi-row
`cachesim_sweep` CSV must be split into single-row files before pricing. No
sweep-to-energy glue exists anywhere in the tree - that is new code, and it
is the only new code this plan needs.

All energy is additionally `NG45_INTERIM` with `incomplete = True` until
ASAP7 synthesis lands. The interim status is stated at
`zoo/archx/zoo/snn_edp/characterization/NANGATE45.md:3` ("interim until
ASAP7 synthesis"); the `NG45_INTERIM` token and the `incomplete` flag
themselves live in `characterization/energy_table_nangate45.json` and
`characterization/build_nangate45.py`, not in that markdown file. The committed
B09 rows confirm it: every one carries `incomplete = True`
(`.../stokes/results_ng45_20261114/stage2/results_ng45.csv`).

---

## Workload, and what already exists for it

**Benchmark**: `B09/loas_vgg16_T4_n500`, dataset `cifar10/test`, T = 4,
N = 500, 13 captured layers, of which 12 are replayable 3x3 stride-1 convs
and layer 13 is a 1x1 GEMM classifier
(`zoo/wt500_fig3cfg/layer_shapes.md:217-231`). Shapes:

| # | layer | CIN | COUT | HO=WO | weight footprint |
|---|---|---|---|---|---|
| 01 | `layer_01_core_features_3` | 64 | 64 | 32 | 36 KiB |
| 02 | `layer_02_core_features_7` | 64 | 128 | 16 | 72 KiB |
| 03 | `layer_03_core_features_10` | 128 | 128 | 16 | 144 KiB |
| 04 | `layer_04_core_features_14` | 128 | 256 | 8 | 288 KiB |
| 05 | `layer_05_core_features_17` | 256 | 256 | 8 | 576 KiB |
| 06 | `layer_06_core_features_20` | 256 | 256 | 8 | 576 KiB |
| 07 | `layer_07_core_features_24` | 256 | 512 | 4 | 1.1 MiB |
| 08 | `layer_08_core_features_27` | 512 | 512 | 4 | 2.25 MiB |
| 09 | `layer_09_core_features_30` | 512 | 512 | 4 | 2.25 MiB |
| 10 | `layer_10_core_features_34` | 512 | 512 | 2 | 2.25 MiB |
| 11 | `layer_11_core_features_37` | 512 | 512 | 2 | 2.25 MiB |
| 12 | `layer_12_core_features_40` | 512 | 512 | 2 | 2.25 MiB |

**Note on the thirteenth layer.** The replay rule admits 1x1 as well as
3x3 stride-1 - `KERNEL_PADDING = {1: 0, 3: 1}` with a stride-1 check at
`src/lays/weight_trace_gen/trace.py:27`, `:111`, rejecting anything else
with "the arch models replay only 1x1 or 3x3 stride-1 layers". So
`layer_13_core_classifier` is *not* excluded by the kernel rule, and
`docs/plans/2026-11-04-cin-khkw-concat-layout-plan.md:110-111` (which says
3x3 only) is stale while `zoo/fig2_hw_n_sweep/README.md:26-27` is correct.
Why the campaign nonetheless carries 12 layers and not 13 for this capture
is **not determinable** from the committed artifacts; S0 settles it before
the corpus is sized. The plan assumes 12 and notes that a thirteenth would
add one small GEMM case per config.

(Footprint = CIN x COUT x 9 x `weight_bytes`, `weight_bytes = 1`.) Eight of
the twelve exceed the 512 KiB L2 - layers 05 through 12 - and five of those
(08-12, at 2.25 MiB) exceed it by more than 4x, so the capacity
variants V1/V2 have something to bite on even though the demand population is
thin. `core.features.0` is not captured - "weight-bearing input is not
exactly binary; excluded from capture" (`layer_shapes.md:233`).

**Proposed scope: all 12 replayable convs x 5 samples = 60 cases per
config.** There is no reason to subset: one
benchmark with 12 layers is small enough to run whole, and a design-space
section that subsets its only benchmark invites the question of which layers
were dropped.

### What exists, exactly

**Reusable outright:**

- **The operating-point row itself** - the full 116-column cacheA record on
  `layer_08`, sample 0, quoted above. One of the 60 V0 cases is therefore
  already measured, and S1 uses it as a byte-identity gate rather than as
  data.
- **Energy-level coverage of the whole benchmark**:
  `.../stokes/results_ng45_20261114/stage2/results_ng45.csv` holds 180 rows
  for `capture = B09/loas_vgg16_T4_n500` - 12 layers x 5 architectures x
  {cacheA, cacheB, spad}, sample 0 only. For `arch = loas` specifically there
  are 36 rows (12 layers x 3 arms). These give `total_cycles`, `T_s`,
  `E_dyn_nJ`, `E_leak_nJ`, `area_mm2` and `EDP_nJ_s` **for V0 on every
  layer**. Spot values for `arch=loas`, cacheA: `layer_01` 99,110 cycles /
  90.4 uJ; `layer_08` 240,720 / 1.226 mJ; `layer_09` 497,636 / 1.920 mJ;
  `layer_12` 107,072 / 633 uJ.
  **Limitation, and it is the decisive one:** this file is the *energy*
  schema (63 columns), not the cachesim schema. It has no `l1_hit_rate`, no
  `dram_bytes`, no `stretch_cycles`. So it covers V0's latency and energy
  across the benchmark but **neither of the other two reported metrics**, and
  it covers no variant but V0.
- **Local spike-input traces.**
  `examples/input_trace/delta/B09/loas_vgg16_T4_n500/` holds all 13 layer
  tensors as `.npy` plus `meta.json`, **349 MB, present on this machine**.
  This is what makes the plan cheap: the inputs this benchmark needs are
  already here, so the weight-trace corpus can be regenerated locally
  without touching the campaign.

**Covers nothing:** `zoo/concat_vs_khkw` (different layers, no-prefetch
corner), `zoo/demo_l2pf` (different benchmark, reduced schema, and its rows
carry the **pre-rename** spellings - `next_access` and `distance_aware` were
`next_burst` and `next_tile` before commit `0c55f2f`,
`docs/atlas/README.md:6` - so any join against them needs an explicit
mapping, not a column join), `zoo/set_utilization` (its `ways_sweep.py:19`
looks like an associativity sweep but `RESULTS.md:19` says outright these
are "static reachability and distribution measurements, **not** measured
occupancy or hit rates"), `zoo/fig3_design_space` (scheduler mapspace, no
cachesim rows).

**New work:** the 10-config grid file; the retained `.wcts` corpus for this
benchmark; the sweep-to-energy splitter; the `cacti_fn` re-harvest for 4
geometries; the first Belady run in the project's history; the plot.

### Trace retention is still the structural constraint

cachesim replays `.wcts` weight-trace streams. The WT500 campaign **never
stores them** - ~23 TB gzipped against a 1 TB quota - so
`zoo/wt500_fig3cfg/stokes/sim_shard.py` deletes each one as soon as its
results are durable (`_delete_consumed`, `sim_shard.py:189-203`;
`zoo/wt500_fig3cfg/PAUSE-2026-11-11.md:64-73`). And `sim_shard.py:263` takes
exactly **one** `--config` (`--shard-dir` is `:262`). I confirmed the consequence directly: a search of
the whole Lustre snapshot for `*.wcts` returns only pytest fixtures under
`fig12_edp/nocsim/.testtmp/`. **No production weight trace survives
anywhere.**

So RQ4 cannot ride a campaign wave; it must own a retained corpus, generated
once and replayed 10 times. That is exactly what `zoo/concat_vs_khkw` did,
down to the per-stream `sha256`/`bytes`/`tiles`/`cores` in its
`provenance.json`, and this plan copies that model.

### Compute cost, measured

- **Replay.** The committed cacheA row on `layer_08` - one of the heavier
  layers, at this exact geometry and core count - took
  `sim_wall_seconds = 1.737395`; the matching cacheB row took 1.854850.
  `zoo/concat_vs_khkw/results.csv`, 120 runs at a comparable geometry on
  smaller layers, gives min 0.20 s, median 0.47 s, max 1.18 s.
  Taking ~1.0 s as a benchmark-wide mean and 1.9 s as the worst case:
  **10 configs x 12 layers x 5 samples = 600 runs = ~10 CPU-minutes, worst
  case ~19.** At 8 workers, under three minutes of wall time.
  Belady doubles its own share (access-log pass + oracle pass), adding one
  further ~10 CPU-minutes for the V4 column.
- **Generation.** Weight-trace generation is measured at 4.44 us per MAC
  cycle, range 4.15-4.84 (`zoo/fig2_hw_n_sweep/T1_perf_report.md:86`; the
  per-stage table is `:72-77`, summarized at `:90` as "under 2 % of the
  total" for the nocsim stage). This is the dominant cost and it is paid
  once. I cannot convert it to a total for this benchmark without the
  per-layer MAC-cycle counts, which are not recorded in any committed
  artifact I found - **not determinable here; S0 measures it on layer 01 and
  extrapolates by footprint before committing to the full 12.**
- **`cacti_fn` re-harvest for 4 geometries: not determinable** - no timing is
  recorded in `shared_harvest.py` or its outputs. S1 measures one.
- **Belady wall-clock and peak RSS: not determinable** - never run. S1
  measures one.

Memory is real and per-process: `scripts/pipeline.py:56-58` records a 14 GB
RSS peak for the largest single command in `make demo`, and
`cachesim_sweep --max-engines` (default 256) exists precisely so an oversized
grid fails at startup instead of OOMing hours in (`cachesim_sweep.cpp:76-79`).
At 10 configs that guard is never near.

---

## Execution chain

- **S0 - operating point and corpus.** Reconstruct the cacheA config from the
  echoed columns above into `zoo/cache_dse/configs/base.json` and record its
  SHA256. Generate and retain the 12-layer x 5-sample `.wcts` corpus from the
  local `.npy` inputs, with per-stream hashes in `concat_vs_khkw`
  `provenance.json` style. Time layer 01's generation and extrapolate before
  running the other eleven. No sweep yet.
  *Gate*: if the extrapolated generation cost exceeds one node-hour, stop and
  re-scope to a layer subset before generating.
- **S1 - identity gate and cost pilot.** Run V0 on
  `layer_08_core_features_27`, sample 0, and require it to reproduce the
  committed `cache_a.csv` row **byte for byte** on every counter column. If
  it does not, the binary or the config has moved since the campaign and the
  sweep stops. In the same pass run **one** Belady L2 point and **one**
  `cacti_fn` re-harvest, recording wall time and peak RSS - the three numbers
  this plan cannot currently state. Assert `max_wait_depth == 0` on every row
  and make it fatal, not a warning, since the L1 oracle's exactness depends
  on it.
  *Gate*: reviewed before S2.
- **S2 - the sweep.** Emit the 10-config JSON array; run `cachesim_sweep
  --config-grid` over the corpus; one CSV, 600 rows. V4's access logs come
  from a prior V0 pass over the same trace and layout -
  `cachesim_sweep.cpp:65-68` takes one `--oracle` for a whole grid, which is
  safe only under exactly that condition.
- **S3 - energy.** Split the sweep CSV into single-row files; re-harvest
  `cacti_fn` for the 4 changed geometries (V1a, V1b, V2a, V2b); price all ten
  configs; carry `incomplete_reasons` through to the output rather than
  dropping it.
- **S4 - aggregate.** `outputs/cache_dse.csv`: one row per
  (variant, layer, sample), plus a per-variant whole-model aggregate
  carrying **performance and EDP normalized to V0** and the diagnostic
  columns unnormalized. Aggregation follows the paper's own rule - sum over
  layers before forming ratios, never average per-layer ratios
  (`08_evaluation.tex:83-85`, "Whole-model results sum all kept layers of a
  network before forming ratios"), which for EDP means `sum(E) * sum(t)`,
  the `model_EDP_nJ_s` field and not `sum_layer_EDP_nJ_s`
  (`stage2.py:315`).
- **S5 - plot.** `plot.py` -> the figure below, plus the full per-variant
  table as an appendix CSV.
- **Gates overall**: Q1, Q7 and Q10 are **closed by user decision** (keep the
  16 KiB / 512 KiB operating point; drop R-max; ten bars with V0 kept), so
  nothing blocks S0. The user answers **Q2 and Q3** before S2, because each
  changes what S2 runs or how many configs it runs; **Q8** before S2 as well,
  since the float decision determines the figure's column width and therefore
  its layout;
  **Q4, Q5 and Q6** at figure sign-off, since they change what is drawn
  rather than what is measured; **Q9** is prose and gates paper integration
  only. S1's identity check and cost pilot are reviewed before S2; the
  reviewer sees every implementation commit; figure sign-off before paper
  integration.

---

## Figure form: a bar chart, two panels

**Two stacked panels sharing one categorical x-axis of ten configs.
Top panel: performance, normalized to cacheA, higher is better. Bottom
panel: EDP, normalized to cacheA, lower is better. Bars, from zero.**

x-axis order, left to right, grouped by what the knob touches:

```
  cacheA | L2 256K  L2 1M | L1 8K  L1 32K | LRU  LFU | Belady | L1 nl  L12 nl
   (V0)  |  (V1a)  (V1b)  | (V2a)  (V2b)  | (V3a)(V3b)|  (V4)  | (V5)   (V6)
  base   |   capacity     |   capacity    | replacement|  bound |  prefetch
```

**Why bars are right here, and the one condition they depend on.**
Performance and EDP are ratios of non-negative quantities with a meaningful
zero, and both axes start at zero, so bar length is proportional to the
quantity and every visual comparison is the arithmetic comparison. That
condition is load-bearing, not incidental: on a **truncated** axis a bar
misstates every comparison by the amount of the truncation, and the error is
largest exactly where the differences are smallest. **If a later revision
truncates either axis, bars stop being correct here and the encoding has to
change with it.**

**Why two panels rather than two bar groups per config.** Both encodings
were on the table. Paired bars put performance and EDP side by side at each
config, which is compact; but the two metrics have **opposite polarity** -
taller is better in one and worse in the other - and interleaving opposite
polarities in one axis is the single most reliable way to get a bar chart
misread. Separate panels let each carry its own "higher/lower is better"
label and its own 1.0 reference line. Stated as Q6 in case the user prefers
the compact form.

Other properties the mock implements:

- a dashed horizontal rule at 1.0 on both panels, labelled `cacheA`, so a
  bar's relation to the operating point is readable without arithmetic;
- **Belady drawn distinctly** - hatched fill and an open outline, plus a
  light band spanning from its bar back to the 1.0 rule. It is a bound, not
  a buildable design, and a reader who reads it as the eighth design point
  draws the wrong conclusion. This is the dispatch's "keep the Belady bound
  visually distinct" requirement;
- light group separators and group captions (capacity / replacement / bound
  / prefetch) under the axis, because the ranking claim is between groups
  rather than between adjacent bars;
- **error bars are drawn** (`cache_dse_mock.py:59-60`, `:76-77`): five
  samples per layer per config give a spread, and a bar with no whisker
  invites over-reading small differences. The appendix CSV carries the
  spread as well. Q5 asks whether min-max or stddev.

**Rejected alternatives.**
(a) *Normalized dot plot.* It handles five or more metrics well; with two it
spends the reader's effort on an encoding they have to learn first.
(b) *Small multiples, one panel per config.* Ten panels for ten bars.
(c) *Slope chart.* A slope encodes an ordered pair; these are nine
alternatives to one baseline, not transitions.
(d) *Absolute values rather than normalized.* Performance in inferences/s
and EDP in nJ-s differ by orders of magnitude across the twelve layers, so
the whole-model absolutes hide the per-knob effect the section is about. The
absolutes belong in the appendix table, and the caption gives cacheA's.

`cache_dse_mock.py` renders this shape with invented numbers; the config
names, the config keys, the benchmark and the metric definitions are real.

## Open questions

**Closed by user decision** (recorded so they are not relitigated):

- **Q1 - CLOSED.** Capacities: keep the existing 16 KiB L1 / 512 KiB L2
  cacheA operating point. The asymmetry against the scratchpad's 32 KiB /
  2 MiB stands and is stated in prose instead; RQ3's "at equal on-chip
  capacity" sentence needs qualifying.
- **Q7 - CLOSED.** "R-max" is dropped. No *variant* in this plan moves
  `rrip_bits` or the demand reserves. (The operating point itself carries
  `rrip_bits=2` in its echoed row, and S0 rebuilds the base config from
  those columns; that value is inherited unchanged by all ten configs.)

**Open:**

- **Q2.** At the operating point the L1 prefetcher absorbs the stream and the
  L2 sees 1,152 demand accesses out of 2.45 M, so `l2_hit_rate = 0.0` and the
  L2 knobs (V1, V4) are measured against a near-empty demand population.
  Accept that and caption it, or add a **second operating point with L1
  prefetch off** so the L2 variants are legible? Adding one doubles the run
  (600 -> 1,200 rows, still ~20 CPU-minutes) and doubles the figure.
  **Propose: run the prefetch-off corner in S1 as a diagnostic**, decide
  after seeing whether V1/V4 are flat, and keep the paper figure
  single-operating-point unless they are. This matters more under the
  two-metric scope than it did before: with no traffic panel, a flat V1 bar
  gives the reader nothing to diagnose it with.
- **Q3.** V4's Belady bound is over **demand** references only - the access
  log records only `r.demand` (`engine.cpp:486-491`) - while most L2
  occupancy here comes from prefetch fills. Caption it as a demand-replacement
  bound, or drop V4 and report it in text only? **Propose captioning**; a
  bound that is honest about its scope still answers "is replacement where
  the headroom is".
- **Q4.** EDP is half energy, and on V5/V6 the energy half moves only through
  DRAM traffic because the nine prefetch operation prices are zeroed pending
  ASAP7 (`cache.architecture.yaml:17`). Every EDP bar also inherits
  `incomplete = True` under `NG45_INTERIM`
  (`characterization/NANGATE45.md:3`). Caption the EDP panel with that
  caveat, or hold the EDP panel until the ASAP7 table lands and ship the
  performance panel alone first? **Propose captioning and shipping both**,
  since the performance panel alone cannot make the section's argument.
- **Q5.** Error bars: five samples per (config, layer) give a spread, and the
  whole-model aggregate hides it. Draw min-max or stddev whiskers on both
  panels, or report the spread in the appendix only? **Propose whiskers**,
  since a bar with no spread invites over-reading small differences.
- **Q6.** Two stacked panels (performance above, EDP below), or two bar
  groups per config in a single panel? **Propose stacked panels**, because
  the two metrics have opposite polarity and interleaving them in one axis
  reads wrong. The mock draws the proposal.
- **Q10 (bar count) - CLOSED by the user, 2026-11-16: "ten bars is right,
  keep V0".** The scoping message's x-axis sentence - "operating-point cacheA
  plus the user's variants exactly as listed" - gives ten bars, while the same
  message said "(9 bars)"; ten is correct and V0 stays as the visible
  baseline, which is what the plan and the mock already draw. Nothing in the
  figure changes.
- **Q8.** RQ4 declares no float: there is no `\begin{figure}`, no
  `\begin{table}` and no `\label{fig:eval-cache-dse}` anywhere in
  `08_evaluation.tex:202-207`; the nearest float belongs to RQ3
  (`fig:eval-spad-cache`, a `figure*` at `:194-200`). Add
  `\label{fig:eval-cache-dse}` as a single-column figure after
  `fig:eval-spad-cache`, plus an appendix table? **Propose yes**, and
  single-column - two stacked panels of ten bars does not need `figure*`.
- **Q9 (prose).** RQ4's sentence at `08_evaluation.tex:206` promises "hit
  rate, off-chip traffic, latency, and energy", and the figure now reports
  performance and EDP. The sentence has to change, and so does `:205`, which
  promises associativity, line size and line layout - none of which are in
  the nine variants. **Propose rewriting both lines** to match this plan; the
  dropped quantities survive as the appendix table.
