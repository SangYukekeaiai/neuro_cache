#!/bin/sh
# Task 5: the arch binary must write the SAME bytes to stdout as to a file.
# Usage: stdout_roundtrip.sh <binary> <trace.bin> <task.bin>
set -e
bin=$1; trace=$2; task=$3
tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT
"$bin" "$trace" "$task" "$tmp/via_file.bin"
"$bin" "$trace" "$task" - > "$tmp/via_stdout.bin"
cmp "$tmp/via_file.bin" "$tmp/via_stdout.bin"
echo "stdout_roundtrip: identical"
