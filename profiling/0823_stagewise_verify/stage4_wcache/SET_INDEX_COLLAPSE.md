# Set-Index Collapse: why the private L1 reaches 8 of its 128 sets

Stage 4, wcache. Worked entirely on **V8 = `vgg16 layer_08_features_27`**
(KH=3, KW=3, CIN=512, COUT=512) at config **C2** (L1 16 KB / 8-way, L2 512 KB / 16-way,
`cin_block=1`, `cout_block=16`, `weight_bytes=1`).

Companion visual: <https://claude.ai/code/artifact/d2797b1b-ed56-4b48-8934-55db45cc6b71>

---

## 0. The finding in one sentence

L1 and L2 run the **identical** index function, `set = line % num_sets`.
The shared L2 reaches all 2,048 of its sets. A private L1 reaches **8 of 128**.
The index function is not the bug. What the cache can *see* of the address stream is.

Stated at bit level, which is the sharpest form:

> The L1 index takes **5 bits from `cout`** (4 of them frozen for any one core)
> and only **2 bits from `cin`**. The fix gives it **6 bits of `cin`** instead.

Measured headline:

| | value |
|---|---|
| L1 sets reachable by one core | **8 / 128** |
| L1 sets reachable by all 16 cores pooled | 128 / 128 |
| L2 sets reachable by all 16 cores | 2048 / 2048 |
| Usable L1 per core | **1,024 B** of 16,384 B |
| Distinct tags per reachable set | **1,152** against 8 ways |
| Measured `l1_hit_rate` | **0.000** exactly |

---

## 1. Cache geometry

```
line_size_bytes = cin_block * cout_block * weight_bytes = 1 * 16 * 1 = 16 B

L1: 16 KB, 8-way
    num_lines = 16384 / 16 = 1024
    num_sets  = 1024  /  8 =  128

L2: 512 KB, 16-way
    num_lines = 524288 / 16 = 32768
    num_sets  = 32768  / 16 =  2048
```

`num_sets` is a power of two in both, so wcache's `locate()`

```cpp
// src/wcache/native/src/block_pack.cpp:398
return Placement{SetIndex{v % num_sets}, TagId{v / num_sets}};
```

is exactly the classic bit split: `v % num_sets` is the low bits of the line id,
`v / num_sets` is the rest. There is no index hashing.

---

## 2. The address is a plain row-major flatten

The weight tensor is stored `[tap][cin][cout]`, one byte per weight, **cout contiguous**,
where `tap = kh*3 + kw` runs 0..8.

```
byte_address = (tap * 512 + cin) * 512 + cout

total size = 9 * 512 * 512 = 2,359,296 B    ->  22 address bits
```

How the tensor sees those 22 bits:

```
 bit  21    18 17            9 8              0
     +--------+---------------+----------------+
     |  tap   |      cin      |      cout      |
     | 4 bits |    9 bits     |     9 bits     |
     +--------+---------------+----------------+
```

## 3. How the cache cuts the same 22 bits

```
offset bits = log2(16)  = 4
index bits  = log2(128) = 7
tag bits    = 22 - 7 - 4 = 11
```

```
 bit  21              11 10        4 3      0
     +------------------+-----------+--------+
     |       tag        |   index   | offset |
     |     11 bits      |  7 bits   | 4 bits |
     +------------------+-----------+--------+
```

## 4. Overlay the two cuts

This is the whole problem in one picture. The cache boundaries do **not** line up
with the tensor boundaries.

```
 bit  21    18 17            9 8              0
     +--------+---------------+----------------+
     |  tap   |      cin      |      cout      |   <- tensor
     +--------+---------------+----------------+
     |       tag        |   index   | offset   |   <- cache
     +------------------+-----------+----------+
 bit  21              11 10        4 3        0
```

Reading off each field:

| field | width | made of |
|---|---:|---|
| offset | 4 | `cout[3:0]` |
| **index** | **7** | **`cin[1:0] : cout[8:4]`** |
| tag | 11 | `tap[3:0] : cin[8:2]` |

