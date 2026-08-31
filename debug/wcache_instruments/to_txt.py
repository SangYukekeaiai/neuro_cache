#!/usr/bin/env python3
"""Render either instrument's CSV as aligned columns, for reading by eye.

One converter for both files rather than a text mode in each emitter: the C++
side stays CSV, which is the right shape for analysis, and the alignment is a
presentation choice that belongs where the reading happens. It works on any CSV
with `#` comment lines above a header, so a third instrument would need no
change here.

    python3 to_txt.py in.csv out.txt [--rows N] [--sort COL[,COL...]]

`--rows N` keeps the first N data rows and says so in the footer, because a file
that was cut and does not say so reads as a run that stopped early.

`--sort COL` reorders by one or more columns before cutting, numerically where
every value in the column is an integer and lexically otherwise. It exists for
the line trace, whose natural order is `ended_at` and cannot be anything else:
a row is written when its episode closes, since residency and hits are unknown
until then. `--sort first_request` reads the same file in request order.

Sorting BEFORE cutting is the decision that makes `--rows` mean what a reader
expects: `--sort first_request --rows 2000` is the 2000 earliest requests, not
an arbitrary 2000 rows put in order afterwards.
"""
import csv, sys

def main(argv):
    rows, sort_cols = None, []
    if "--rows" in argv:
        i = argv.index("--rows")
        rows = int(argv[i + 1])
        argv = argv[:i] + argv[i + 2:]
    if "--sort" in argv:
        i = argv.index("--sort")
        sort_cols = argv[i + 1].split(",")
        argv = argv[:i] + argv[i + 2:]
    src, dst = argv[1], argv[2]

    comments, data = [], []
    with open(src) as f:
        for line in f:
            if line.startswith("#"):
                comments.append(line.rstrip("\n"))
            else:
                data.append(line)
    r = list(csv.reader(data))
    header, body = r[0], r[1:]
    total = len(body)

    for col in reversed(sort_cols):
        if col not in header:
            raise SystemExit(f"to_txt: no column {col!r}; have {', '.join(header)}")
        k = header.index(col)
        # Numeric when the whole column is integral, lexical otherwise. Decided
        # per column over the actual data rather than by a flag, because a
        # lexical sort of a cycle count puts 1088 before 32 and the reader has
        # no way to see that it happened. Stable, so several --sort columns
        # compose right-to-left into one ordering.
        numeric = all(c[k].lstrip("-").isdigit() for c in body if k < len(c))
        body.sort(key=(lambda c: int(c[k])) if numeric else (lambda c: c[k]))

    if rows is not None:
        body = body[:rows]

    # Width per column over what is actually printed, so a narrow column stays
    # narrow instead of being padded to a value the file does not contain.
    w = [len(h) for h in header]
    for row in body:
        for i, cell in enumerate(row):
            if i < len(w):
                w[i] = max(w[i], len(cell))

    with open(dst, "w") as out:
        for c in comments:
            out.write(c + "\n")
        out.write("  ".join(h.rjust(w[i]) for i, h in enumerate(header)) + "\n")
        out.write("  ".join("-" * x for x in w) + "\n")
        for row in body:
            out.write("  ".join(c.rjust(w[i]) for i, c in enumerate(row)) + "\n")
        order = f" by {','.join(sort_cols)}" if sort_cols else ""
        if rows is not None and total > rows:
            out.write(f"# first {rows} of {total} rows, sorted{order}\n" if sort_cols
                      else f"# first {rows} of {total} rows\n")
        else:
            out.write(f"# {total} rows, sorted{order}\n" if sort_cols
                      else f"# {total} rows\n")

if __name__ == "__main__":
    main(sys.argv)
