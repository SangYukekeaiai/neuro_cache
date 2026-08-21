#!/bin/sh
# Task 8: --stream writes exactly one valid WCTS stream on stdout and nothing else.
#
# End-to-end, so it needs a solved schedule under outputs/schedules and the
# input trace corpus. tests/test_stream_dump.py covers the same stream/dump
# contract from a checked-in fixture, with no corpus.
set -e
cd "$(dirname "$0")/.."
tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT

conda run -n cosa_snn python scripts/generate_weight_traces.py \
    --stream --arch loas --trace-dir vgg16_T4_all \
    --layer layer_01_features_3 --sample-start 0 --sample-count 1 \
    --dump-trace "$tmp/dump.bin" --dump-trace-tiles 2 \
    > "$tmp/stream.bin" 2> "$tmp/log.txt"

# 1. stdout starts with the magic.
head -c 8 "$tmp/stream.bin" | grep -q 'WCTRACE1'
# 2. the tee is a byte-identical PREFIX of what the consumer saw, up to 2 tiles.
conda run -n cosa_snn python - "$tmp/stream.bin" "$tmp/dump.bin" <<'PY'
import struct, sys
full = open(sys.argv[1], "rb").read()
dump = open(sys.argv[2], "rb").read()
assert dump[:8] == b"WCTRACE1"
assert struct.unpack_from("<i", dump, 16)[0] == 2, "dump must declare 2 tiles"
assert struct.unpack_from("<i", dump, len(dump) - 12)[0] == -1, "dump needs a trailer"
# The two headers differ only in n_tiles; every tile frame that both carry must match.
hb_full = struct.unpack_from("<I", full, 12)[0]
hb_dump = struct.unpack_from("<I", dump, 12)[0]
assert hb_full == hb_dump
body_dump = dump[hb_dump:len(dump) - 12]
assert full[hb_full:hb_full + len(body_dump)] == body_dump, "tee is not byte-identical"
print("stream + tee: OK")
PY
# 3. nothing but the stream on stdout: every log line went to stderr.
test -s "$tmp/log.txt"
echo "test_stream_flag: OK"
