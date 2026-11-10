#!/usr/bin/env python3
"""Build DIGITS.ttf: DejaVu Sans rescaled so its x-height matches Gill Sans at equal point size.

Numbers in the campaign figure render through mathtext in this face; words stay in Gill Sans
(GIL_____.TTF beside this script). Rerun only if either source font changes.
"""

from pathlib import Path

import matplotlib
from fontTools.ttLib import TTFont

ROOT = Path(__file__).resolve().parent
FAMILY = "DejaVu Sans Digits"
OUT = ROOT / "DIGITS.ttf"


def x_height_em(font):
    sx = getattr(font["OS/2"], "sxHeight", 0)
    if not sx:
        sx = font["glyf"]["x"].yMax
    return sx / font["head"].unitsPerEm


def main():
    gill = TTFont(ROOT / "GIL_____.TTF", fontNumber=0)
    source = Path(matplotlib.get_data_path()) / "fonts/ttf/DejaVuSans.ttf"
    digits = TTFont(source, fontNumber=0)
    ratio = x_height_em(digits) / x_height_em(gill)
    digits["head"].unitsPerEm = round(digits["head"].unitsPerEm * ratio)
    for record in digits["name"].names:
        if record.nameID in (1, 4, 6, 16):
            value = FAMILY.replace(" ", "") if record.nameID == 6 else FAMILY
            digits["name"].setName(value, record.nameID, record.platformID,
                                   record.platEncID, record.langID)
    digits.save(OUT)
    print(f"{OUT} unitsPerEm={digits['head'].unitsPerEm} (scale ratio {ratio:.4f})")


if __name__ == "__main__":
    main()
