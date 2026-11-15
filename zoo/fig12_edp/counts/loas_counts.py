"""LoAS shares PTB's fetch/accumulate counts and emits T-bit output words."""
import ptb_counts

FIELDS = (*ptb_counts.FIELDS, "W_o")


def count_sample(trace, sample, **kwargs):
    counts = ptb_counts.count_sample(trace, sample, **kwargs)
    return {**counts, "W_o": counts["O"] / counts["T"]}


if __name__ == "__main__":
    from capture_counts import main
    raise SystemExit(main("loas", count_sample, FIELDS))
