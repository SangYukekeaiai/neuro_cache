# Weight-access locality via input spiking structure

> Created: 2026-07-23. Plan for the access-pattern stage of the
> replacement-policy work: testing whether each of the input's four
> dimensions carries a hot zone, and routing each dimension to the
> analysis method that matches its relationship to a weight address.

## Overview

**What:** test each of the four input dimensions, `cin`, `hin`, `win`,
`t`, for a hot zone: some values firing far more often than others.

**Why:** weight access is driven by the input's own spiking pattern, so
any locality in weight access ultimately comes from locality in the
input along one or more of its four dimensions.

**How:** route each dimension to the method that matches its
relationship to a weight address. `cin` is native to the weight address
and is tested via a cache simulator. `hin`, `win`, and `t` are tested
directly on the raw input spike trace.

## 1. `cin`

**What:** build a cache-simulation pipeline over the weight-access trace
and test whether `cin`'s own values cluster the access pattern the way a
hot zone would.

**Why specially:** `cin` appears directly inside every weight address
`(kh, kw, cin, cout)`. Testing it needs no reconstruction from schedule
or tile metadata, so it can be tested straight off the weight trace
already on disk.

**How:**

### 1.1 Expand the address stream

- **What:** turn each trace event `(kh, kw, cin, cout_start, cout_end)`
  into its individual `(kh, kw, cin, cout)` elements.
- **Why specially:** an event's `cout` range represents several
  distinct, simultaneously touched weight elements, not one address, so
  each one needs its own entry before any tagging happens.
- **How:** for each event, iterate `cout` from `cout_start` to
  `cout_end` and emit one `(kh, kw, cin, cout)` tuple per value.

### 1.2 Line-tag mapping and the locality diagnostic

- **What:** define a cache-line tag by absorbing one dimension at a
  time, `cout`, `cin`, `kh`, or `kw`, into the line's offset, and measure
  how concentrated the resulting tag histogram is, for each of the four
  choices.
- **Why specially:** a tag hides whichever dimension is chosen as
  innermost (multiple values of it share one tag) and exposes the other
  three (each distinct value gets its own tag). Testing all four choices
  on the same underlying accesses turns "which dimension is hot" into a
  differential comparison: the hot dimension's own clustering appears in
  the three layouts that expose it, and flattens out in the one layout
  that absorbs it.
- **How:**
  - Tag formation: for a chosen `inner_dim`, tag = the other three
    dimensions unchanged, plus `inner_dim // line_size`.
  - Concentration formula: build `tag -> access count` per sample per
    layer, then score it with normalized entropy: `p_i =
    count(tag_i)/total`, `H = -sum(p_i * log(p_i))`, `concentration = 1
    - H/log(n)` (`n` = number of distinct tags seen). 0 means uniform,
    near 1 means concentrated. Computed per sample, then summarized
    across samples, not pooled, so a real per-sample hot zone stays
    visible.
  - Output format: a rank-frequency plot (tags sorted by count, log-log
    scale) per layout, showing the shape directly, plus a bar or box
    plot of the concentration score across samples, one bar per
    `inner_dim` choice, for the actual differential read.

### 1.3 The cache's tag: formation, size, and rationale

- **What:** define the tag and line width the actual cache simulator
  will use, reusing 1.2's tag definition.
- **Why specially:** using the same tag for the cache as for the
  diagnostic means the cache's hit and miss behavior is governed by
  exactly the locality property already measured, so the diagnostic's
  read carries directly over to a prediction about hit rate.
- **How:** tag = `(kh, kw, cout_chunk, cin // line_size)` (or the
  equivalent when a different dimension is innermost). One line's width
  in bytes = `line_size` times the weight's byte width; `line_size` is
  chosen to land on a realistic line width, for example 16 or 32
  elements at 8-bit weights, rather than the full range of that
  dimension.

### 1.4 Build and run the fully-associative LRU cache

- **What:** simulate the cache using the tag from 1.3.
- **Why specially:** a fully-associative cache with LRU is the simplest
  correct baseline, keeping any set or associativity design deferred.
- **How:** single global capacity, `OrderedDict`-based recency, replay
  the expanded and tagged stream from 1.1 through it.

## 2. `hin`, `win`, `t`

**What:** test these three dimensions directly on the raw `(t, cin,
hin, win)` input spike trace.

**Why specially:** none of these three appear as native weight-address
coordinates. `hin`/`win` exist only as a combination of a weight event's
`kh`/`kw` and its originating tile's `ho`/`wo`, requiring a schedule
rejoin and a fold across time. Going to the raw spike trace measures the
same input-side question directly.

**How:** for each of `hin`, `win`, and `t`, build a per-sample histogram
of firing counts over the raw spike trace (marginalizing the other
axes), then score its concentration with the same normalized-entropy
formula as 1.2: `p_i = count(value_i)/total`, `H = -sum(p_i *
log(p_i))`, `concentration = 1 - H/log(n)`. Compute this per sample
rather than pooling across samples, since the hot zone's specific
location can shift from sample to sample; a pooled histogram would
flatten out a real per-sample concentration even where one exists.
Summarize the resulting concentration scores' distribution
(median/spread) across samples, the same per-sample-then-summarize
approach used for `cin`.
