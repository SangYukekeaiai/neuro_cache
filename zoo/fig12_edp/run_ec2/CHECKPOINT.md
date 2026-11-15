# T71 checkpoint

Implemented only under `run_ec2/`: portable sample-first queue, explicit JSON
machine/science configuration, bounded memory reservations, finite OOM tiers,
owned-session cancellation, NVMe/TMPDIR pipeline, fsynced durable per-sample
results, strict content fingerprints, sample-0 CSV/figure barrier, and staging
documentation. No shared source/native change, real rented launch, or cloud
change was made. The active T84 wave remains parent-owned and untouched.

Native mini: SpinalFlow B09 VGG16 classifier, actual samples 0 and 1, one
3 GiB worker within a separate <=4 GiB scope. See `mini_validation.json`,
`mini.log`, `resume.log`, and `mini_output/`. The subset is explicitly 1/749.
Known Prosperity zero-MAC failures remain a parent/shared-source issue; this
runner records them explicitly and makes no semantic workaround.

Next: parent review, then rented-host staging and measurement using STAGING.md.
Do not launch `rented.example.json` on Delta. It is a 240 GiB resource example.
