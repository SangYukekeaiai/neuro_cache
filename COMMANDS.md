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
- `schedule.levels`: selected factor placement by loop level.
- `schedule.readable`: fused temporal/spatial order per memory region.
- `schedule.summary`: spatial and temporal tile products per memory region.
- `costs`: per-variable footprint and traffic terms.
