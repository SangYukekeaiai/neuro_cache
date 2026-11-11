# S2 release: campaign schedules

`s2_schedules.tar.gz` is the complete S2 close-out, packed for delivery to
the generation cluster through git. Contents, relative to
`zoo/wt500_fig3cfg/outputs/` on the producing host (DeltaAI, repo commit
b1dc999, packed 2026-11-11):

- `manifest.json` - the unified campaign manifest: 755 rows (151 per arch),
  749 winners + 6 prosperity infeasibles, every row carrying `mode`,
  13-entry `mode_statuses` and `schedule_sha256`; `mode_digest` key holds
  the per-mode OPT/INF table (3,036 / 6,779, no TIME_LIMIT).
- `schedules/` - the 749 schedule artifact JSONs.
- `workloads/` - the per-layer workload YAMLs the sweep solved.

Unpack on the consuming host into `zoo/wt500_fig3cfg/outputs/`:

    mkdir -p zoo/wt500_fig3cfg/outputs
    tar -xzf zoo/wt500_fig3cfg/release/s2_schedules.tar.gz -C zoo/wt500_fig3cfg/outputs

Then verify integrity from the manifest itself (it carries a sha256 per
schedule row), not from trust in the transport:

    python - <<'EOF'
    import json, hashlib, sys
    m = json.load(open('zoo/wt500_fig3cfg/outputs/manifest.json'))
    bad = 0
    for r in m['schedules']:
        if r['status'] == 'INFEASIBLE':
            continue
        h = hashlib.sha256(open('zoo/wt500_fig3cfg/outputs/' + r['schedule_path'], 'rb').read()).hexdigest()
        if h != r['schedule_sha256']:
            print('MISMATCH', r['schedule_path']); bad += 1
    print('verified', len(m['schedules']), 'rows,', bad, 'mismatches')
    sys.exit(1 if bad else 0)
    EOF

The tarball's own checksum is in `s2_schedules.tar.gz.sha256`.
