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

Generate the architecture sweep configs:

```bash
python3 scripts/generate_arch_sweep.py
```

Run every generated architecture against every workload:

```bash
python3 scripts/run_arch_workload_sweep.py --skip-existing
```

Preview the full sweep without launching Gurobi:

```bash
python3 scripts/run_arch_workload_sweep.py --dry-run
```

Run the small VGG16 partial sweep:

```bash
PYTHONPATH=src python3 scripts/run_arch_workload_sweep.py \
  --nodes 36 1152 \
  --gb-sizes 64KB 128KB \
  --splits 30,1,1 24,4,4 \
  --workloads vgg16/conv1_1 vgg16/conv5_3
```

Output:

- `status`: Gurobi solve status.
- `objective`: final objective value when a solution exists.
- `strategy.NodeLevel.temporal_tile`: unordered remaining temporal factors.
- `strategy.NoCLevel.temporal_permutation`: NoC temporal order.
- `strategy.NoCLevel.spatial_splitting`: NoC spatial split.
- `strategy.DRAM.temporal_permutation`: DRAM temporal order.
