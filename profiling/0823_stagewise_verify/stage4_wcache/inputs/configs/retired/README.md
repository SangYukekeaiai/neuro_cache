# C1, retired from the Stage 4 grid

C1 was the arch's own L1: 30,720 bytes, the `NodeLevel.local_buffer.entries.weight`
partition of `loas_inst16_node32kb_noc2MiB_pe16.yaml`.

It is not run here. **Stage 3's result stands in for C1**, since nocsim already
models the 30,720 B node weight buffer over the same schedules and the same
spike traces, and re-deriving it through the cache model would be a second
number for one quantity.

Stage 4 therefore measures C2, C3 and C4, whose job is to isolate the INDEXING
question. The file is kept because C1's geometry is the reason 240 sets keeps
appearing in the analysis: 240 is not a power of two, so `gcd(32, 240) = 16`
rather than 32, and the arch accidentally gets 3.75x the reachable sets that a
16 KB L1 does. That is worth remembering when Stage 3 and Stage 4 numbers are
put side by side.