The index draws **5 bits from `cout`** and only **2 bits from `cin`**. Remember that.

---

## 5. One real request, traced end to end

Take `kh=1, kw=2, cin=100, cout=5`, so `tap = 1*3 + 2 = 5`.

```
byte_address = (5 * 512 + 100) * 512 + 5 = 1,361,925
```

In binary, cut by the cache:

```
  01010011001   0000000   0101
  \_________/   \_____/   \__/
     tag=665    index=0   off=5
```

Cross-checks, all confirmed numerically:

| field | bits | value | wcache computes |
|---|---|---:|---|
| tag | `01010011001` | 665 | `line / 128 = 85120 / 128 = 665` |
| index | `0000000` | **0** | `line % 128 = 85120 % 128 = 0` |
| offset | `0101` | 5 | `cout % 16 = 5` |

The tag also reads straight off the overlay:
`tap : cin[8:2] = 5 : 25 = 5*128 + 25 = 665`.

---

## 6. Freeze core 0 and four index bits die

The 16 cores split COUT=512 sixteen ways. **Core 0 owns `cout 0..31` and issues nothing else.**
Verified against the real trace: in any single tile a core touches one `cout_block`,
and over the whole layer core 0 touches blocks {0, 1}, core 1 touches {2, 3}, and so on.

`cout 0..31` in binary is `0 0000 xxxxx`, so `cout[8:5] = 0000` permanently.
Those four bits sit inside the index.

```
index =  cin[1] cin[0] | cout[8] cout[7] cout[6] cout[5] | cout[4]
          vary   vary  |    0       0       0       0    |  vary
         \___________/   \_____________________________/   \____/
            2 live              4 bits FROZEN AT 0          1 live
```

**3 live bits out of 7**, so `2^3 = 8` index values and only those eight:

| cin[1:0] | cout[4] | index binary | index |
|---|---|---|---:|
| 00 | 0 | `0000000` | 0 |
| 00 | 1 | `0000001` | 1 |
| 01 | 0 | `0100000` | 32 |
| 01 | 1 | `0100001` | 33 |
| 10 | 0 | `1000000` | 64 |
| 10 | 1 | `1000001` | 65 |
| 11 | 0 | `1100000` | 96 |
| 11 | 1 | `1100001` | 97 |

Exactly the set list enumerated from the trace: `{0, 1, 32, 33, 64, 65, 96, 97}`.

---

## 7. The 16 cores partition the 128 sets

```
core  0   cout   0.. 31   cout[8:4] = 0,1     index = { 0, 1,32,33,64,65, 96, 97}
core  1   cout  32.. 63   cout[8:4] = 2,3     index = { 2, 3,34,35,66,67, 98, 99}
core  2   cout  64.. 95   cout[8:4] = 4,5     index = { 4, 5,36,37,68,69,100,101}
  ...
core 15   cout 480..511   cout[8:4] = 30,31   index = {30,31,62,63,94,95,126,127}
```

Sixteen **disjoint** groups of eight. Every core has its own private 16 KB array,
and in every one of those arrays 120 sets are physically present and permanently
unreachable.

```
usable per core = 8 sets x 8 ways x 16 B = 1,024 B   out of 16,384 B
```

---

## 8. Count the tags fighting over those eight sets

```
tag = tap[3:0] : cin[8:2]

  tap          9 values     (kh, kw over 3x3)
  cin[8:2]   128 values     (cin 0..511; the low 2 bits were spent on the index)

distinct tags landing in ONE set = 9 * 128 = 1,152
ways available in that set       =               8
```

**1,152 tags competing for 8 ways. 144x oversubscribed.**

Every access evicts a line that will be needed again, and
`8 sets x 1,152 tags = 9,216` accounts for every line the core owns
(`2 cout blocks x 512 cin x 9 taps = 9,216`). That is why the smoke run measured
an L1 hit rate of exactly `0.000` rather than merely a poor one.

---

## 9. Why L2 escapes the same arithmetic

L2 is **shared**, so it sees all 16 cores. Its id stream is dense, and modulo
distributes a dense range perfectly.

