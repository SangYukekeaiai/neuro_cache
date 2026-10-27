import pathlib
import sys

# scripts/ is not a package; tests import its modules (pipeline) by name.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent / "scripts"))
