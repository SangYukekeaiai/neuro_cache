"""Transaction (TC) data structure for the SNN-CoSA NoC simulator.

Each TC represents one atomic NoC event: a unicast send, a multicast send,
or a PE computation count.  The list of TCs produced by combine.py is the
final output written to the CSV file.
"""

from __future__ import annotations
from json import JSONEncoder
from typing import List

# ---------------------------------------------------------------------------
# Operation codes  (must match the CSV reader convention)
# ---------------------------------------------------------------------------
UNICAST   = 0   # point-to-point send:  one src  → one dest
MULTICAST = 1   # one-to-many send:     one src  → multiple dests
COUNT     = 2   # computation counter:  one node runs for N cycles

# ---------------------------------------------------------------------------
# Network packet constants  (kept identical to CoSA for compatibility)
# ---------------------------------------------------------------------------
FLIT_SIZE   = 64    # bits per flit
FLITS_PER_PACKET = 4    # payload flits per packet  (1 header flit excluded)
PACKET_SIZE = FLIT_SIZE * FLITS_PER_PACKET   # 256 bits per packet


# ---------------------------------------------------------------------------
# TC  —  one transaction
# ---------------------------------------------------------------------------
class TC:
    """One atomic NoC transaction.

    Args:
        tc_id:      Unique integer ID assigned by TC_Generator.
        actor_id:   Node (PE) or port ID that originates this transaction.
        op:         UNICAST, MULTICAST, or COUNT.
        deps:       List of tc_ids that must complete before this TC can start.
        var_name:   Name of the tensor being transferred ("weight", "psum",
                    "vmem") or "" for COUNT.
        entries:    Number of tensor elements in the transfer (0 for COUNT).
        datawidth:  Bits per element (0 for COUNT).
        annotation: Human-readable description written as a CSV comment line.
    """

    def __init__(
        self,
        tc_id: int,
        actor_id: int,
        op: int,
        deps: List[int],
        var_name: str,
        entries: int,
        datawidth: int,
        annotation: str = "",
    ) -> None:
        self.tc_id      = tc_id
        self.actor_id   = actor_id
        self.op         = op
        self.deps       = deps          # list of prerequisite tc_ids
        self.var_name   = var_name
        self.entries    = entries       # number of data elements
        self.datawidth  = datawidth     # bits per element
        self.annotation = annotation

        self.srcs: List[int] = [actor_id]   # always the originating actor
        self.dests: List[int] = []           # filled by create_* methods
        self.size: int = 0                   # packets (unicast/multicast) or
                                             # cycles (count)

    # ------------------------------------------------------------------
    # Initializers — called once after __init__ to set dests and size
    # ------------------------------------------------------------------

    def create_unicast(self, dest: int, num_packets: int) -> None:
        """Configure as a point-to-point transfer to a single destination."""
        self.dests = [dest]
        self.size  = num_packets

    def create_multicast(self, dests: List[int], num_packets: int) -> None:
        """Configure as a one-to-many transfer to multiple destinations."""
        self.dests = list(dests)
        self.size  = num_packets

    def create_count(self, cycles: int) -> None:
        """Configure as a computation counter running for `cycles` cycles."""
        self.size = cycles

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    @staticmethod
    def _fmt(lst: List[int]) -> str:
        """Space-separated integer list for CSV columns."""
        return " ".join(str(x) for x in lst)

    def format_csv(self) -> str:
        """Return two lines: a comment header and the CSV data row.

        Column order:
            tc_id | actor_id | op | size | src | dest | dep
        """
        comment = f"# {self.annotation}\n"
        row = ",".join([
            str(self.tc_id),
            str(self.actor_id),
            str(self.op),
            str(self.size),
            self._fmt(self.srcs),
            self._fmt(self.dests),
            self._fmt(self.deps),
        ])
        return comment + row


# ---------------------------------------------------------------------------
# JSON serialisation helper (for optional .json output)
# ---------------------------------------------------------------------------
class TCEncoder(JSONEncoder):
    def default(self, o: object) -> object:
        if isinstance(o, TC):
            return o.__dict__
        return super().default(o)