```
core 0 alone      8,256 distinct lines spread over ids 0 .. 147,425   <- holes everywhere
all 16 cores    132,096 distinct lines spread over ids 0 .. 147,455   <- dense
```

(Counts are from sample 0, whose coverage of the id space is partial. The
reachability conclusion is identical either way.)

| cache | scope | sets | id stream | sets reached | lines per set |
|---|---|---:|---|---:|---:|
| L1 16 KB 8-way | private, 1 of 16 cores | 128 | stride 32 | **8** | **1,152** |
| L1 16 KB 8-way | hypothetical, pooled | 128 | dense | 128 | 1,152 |
| L2 512 KB 16-way | shared, all 16 cores | 2048 | dense | **2048** | **72** |

The middle row is the control that settles it: the same `% 128` on the same tensor,
fully covered once the cores are pooled. The global radix that separates cores'
blocks is exactly right for L2. For a private L1, 31 of every 32 ids are holes it
will never issue.

---

## 10. The fix, stated as bits

Store each core's 32 channels contiguously, `[core][tap][cin][cout_local]`, where
`cout_local = cout - 32*core` is 5 bits:

```
byte_address = ((core * 9 + tap) * 512 + cin) * 32 + cout_local
```

New overlay:

```
 bit  17    14 13            5 4            0
     +--------+---------------+--------------+
     |  tap   |      cin      |  cout_local  |   <- tensor
     +--------+---------------+--------------+
     |     tag      |   index    |   offset  |   <- cache
     +--------------+------------+-----------+
 bit  17          11 10         4 3         0
```

| field | before | after |
|---|---|---|
| offset | `cout[3:0]` | `cout_local[3:0]` |
| **index** | `cin[1:0] : cout[8:4]` | **`cin[5:0] : cout_local[4]`** |
| tag | `tap[3:0] : cin[8:2]` | `tap[3:0] : cin[8:6]` |

All seven index bits now vary, six of them from `cin`. Core 0 reaches all 128 sets.

Same request through the new layout:

```
addr = ((0*9 + 5) * 512 + 100) * 32 + 5 = 85,125
  offset =  5
  index  = 72      (was 0)
  tag    = 41      (was 665)
```

New pressure per set:

```
tags per set = tap (9) x cin[8:6] (8) = 72   vs 8 ways

before:  1,152 tags / 8 ways  = 144x oversubscribed
after:      72 tags / 8 ways  =   9x oversubscribed
```

A clean **16x** reduction, which is precisely the sixteen cores' worth of index bits
that were being wasted.

### Two ways to implement it, and they are not equivalent

**(a) Fix the index.** L1 computes a core-local id while L2 keeps the global one.
The mapper must emit two ids per request and the L1 must know its `base`.
Tags stay safe because L1s are private, so two cores holding local id 5 never meet.

**(b) Fix the layout.** Write the weight tensor so each core's slice is contiguous,
`line = slice * 9216 + local`. This stays a global bijection, stays dense, and plain
`line % num_sets` then works unchanged at **both** levels, with no new hardware and no
change to `locate()`. The weights are written offline, so the layout is ours to choose.

**(b) is preferred.** It is already the open plan in
`project_2026-07-28-set-index-and-cin-cout-layout-plan.md`; this measurement is the
evidence that plan was waiting for.

### R9 needs care

R9 has COUT=128, so `blocks_per_core = 128 / (16 * 16) = 0.5`. Two cores share a
`cout_block` and there is no private slice to give them. The slice granularity becomes
the block:

```
local radix = max(1, blocks_per_core) = 1
line = block_slice * 2304 + (kh*3 + kw) * 256 + cin      dense 0..2303 per slice
```

That still reaches all 128 sets. The two cores sharing it each keep their own copy in
their own L1, exactly as they do today. This is the same core-pair false sharing that
produces R9's measured L2 hit rate near 0.5.

---

## 11. What the fix does not solve

```
V8 core 0:  9,216 lines over the layer,  1,226 lines in a median tile,  1,875 worst
16 KB L1 :  1,024 lines
```

