"""Physical movement counts from annotated lays.nocsim transaction CSVs."""

import csv
from pathlib import Path

from lays.nocsim.core.noc import NoC
from lays.nocsim.core.transaction import COUNT, MULTICAST, PACKET_SIZE, UNICAST

GB_WORD_BYTES = 32
DRAM_BURST_BYTES = 64


def parse_tc_csv(path, *, X, Y, gb_port=None, dram_port=None):
    """Return counts, with GB accesses in 32B words and DRAM in 64B bursts.

    Multicast charges the union of directed XY tree edges, and one GB read
    per packet. Every destination receives the packet's padded payload.
    DRAM rounds up independently per transaction; its bus is not a mesh hop.
    Non-weight boundary traffic is rejected; k/t chains remain separate.
    """
    if PACKET_SIZE != GB_WORD_BYTES * 8:
        raise ValueError("Fig12 requires 32B NoC packets/GB words")
    noc = NoC(X, Y, gb_port=gb_port, dram_port=dram_port)
    counts = dict.fromkeys((
        "weight_packet_hops", "chain_packet_hops", "k_chain_packet_hops",
        "t_chain_packet_hops", "weight_unicast_packet_hops",
        "weight_multicast_packet_hops", "gb_reads", "gb_writes",
        "l1_delivery_bytes", "dram_accesses", "dram_bytes",
        "dram_payload_bytes", "dram_transactions", "transaction_count",
        "psum_boundary_bytes", "vmem_boundary_bytes",
    ), 0)
    annotation = None
    with Path(path).open() as stream:
        for line in stream:
            if not line.strip():
                continue
            if line.startswith("#"):
                annotation = line[1:].strip().split(":", 1)[0]
                continue
            row = next(csv.reader([line]))
            if len(row) != 7 or not annotation:
                raise ValueError("expected an annotated seven-column tc.csv row")
            tc_id, actor, op, size = map(int, row[:4])
            srcs, dests, deps = ([int(v) for v in field.split()] for field in row[4:])
            if (tc_id != counts["transaction_count"] or size < 0
                    or len(srcs) != 1 or actor != srcs[0]
                    or any(d < 0 or d >= tc_id for d in deps)
                    or any(p < 0 or p >= noc.num_ports for p in srcs + dests)
                    or len(set(dests)) != len(dests)):
                raise ValueError(f"invalid transaction {tc_id}")
            counts["transaction_count"] += 1
            label, annotation = annotation, None
            if op == COUNT:
                if dests or not label.startswith(("mac_", "lif_")):
                    raise ValueError(f"invalid COUNT transaction {tc_id}")
                continue
            if op not in (UNICAST, MULTICAST) or not dests or (op == UNICAST and len(dests) != 1):
                raise ValueError(f"invalid transfer {tc_id}")
            src = srcs[0]
            chain = "k" if "__kchain_" in label else "t" if "__tchain_" in label else None
            if chain:
                if (op != UNICAST or src >= noc.num_pes or dests[0] >= noc.num_pes
                        or noc.manhattan(src, dests[0]) != 1
                        or not label.startswith("psum_" if chain == "k" else "vmem_")):
                    raise ValueError(f"chain must be a neighbor link: {label}")
                counts[f"{chain}_chain_packet_hops"] += size
                counts["chain_packet_hops"] += size
                continue
            weight = label.startswith("weight_") or (
                label.startswith("dram_") and label.endswith(("__load_weight", "__store_weight")))
            if not weight:
                raise ValueError(f"unexpected psum/vmem boundary or unknown traffic: {label}")
            payload = size * GB_WORD_BYTES
            if src == noc.dram_port or noc.dram_port in dests:
                if op != UNICAST:
                    raise ValueError("DRAM traffic must be unicast")
                bursts = (payload + DRAM_BURST_BYTES - 1) // DRAM_BURST_BYTES
                counts["dram_transactions"] += 1
                counts["dram_payload_bytes"] += payload
                counts["dram_accesses"] += bursts
                counts["dram_bytes"] += bursts * DRAM_BURST_BYTES
            else:
                if src != noc.gb_port or any(d >= noc.num_pes for d in dests):
                    raise ValueError(f"unexpected weight endpoints: {label}")
                hops = size * noc.count_hops(src, dests)
                counts["weight_packet_hops"] += hops
                kind = "unicast" if op == UNICAST else "multicast"
                counts[f"weight_{kind}_packet_hops"] += hops
            if src == noc.gb_port:
                counts["gb_reads"] += size
            if noc.gb_port in dests:
                counts["gb_writes"] += size
            counts["l1_delivery_bytes"] += payload * sum(d < noc.num_pes for d in dests)
    if not counts["transaction_count"]:
        raise ValueError("empty transaction CSV")
    return counts
