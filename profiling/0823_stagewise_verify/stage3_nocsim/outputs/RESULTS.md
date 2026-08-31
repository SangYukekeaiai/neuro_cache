# Stage 3 results: nocsim

Run 2026-08-24 over four layers x five samples, **arm M only** (the 16-node
arch). `run_stage3.py`, `conda run -n base`. 20 runs, 2 minutes wall. Logs in
`logs/`, machine-readable record in `stage3_results.json`, transaction lists in
`tc/` (25 MB).

Arm S (single-node) weight traces exist under
`weight_traces_single_node/` from increment 4 and can be run without
regenerating anything. They are not included here.

Two model defects were found and fixed before this ran, both by challenging an
earlier claim of an exact 16x cross-arm ratio. They change every number in this
file and are documented in section 5.

## 1. What ran

| Input | Path | Note |
|---|---|---|
| schedules, 4 | `stage2_weight_trace/inputs/schedules/loas/` | unchanged from Stage 2 |
| arch, 1 | `stage3_nocsim/inputs/arch/loas_inst16_node32kb_noc2MiB_pe16.yaml` | `DRAM_LATENCY: 0.25` |
| layer shapes, 4 | written from each schedule's own `workload` block | cannot drift from the schedule |
| weight traces, 20 | `stage2_weight_trace/outputs/weight_traces/` | 166 MB |

SHA-256 of every one is in `../inputs/MANIFEST_stage3.json`.

The arch is a Stage 3 copy rather than Stage 1's file: Stage 1's MANIFEST
records its sha, and that record of what ran on 08-23 was left intact. The only
difference is `DRAM_LATENCY`.

## 2. Results

```
tag  samples 0..4        total_cycles      dram    unicast      compute/node
V8       599,784 ..    600,508          36,864    592,000   146,200 .. 162,512
R9        66,910 ..     86,384           2,304     37,136    66,910 ..  86,384
V9       605,662 ..    606,135          36,864    592,000   302,864 .. 313,776
R16    1,188,091 ..  1,188,207          73,728  1,184,000   123,108 .. 126,572
```

`compute_per_node` is `count_cycles / 16`. eventsim's `count_cycles` sums every
node's COUNT, so the per-node figure is what actually competes with DRAM and
NoC on the critical path.

## 3. Three of four layers are bounded by the global-buffer port

`unicast_cycles` is 98.6% to 99.7% of `total_cycles` on V8, V9, and R16. DRAM is
3% to 6%. Per-node compute is a quarter to a half of the total and never
reaches the critical path.

The reason is a rate difference, not an amortization difference. Measure the
bytes on each side:

| tag | layer weights | DRAM -> GB | GB -> nodes |
|---|---:|---:|---:|
| V8 | 2.36 MB | 4.72 MB (2.0x) | 4.74 MB (2.0x) |
| R9 | 0.29 MB | 0.29 MB (1.0x) | 0.30 MB (1.0x) |
| V9 | 2.36 MB | 4.72 MB (2.0x) | 4.74 MB (2.0x) |
| R16 | 1.18 MB | 9.44 MB (8.0x) | 9.47 MB (8.0x) |

**The two stages move the same bytes.** Each node needs a different weight
slice, so the global buffer amortizes nothing: everything that arrives is
forwarded once. What differs is the charged rate.

```
DRAM port   0.25 cycles per 256-bit packet   =  128 B/cycle  =  64 GB/s at 500 MHz
GB port     4    cycles per 256-bit packet   =    8 B/cycle  =   4 GB/s at 500 MHz
```

16x, which is exactly the ratio between the two columns of the table. The NoC
figure comes from `FLITS_PER_PACKET = 4` (`core/transaction.py:23`), applied in
`EventSim.h:171` as `route.size() + size * FLITS_PER_PACKET`.

So the reported bottleneck is a statement about one constant and one modelling
choice: that a packet costs 4 cycles at a port, and that `combine()` emits all
16 node transfers from a single global-buffer actor. Neither mattered while
`DRAM_LATENCY` was 34x too slow. Both decide the answer now.

R16 is the extreme because its 32 x 2 tiling refetches the layer's weights 8
times; R9's 2 x 64 fetches them once.

**R9 is the exception** and is compute-bound at exactly `compute_per_node`. Its
tiling puts almost everything in NoC steps, so it moves 16x less weight data
than R16 for comparable compute.

## 4. What the per-tile cycles bought

The question increments 1 through 4 existed to answer: does charging each step
its own measured `mac_cycles`, rather than a static dense formula, change a
reported runtime?

```
tag   compute varies across the 5 samples   ->   total varies   passthrough
V8                16,312                              724           4.4%
R9                19,474                           19,474         100.0%
V9                10,912                              473           4.3%
R16                3,464                              116           3.3%
```

