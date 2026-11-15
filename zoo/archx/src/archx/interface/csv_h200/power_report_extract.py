
import json
from collections import defaultdict
import csv
import os
import glob

current_dir = os.path.dirname(os.path.abspath(__file__))
csv_dir = os.path.join(current_dir, "include/csv/")

if not os.path.exists(csv_dir):
    os.makedirs(csv_dir)

# Find power_report*.json
json_files = glob.glob(os.path.join(current_dir, "power_report*.json"))
if not json_files:
    raise FileNotFoundError("No power_report*.json file found in directory.")
import re
for power_report_path in json_files:
    match = re.match(r"power_report(.*)\.json", os.path.basename(power_report_path))
    extra_str = match.group(1) if match else ""
    with open(power_report_path, "r") as f:
        data = json.load(f)
    kernels = data.get("kernels", [])
    for kernel in kernels:
        kernel_id = kernel.get("kernel_id", "")
        power = kernel.get("raw_power_w")
        runtime = kernel.get("avg_duration_us")
        n_kernels = kernel.get("frequency")
        if not kernel_id:
            continue
        csv_path = os.path.join(csv_dir, f"{kernel_id.lower()}{extra_str}.csv")
        with open(csv_path, "w", newline="") as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=["power_w", "runtime_us", "n_kernels"])
            writer.writeheader()
            writer.writerow({
                "power_w": power,
                "runtime_us": runtime,
                "n_kernels": n_kernels
            })