# Accepted T71 experiment plan

The current dispatch explicitly approves implementation and bounded validation.
Build a portable local queue for 749 feasible pairs, three energy arms and
samples 0 through 499. Complete attempts for every sample-0 pair and emit a
clearly labelled CSV/figure checkpoint before starting any sample-1 work;
subsequent samples also use barriers. Missing/OOM/budget cases remain explicit,
never complete totals. A mini case limit is always labelled a subset.

Use existing native generation, architecture counts, NoC and energy join code.
Every sample index must reach generation, counts, density, record CSV, NoC,
rows and fingerprints. Stage transient WCTS/native files on local NVMe and
commit fsynced durable results before deleting the stream. Resume verifies
scientific inputs and artifact digests and fails closed on changes.

Expose all machine paths and resource settings in JSON. Reserve memory before
launching bounded workers; giant work runs serially, and OOM retries move up
finite tiers. Cancel only owned worker sessions. Pin both production configs
to the VGG16 snapshots, with A L1 d4/L2 d1/min_touches9.

Acceptance: native tiny sample 0 and sample 1 at one worker, <=4 GiB total;
compare sample 0 with an existing matching demo; prove distinct sample use;
resume without regeneration; reject changed config; test barriers, memory
reservations, finite escalation and partial coverage. No rented-machine launch,
cloud change, shared native rebuild, input write, or T84 change is authorized.
