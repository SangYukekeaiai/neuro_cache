"""Exercise the real launcher's argument suffix without building or simulating."""
import os
from pathlib import Path
import subprocess
import pytest


@pytest.mark.parametrize('gpus,memory,cores,deferred', [('1','100','72',True), ('4','420','288',False)])
def test_in_place_resize_uses_actual_gpu_shape(tmp_path,gpus,memory,cores,deferred):
    stub=tmp_path/'bash'
    stub.write_text('#!/bin/sh\nprintf "%s\\n" "$@"\n')
    stub.chmod(0o755)
    source=Path(__file__).with_name('job.sh').read_text()
    suffix='sample=$1\n'+source.split('sample=$1\n',1)[1]
    env={**os.environ,'PATH':str(tmp_path)+':'+os.environ['PATH'],
         'SLURM_JOB_PARTITION':'ghx4-interactive','SLURM_GPUS_ON_NODE':gpus}
    args=subprocess.check_output(['/bin/bash','-c','ROOT=/tmp\n'+suffix,'test','489','--count-only'],env=env,text=True).splitlines()
    last=lambda flag:args[max(i for i,s in enumerate(args) if s==flag)+1]
    assert last('--memory-gib')==memory and last('--cores')==cores
    assert ('--defer-oversize' in args)==deferred
    assert args[2]=='489' and '--count-only' in args
