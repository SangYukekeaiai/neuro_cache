# Replacement policy: spike-locality hypothesis and first cache-sim step

> Created: 2026-07-22. Rephrased status update and near-term plan for
> shifting focus from weight-trace generation to designing a cache
> replacement policy informed by spike-input locality.

## Context

Current focus has moved to the cache **replacement policy** question:
given the reconstructed weight-address traces, can eviction decisions be
made smarter than recency/frequency alone by exploiting structure in the
spike input itself?

## Core hypothesis

Input spikes are not uniformly distributed. They are assumed to carry
their own pattern, i.e. structured locality along one or more dimensions:

- input channel (`cin`)
- spatial position (`hin`, `win`)
- time (`T`)
- or some combination of the above

**Design implication:** if this locality exists, the replacement policy
should prioritize retaining weights associated with the "hot zone" of the
input spikes, rather than treating all cached weights as equally
priority-worthy. Eviction priority should be driven by observed
input-feature activity.

## Overall methodology (top-down)

1. Profile real traffic to discover the common pattern in spike inputs.
2. Design a policy that exploits that pattern.
3. Evaluate the resulting cache performance against baseline policies.

## Where things are now: Step 1, pattern discovery

To discover the pattern, a minimal cache simulator needs to be built on
top of the already-generated weight traces (`src/tracegen.py` output),
consisting of:

1. A baseline **LRU** replacement policy (control/reference point).
2. An **address mapping** from logical weight coordinates
   `[kh, kw, cin, cout_range]` to a cache line address.
3. A defined **cache line format**.
4. A **sweep harness** over cache size and set-associativity.

The real cache-line-level trace this produces is meant to let us observe
the locality feature we're looking for.

## Open question (unresolved)

Once the simulator produces real hit/miss/eviction traces, what
statistics or signals should be tracked to reliably surface *which*
dimension(s), channel, spatial, temporal, or joint, the input locality
actually lives in? No concrete answer yet for which metrics would give a
strong enough signal to confirm the pattern.

## Next steps

- Implement the 4-part minimal cache simulator listed above.
- Run it against existing weight traces across a sweep of cache
  size/associativity.
- Identify candidate profiling metrics for the open question above before
  or alongside implementation.
