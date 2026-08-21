"""Task 8: --stream's stream/dump contract, driven from a checked-in fixture.

tests/test_stream_flag.sh pins the same contract end to end through the CLI,
which needs a solved schedule and the input corpus. This one needs neither, so
it can run anywhere: it calls the same emit_stream the --stream branch calls.

Run: PYTHONPATH=src python tests/test_stream_dump.py
"""
import io
import pathlib
import struct
import sys
import tempfile

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "tests"))

from generate_weight_traces import emit_stream  # noqa: E402
from test_stream_writer import load_fixture  # noqa: E402

FIXTURE = "loas_vgg16_layer01_v2.json"
N_CORES = 8
SPATIAL = {3: 8}


def test_dump_is_byte_identical_to_the_stream():
    trace = load_fixture(FIXTURE)
    sink = io.BytesIO()
    with tempfile.TemporaryDirectory() as tmp:
        dump_path = pathlib.Path(tmp) / "dump.bin"
        emit_stream(trace, sink, n_cores=N_CORES, spatial_factors=SPATIAL,
                    dump_path=dump_path)
        assert dump_path.read_bytes() == sink.getvalue(), "full dump must match the stream"


def test_dump_trace_tiles_yields_a_valid_short_stream():
    trace = load_fixture(FIXTURE)
    sink = io.BytesIO()
    with tempfile.TemporaryDirectory() as tmp:
        dump_path = pathlib.Path(tmp) / "dump.bin"
        emit_stream(trace, sink, n_cores=N_CORES, spatial_factors=SPATIAL,
                    dump_path=dump_path, dump_tiles=1)
        dump = dump_path.read_bytes()
    full = sink.getvalue()
    assert struct.unpack_from("<i", dump, 16)[0] == 1, "dump must declare the truncated tile count"
    assert struct.unpack_from("<i", dump, len(dump) - 12)[0] == -1, "dump needs a trailer"
    hb = struct.unpack_from("<I", full, 12)[0]
    assert hb == struct.unpack_from("<I", dump, 12)[0]
    body = dump[hb:len(dump) - 12]
    assert full[hb:hb + len(body)] == body, "dump is not byte-identical to what the consumer saw"


if __name__ == "__main__":
    test_dump_is_byte_identical_to_the_stream()
    test_dump_trace_tiles_yields_a_valid_short_stream()
    print("test_stream_dump: OK")
