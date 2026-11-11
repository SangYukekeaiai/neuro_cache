#!/usr/bin/env bash
# First-login recon on Stokes. Read-only; prints everything the
# deployment plan needs to go/no-go. Run on the login node.
set -u

echo "== partitions, wall limits, node shapes =="
sinfo -o "%P %l %D %c %m %a" 2>/dev/null || echo "sinfo failed"

echo; echo "== allocation balance =="
myusage 2>/dev/null || echo "myusage not found; ask ARCC for the balance command"

echo; echo "== storage quota and free space =="
for fs in /lustre/fs0 /lustre/fs1; do
  [ -d "$fs" ] && { echo "-- $fs"; lfs quota -h -u "$USER" "$fs" 2>/dev/null; df -h "$fs" 2>/dev/null | tail -1; }
done
echo "-- home"; du -sh "$HOME" 2>/dev/null

echo; echo "== node helper =="
which ncode cnode 2>/dev/null; ls "$HOME/local/bin" 2>/dev/null

echo; echo "== outbound reachability =="
timeout 8 bash -c 'echo > /dev/tcp/dt-login02.delta.ncsa.illinois.edu/22' 2>/dev/null \
  && echo "Delta ssh: REACHABLE" || echo "Delta ssh: NOT reachable"
timeout 8 bash -c 'echo > /dev/tcp/github.com/443' 2>/dev/null \
  && echo "GitHub https: REACHABLE" || echo "GitHub https: NOT reachable"

echo; echo "== globus =="
which globus globus-url-copy 2>/dev/null || echo "no globus CLI on PATH (an endpoint may still exist; ask ARCC)"

echo; echo "== prior campaign root =="
ls -d /lustre/fs*/home/"$USER" 2>/dev/null
ls /lustre/fs1/home/"$USER"/data/input_trace_delta 2>/dev/null | head -5
