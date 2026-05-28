# SNN CoSA Commands

Run commands from the project root:

```bash
cd /home/yy/projects/snn_cosa
conda activate cosa_snn
export PYTHONPATH=src
```

Install dependencies:

```bash
python -m pip install -r requirements.txt
```

Solve the sample layer and write the final schedule:

```bash
python -m snn_cosa solve \
  --layer configs/workloads/sample_snn_layer.yaml \
  --arch configs/arch/snn_arch.yaml \
  --mapspace configs/mapspace/mapspace.yaml \
  --out outputs/sample_schedule.json
```

Useful options:

```bash
python -m snn_cosa solve --time-limit 60 --mip-gap 0.01 --solver-log
```

Output:

- `status`: Gurobi solve status.
- `objective`: final objective value when a solution exists.
- `strategy.NodeLevel.rest_temporal_permutation`: remaining temporal order.
- `strategy.NoCLevel.temporal_permutation`: NoC temporal order.
- `strategy.NoCLevel.spatial_splitting`: NoC spatial split.
- `strategy.DRAM.temporal_permutation`: DRAM temporal order.
