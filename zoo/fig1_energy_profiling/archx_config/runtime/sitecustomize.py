"""Limit the archx CLI's batch pool within this launch environment."""
import os
os.cpu_count = lambda: 1
