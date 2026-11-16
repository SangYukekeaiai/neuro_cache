"""Logic-only Accelergy unit check; not the campaign's complete memory ERT."""
from decimal import Decimal
import csv
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import yaml

root=Path(__file__).resolve().parents[1]
table=root/'inputs/energy_table_asap7_syn.json'
bank=json.loads(table.read_text())
key='loas.adder16.add'
prices=[v['operations'][key]['dynamic_energy_nJ'] for k,v in bank['variants'].items() if k.startswith('loas/')]
assert len(set(prices))==1
expected_pj=Decimal('0.00855238')  # Five additions at the frozen 0.000001710476 nJ/add.
output=root/'outputs/self_checks/ert_logic';output.mkdir(parents=True,exist_ok=True)
ert={'ERT':{'version':0.3,'tables':[{'name':'audit.adder16','actions':[{'name':'add','arguments':None,'energy':prices[0]*1000}]}]}}
counts={'action_counts':{'version':0.3,'local':[{'name':'audit.adder16','action_counts':[{'name':'add','counts':5}]}]}}
for name,obj in [('ERT.yaml',ert),('action_counts.yaml',counts)]:
    (output/name).write_text(yaml.safe_dump(obj,sort_keys=False))
(output/'accelergy_config.yaml').write_text(yaml.safe_dump({'version':0.3,'estimator_plug_ins':[],'primitive_components':[str(root/'vendor/paper_backend/accelergy/share/primitive_component_libs')],'compound_components':[]}))
command=[str(Path(sys.executable).with_name('accelergy')),'ERT.yaml','action_counts.yaml','-o','.', '-p','15','-f','energy_estimation']
with (output/'accelergy.log').open('w') as stream:
    subprocess.run(command,cwd=output,stdout=stream,stderr=subprocess.STDOUT,check=True,timeout=30)
result=yaml.safe_load((output/'energy_estimation.yaml').read_text())
actual=Decimal(str(result['energy_estimation']['Total']))
relative=abs(actual-expected_pj)/expected_pj
assert relative<Decimal('.001'),(actual,expected_pj,relative)
record=dict(scope='logic unit conversion only; complete campaign ERT pending memory decision',operation=key,count=5,
            expected_pJ=str(expected_pj),accelergy_pJ=str(actual),relative_error=str(relative),
            source_table_sha256=hashlib.sha256(table.read_bytes()).hexdigest(),command=command)
(output/'verification.json').write_text(json.dumps(record,indent=2)+'\n')
with (root/'outputs/ert_logic_identity_check.csv').open('w',newline='') as f:
    w=csv.DictWriter(f,fieldnames=['operation','count','expected_pJ','accelergy_pJ','relative_error','source_table_sha256']);w.writeheader();w.writerow({k:record[k] for k in w.fieldnames})
print(json.dumps(record))
