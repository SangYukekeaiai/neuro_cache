# DeltaAI descending campaign

The manager assigns340–429 plus440–449,460–469 and480–489. The original
ten-task array and110-task extension run independently at one task each;
`remaining_samples.txt` supplies the extension mapping. A third node slot
belongs to the interactive stream. Each normal task
requests one ghx4 node,288 cores, four GH200 GPUs,440GiB and six hours. Case
reservations are bounded to420GiB; memory limits concurrent cases. The initial
wave is bounded by a shared240 GH200-hour admission budget. `budget.py`
reserves a job's maximum duration before scientific work, charging4 GH200/hour
for four GPUs normally,8 GH200/hour for the four-GPU interactive job, and
2 GH200/hour for a one-GPU interactive job. Terminal Slurm accounting releases
unused reservations. Insufficient budget refuses new execution; measured burn
requires manager review before raising the cap or concurrency. Core-count
projections do not account for memory-limited packing.

`stream.py` runs detached on the login host. It holds one pending normal-array
task before submitting a two-hour interactive count-only chunk. The quarter-share
shape requests one GH200,72 cores and110GiB, with100GiB reserved for cases.
Cases requiring120GiB are listed in `deferred_to_batch` with their exact index,
identity and retry tier; their attempts are not launched or consumed.
Chunk interruption
retains committed stages and archives attempt evidence; the next chunk resumes
the same sample and tier. Once all fitting cases finish, the held task is released
to complete deferred cases, apply NG45 pricing and retire durable products.
The partition QoS permits one submitted and one running interactive job per user,
so this stream submits sequential chunks. A shared lane lock also prevents
overlapping contenders from computing concurrently; a losing contender exits
naturally. Handoff to
the batch task uses that same lock and is recorded before release. No contender
or array task is cancelled. Unknown failures stop the stream for
diagnosis. `interactive_status.json` records jobs, starts and handbacks; the
controller uses no Delta tunnel after launch.

`setup_env.sh` creates an aarch64 Python/Rust environment. `job.sh` builds the
vendored archx extension on ARM and checks its ELF architecture and digest.
The shared [Delta runner](../delta/README.md) builds native generators,
cachesim and NoC simulation on ARM, then executes the15-row/386-term fixture
gate inside every task. A mismatch aborts before campaign work. Passing tasks
proceed directly; there is no operator checkpoint. Thread caps and
`ARCHX_DISABLE_PERFORMANCE_CACHE=1` apply throughout.

The source transfer excludes compiled binaries, build products and campaign
outputs. DeltaAI's `/u/yyu9` is separate from Delta's home; the ARM checkout and
extension cannot overwrite the x86 copy. `/work` is shared. Captures are read
directly from `/work/nvme/bebv/yyu9/input_trace_delta/` and never modified.

Workspace: `/work/hdd/bebv/yyu9/fig12_full500_deltaai/`. Its `rows` symlink
resolves on DeltaAI to this repository's `deltaai/full500/rows/`. Read those
durable rows through DeltaAI, since the home target is host-specific. Successful
samples undergo NG45 pricing, verification, durable commit and transient-tree
retirement. Exact authorized heavy failures are quarantined; other failures
stop for diagnosis. The shared runner retains failed evidence.

Use only the authenticated `cm-deltaai.sock` ControlMaster for transfers and
operations. A dead socket requires renewed authentication by the owner; do not
retry password logins. The manager owns the cross-site ledger and lowers the
Stokes ownership boundary before assigning another descending block.