The fix converts a total-conflict regime into a capacity regime. The hit rate should
leave `0.000`, but a 1,226-line tile working set still does not fit in 1,024 lines.
The residual 9x oversubscription is genuine capacity pressure and no indexing scheme
removes it.

| layer | tile working set (p50) | fits in 1,024 lines |
|---|---:|---|
| V8 | 1,226 | no |
| V9 | 2,362 | no |
| R9 | **737** | **yes** |
| R16 | 1,842 | no |

**Prediction for config C3 (fully associative L1): a large gain on R9 and a much
smaller one on the other three.** If C3 lifts V9 substantially, the reuse is more
local than this working-set count implies and the model above is wrong somewhere.

---

## 12. Every layer, same mechanism

```
reachable_sets  = (num_sets / gcd(COUT/cout_block, num_sets)) * blocks_per_core
blocks_per_core = max(1, COUT / (16 * cout_block))
```

| layer | COUT | stride | blocks/core | sets @ 128 (C2) | sets @ 240 (C1) | tile working set |
|---|---:|---:|---:|---:|---:|---:|
| V8 `vgg16 features_27` | 512 | 32 | 2 | **8** | 30 | 1,226 |
| V9 `vgg16` | 512 | 32 | 2 | **8** | 30 | 2,362 |
| R9 `resnet19 layer2_0_conv2` | 128 | 8 | 0.5 | **16** | 30 | 737 |
| R16 `resnet19` | 256 | 16 | 1 | **8** | 15 | 1,842 |

The 240-set column is the 30,720 B arch-derived L1 (C1). It does better only because
**240 is not a power of two**, so `gcd(32, 240) = 16` instead of 32. That is a 3.75x
recovery bought purely by an awkward set count, which is index hashing applied by
accident.

Config C4 is the counterintuitive one: `cin_block 4` gives a 64 B line, which cuts
`num_sets` to 32 while leaving the stride at 32, dropping a core to **2 reachable sets**.
A larger line makes this worse, not better.

---

## 13. Sources and reproduction

| what | where |
|---|---|
| weight traces | `profiling/0823_stagewise_verify/stage2_weight_trace/outputs/weight_traces/loas/noc2MiB_node32kb/` |
| index function | `src/wcache/native/src/block_pack.cpp:398` (`locate()`) |
| config defaults | `src/wcache/native/include/wcache/config.h` |
| geometry validation | `src/wcache/native/src/config.cpp` (`check_level_geometry()`) |
| arch (C1's 30,720 B L1) | `profiling/0823_stagewise_verify/stage3_nocsim/inputs/arch/loas_inst16_node32kb_noc2MiB_pe16.yaml` |

Reachable sets, straight from the trace:

```python
import gzip, json
f = '.../vgg16_T4_n5/layer_08_features_27/sample_00000.json.gz'
d = json.load(gzip.open(f))
KW, CIN, NCB, NSETS = 3, 512, 32, 128
s0, sall = set(), set()
for t in d['tiles']:
    for tick in t['ticks']:
        for c in tick['cores']:
            for kh, kw, cin, r0, r1 in c['weight_addresses']:   # entries are LISTS
                for cb in range(r0 // 16, (r1 - 1) // 16 + 1):
                    ln = ((kh * KW + kw) * CIN + cin) * NCB + cb
                    sall.add(ln % NSETS)
                    if c['core_id'] == 0:
                        s0.add(ln % NSETS)
print(len(s0), sorted(s0))   # 8  [0, 1, 32, 33, 64, 65, 96, 97]
print(len(sall))             # 128
```

Bit-field cross-check:

```python
cur = lambda tap, cin, cout: (tap * 512 + cin) * 512 + cout
a = cur(5, 100, 5)                      # 1,361,925
a & 15, (a >> 4) & 127, a >> 11         # (5, 0, 665)

fix = lambda core, tap, cin, cl: ((core * 9 + tap) * 512 + cin) * 32 + cl
b = fix(0, 5, 100, 5)                   # 85,125
b & 15, (b >> 4) & 127, b >> 11         # (5, 72, 41)
```
