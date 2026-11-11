#!/bin/bash
# WT500 campaign status snapshot on Stokes. One shot:
#   bash zoo/wt500_fig3cfg/stokes/monitor.sh
# Every 15 minutes (run inside tmux):
#   while :; do bash zoo/wt500_fig3cfg/stokes/monitor.sh; sleep 900; done
set -u
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1
REPO="$HOME/neuro_cache_wcache"
RUN_ROOT="$REPO/zoo/wt500_fig3cfg/outputs/slurm/runs_full"
CASE_DIR="$REPO/zoo/wt500_fig3cfg/outputs/slurm/cases_weighted"
PYTHON="$REPO/.venv311/bin/python"

echo "===== $(date '+%F %T') ====="

echo "-- queue (wt500-traces) --"
squeue -u "$USER" --name=wt500-traces -o "%A %t %M %C %R" -h | awk '
  {states[$2]++}
  END {for (s in states) printf "  %s: %d  ", s, states[s]; print ""}'
squeue -u "$USER" --name=wt500-traces -o "  %i %t %M %R" -h | head -8

echo "-- finished array tasks (sacct) --"
sacct -n -X --name=wt500-traces --format=State -P 2>/dev/null | sort | uniq -c

echo "-- cases completed --"
total=$("$PYTHON" -c "import json,sys;print(json.load(open(sys.argv[1]))['total_cases'])" \
        "$CASE_DIR/manifest.json" 2>/dev/null || echo "?")
done_rows=$(tail -qn +2 "$RUN_ROOT"/shard_*/results_*.csv 2>/dev/null | wc -l)
echo "  $done_rows / $total"

echo "-- recent errors --"
grep -l . "$RUN_ROOT"/slurm-*.err 2>/dev/null | tail -3 | while read -r f; do
  echo "  $f:"; tail -2 "$f" | sed 's/^/    /'
done
[ -z "$(ls "$RUN_ROOT"/slurm-*.err 2>/dev/null)" ] && echo "  (none yet)"

echo "-- lustre quota --"
lfs quota -h -u "$USER" /lustre/fs1 2>/dev/null | sed -n '2,3p'