On R9 the sparsity signal passes through intact: a 22.5% spread in compute is a
22.5% spread in runtime. On the other three the GB port absorbs 96% of it, and
the layer takes the same time whether its input is sparse or dense.

The per-tile accuracy is therefore real but conditional. It is visible only on
layers whose tiling keeps weight traffic off the critical path. On this arch
that is one layer in four.

For scale, the static dense formula overcharges per-tile compute by 30x to 58x
(58.1x V8, 54.6x R9, 30.2x V9, 38.3x R16), so on R9 the dense model would have
reported a runtime roughly 55x too large.

## 5. Two model fixes

Both were found by challenging the claim that arm M showed an exact 16x
improvement over arm S. It did not; the quantity being compared was
`count_cycles`, an accumulator of total work, not a latency.

**5.1 eventsim never let a dependency delay its successor.**

`EventSim.h:167` read `(void)finish_time;`. The completion queue released a
successor onto the ready queue and discarded the time its input arrived. Start
times came only from `get_actor_free(actor)`, so every actor's timeline packed
gaplessly from cycle 0, and `total_cycles` reduced to the max over actors of
the sum of durations on that actor. A COUNT whose weights arrived at cycle 1000
still ran at cycle 0.

The header comment at `EventSim.h:15` had described the correct behavior all
along ("a transaction dispatches once its dependencies have all finished"), as
does the tc.csv format spec CoSA published for this file layout.

Fixed with a `finish_time` vector and
`start = max(get_actor_free(actor), max over deps of finish_time[dep])`.
`tests/test_eventsim_deps.py` is new, 5 checks driving the compiled binary on
hand-written CSVs. Check M pins that independent work on separate actors still
overlaps, so a fix that merely serialized everything would fail it.

**5.2 `DRAM_LATENCY` was 34x too slow.**

17 was inherited from CoSA's `gen_tc_io.py:778`, where it weights an analytic
*bits-moved* metric that ranks mappings for the MIP. That metric never carried
cycle units, and CoSA never compares it against compute time. CoSA's actual
cycle numbers come from its SystemC simulator in `src/nocsim/sim/noc/`, which
drives DRAMSim2 against a DDR2 device model, and whose DRAM transaction size is
32 bytes, exactly one packet here.

Carried into eventsim as per-packet port occupancy, 17 implied
`32 B / 17 cycles` = 1.88 GB/s at 1 GHz, and made every layer DRAM-bound.

Now **0.25**, from `32 B x 0.5 GHz / 64 GB/s`. The value stays fractional and
the *product* `size * dram_latency` is ceiled once per transaction, in both
`EventSim.h` and `core/generator.py`. Rounding the factor itself to an integer
would be a 4x bandwidth error; ceiling the product keeps the rate exact and
caps the error at one cycle per transaction.

To set it for other hardware: `dram_latency = 32 B x f / BW`. To read one back:
`BW = 32 B x f / dram_latency`.

`DRAM_LATENCY` reaches only nocsim; the MIP solver never reads it. So no
schedule and no weight trace was invalidated. 414 config files updated.

The two fixes move in opposite directions and had to be settled together:

```
              V8 total     R16 total
17         2,549,956     5,052,376     inherited: 1.88 GB/s at 1 GHz
1            607,420     1,195,088     16 GB/s at 500 MHz
0.25         600,508     1,188,176     64 GB/s at 500 MHz
```

## 6. Verification

Four test files pass: `test_step_cycles.py`, `test_combine_cycles_table.py`,
`test_sim_weight_trace.py`, `test_eventsim_deps.py`.

Plan check 7 (cross-arm MAC totals in the same range) needs restating rather
than running. Increment 4 measured the two arms' per-`(tile, core)` work
multisets as **identical**, so their MAC totals agree to the cycle by
construction: arm M groups 16 of arm S's work units into one tile. That
confirms the two arms partition the same work; it says nothing about
performance. The informative cross-arm comparison is `total_cycles`, which
needs the arm S runs.

## 7. Open items

**The GB port model decides three of four layers.** Two assumptions carry it:
`FLITS_PER_PACKET = 4` as the port's cycles-per-packet, and `combine()` emitting
all 16 node transfers through one actor. Both should be checked against the
intended hardware before this bottleneck is treated as a result.

**No access-latency term exists anywhere.** `dram_latency` is occupancy per
packet. A real controller's access latency shows up once at the ramp, not on
every packet, and the model has no place to put it. This became visible only
after 5.1, since before it nothing waited for anything.

**Arm S is not run.** Its 20 traces exist. Running them would make the cross-arm
`total_cycles` comparison available.
