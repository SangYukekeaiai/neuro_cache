"""Read the canonical workload rule; attention projections take precedence."""
import hashlib
from pathlib import Path
import re

SCOPE_PATH = Path(__file__).resolve().parents[2]/'docs/workload_layer_scope.md'


def scope_rule():
    content = SCOPE_PATH.read_bytes()
    text = content.decode()
    keep, = re.findall(r'^KEEP\s+if\s+(.+)$', text, re.MULTILINE)
    skip, = re.findall(r'^SKIP\s+if\s+(.+)$', text, re.MULTILINE)
    return re.compile(keep), re.compile(skip), hashlib.sha256(content).hexdigest()


def kept(layer):
    keep, skip, _ = scope_rule()
    return bool(keep.search(layer)) or not skip.search(layer)


def scoped_selection(selection):
    return {**selection, **{kind: [c for c in selection[kind] if kept(c['layer'])]
                          for kind in ('feasible', 'infeasible')}}


def scope_summary(selection):
    selected = scoped_selection(selection)
    nominal = {(c['trace_relative_dir'], c['layer'])
               for kind in ('feasible', 'infeasible') for c in selection[kind]}
    kept_layers = sum(kept(layer) for _, layer in nominal)
    return {'source': str(SCOPE_PATH), 'sha256': scope_rule()[2],
            'kept_layers': kept_layers, 'excluded_layers': len(nominal)-kept_layers,
            'kept_feasible_pairs': len(selected['feasible']),
            'kept_infeasible_pairs': len(selected['infeasible']),
            'excluded_feasible_pairs': len(selection['feasible'])-len(selected['feasible'])}
