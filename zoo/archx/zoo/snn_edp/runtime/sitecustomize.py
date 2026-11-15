"""Bound the unconfigurable archx batch pool in this launch environment only."""
import os
os.cpu_count = lambda: 1

import archx
import sys
print('archx.__file__=' + archx.__file__, file=sys.stderr, flush=True)
