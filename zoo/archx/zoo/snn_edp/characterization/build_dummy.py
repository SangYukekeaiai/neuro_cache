"""Build explicitly nonfinal dummy prices from the archived composition draft."""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import tarfile


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive',type=Path,required=True)
    args=parser.parse_args()
    c=Path(__file__).resolve().parent; m=c.parent
    h=json.loads((m/'hardware.json').read_text())
    # Preserve archived magnitudes as data, never restore the rejected pricing implementation.
    archive=args.archive.resolve()
    with tarfile.open(archive) as t: old=json.load(t.extractfile('zoo/snn_edp/characterization/energy_table_mapped.json'))
    aliases=json.loads((m/'provenance/operation_renames.json').read_text())['operation_keys']
    old={aliases.get(k,k):v for k,v in old.items()}
    historical_keys={v:k for k,v in aliases.items()}
    base=json.loads((m/'energy_table.json').read_text()); dummy=copy.deepcopy(base)
    metrics=('dynamic_energy_nJ','leakage_power_mW','area_mm2')
    for k,r in dummy.items():
     if not r.get('placeholder'):continue
     r['assumption']='DUMMY placeholder pending ASAP7 synthesis'
     r['placeholder']='DUMMY placeholder pending ASAP7 synthesis'
     r['source']='dummy-placeholder';r['dummy']=True
     retired=json.loads((m/'provenance/retired_logic.json').read_text())['rows']
     if k in retired:
      r['assumption']='DUMMY (magnitude from retired tnn characterization) pending ASAP7 synthesis'
      r['dummy_basis']={'kind':'historical retired characterization magnitude, not active source','retired_record':'provenance/retired_logic.json','key':k}
      for x in metrics:r[x]=retired[k][x]
      continue
     if all(old[k].get(x) is not None for x in metrics):
      for x in metrics:r[x]=old[k][x]
      r['dummy_basis']={'kind':'archived composition estimate; rejected as final characterization','archive':str(archive),'archive_sha256':hashlib.sha256(archive.read_bytes()).hexdigest(),'key':historical_keys.get(k,k),'original_assumption':old[k].get('assumption')}
     else:
      if k.startswith('prosperity.tcam.'):
       # Only a dummy scale reference: 4096 stored bits vs 1024-bit reference CAM.
       ref=old['cache.mshr_cam_l1.search'];vals={x:4*ref[x] for x in metrics}
       why='DUMMY4x archived16x64 binary-CAM magnitude for256x16 subset-match flop array; search/write share inventory; not measured subset-match energy.'
      elif k=='shared.router.hop':
       vals=dict(zip(metrics,(0.00032,1.0,0.01)));why='DUMMY arbitrary sensitivity point:1fJ/bit x320bits=0.00032nJ/packet-hop,1mW and0.01mm2/router; no validated physical source.'
      else:raise ValueError(k)
      r.update(vals);r['dummy_basis']={'kind':'stated uncharacterized placeholder','description':why}
     if 'implementation' in h[k]:r['implementation']=h[k]['implementation']
    for k,r in h.items():
     if 'implementation' in r:dummy[k]['implementation']=r['implementation']
    assert all(all(r[x] is not None for x in metrics) for r in dummy.values())
    (c/'energy_table_dummy.json').write_text(json.dumps(dummy,indent=2,sort_keys=True,allow_nan=False)+'\n')
    manifest={'purpose':'DUMMY placeholder pending ASAP7 synthesis','default_table_sha256':hashlib.sha256((m/'energy_table.json').read_bytes()).hexdigest(),'dummy_table_sha256':hashlib.sha256((c/'energy_table_dummy.json').read_bytes()).hexdigest(),'dummy_rows':[k for k,r in dummy.items() if r.get('dummy')],'excluded_rows':json.loads((c/'pricing_policy.json').read_text())['excluded_operations'],'archived_basis':str(archive),'hardware_sha256':hashlib.sha256((m/'hardware.json').read_bytes()).hexdigest()}
    (c/'energy_table_dummy.manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print(manifest['dummy_table_sha256'])


if __name__=='__main__':main()
