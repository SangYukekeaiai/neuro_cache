"""Independently validate Stage-2 prices and report physical-module energy shares.

Only reads completed reports; never imports aggregation/pricing/simulator code.
--profile dummy changes input filenames/labels for the T97 smoke check only.
Arithmetic uses relative and absolute tolerances of 1e-9; reference counts,
expressions, cycles and latency are compared exactly, with no tolerance.
"""

import argparse
import ast
from collections import Counter, defaultdict
import csv
import hashlib
import json
import math
import operator
from pathlib import Path
import sys


ARCHES = ("spinalflow", "ptb", "loas", "gustavsnn", "prosperity")
ARMS = ("spad", "cacheA", "cacheB")
EXCLUDED = {
    "cache.next_access_logic.step", "cache.distance_logic.step",
    "cache.next_access_state.rmw", "cache.distance_metadata.read",
    "cache.distance_metadata.write", "cache.l1_tags.read",
    "cache.next_line_l1.add", "cache.next_line_l2.add", "cache.l2_tags.read",
}
PRICE_FIELDS = ("dynamic_energy_nJ", "leakage_power_mW", "area_mm2")
TOLERANCE = 1e-9
DENOMINATOR = "sum(E_dyn_nJ + E_leak_nJ) of completed layer cases; not whole-model bars"
OPERATORS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
             ast.Div: operator.truediv, ast.FloorDiv: operator.floordiv, ast.Mod: operator.mod}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_csv(path):
    csv.field_size_limit(sys.maxsize)
    with path.open(newline="") as stream:
        reader = csv.DictReader(stream)
        require(reader.fieldnames and len(set(reader.fieldnames)) == len(reader.fieldnames),
                f"Missing/duplicate CSV fields: {path}")
        rows = list(reader)
    require(rows and all(None not in row and None not in row.values() for row in rows),
            f"Empty or malformed CSV: {path}")
    return rows


def structured(value):
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return ast.literal_eval(value)


def number(value, label):
    require(not isinstance(value, bool), f"Boolean numeric value: {label}")
    result = float(value)
    require(math.isfinite(result) and result >= 0, f"Nonfinite/negative value: {label}")
    return result


def truth(value):
    require(str(value).lower() in ("true", "false", "1", "0"), f"Invalid boolean: {value}")
    return str(value).lower() in ("true", "1")


def row_key(row):
    return tuple(row[k] for k in ("arch", "capture", "layer", "sample", "arm"))


def indexed(rows):
    result = {row_key(row): row for row in rows}
    require(len(result) == len(rows), "Duplicate layer result identities")
    return result


def evaluate(expression, values):
    def visit(node):
        if isinstance(node, ast.Constant) and type(node.value) in (int, float):
            return node.value
        if isinstance(node, ast.Name):
            return float(values[node.id])
        if isinstance(node, ast.BinOp) and type(node.op) in OPERATORS:
            return OPERATORS[type(node.op)](visit(node.left), visit(node.right))
        raise ValueError(f"Unsupported count expression: {expression}")
    return number(visit(ast.parse(expression, mode="eval").body), expression)


def owner_inventory(key, spec):
    namespace, module, _ = key.split(".")
    owner = namespace + "." + spec.get("physical_module", module)
    scope = spec.get("scope", "node" if namespace in ARCHES else "system")
    require(scope in ("node", "system"), f"Unknown inventory scope: {key}")
    instances = number(spec.get("physical_instances", 1), key + ".physical_instances")
    if namespace == "spinalflow" and module in ("adder32", "cmp32", "reg32") and scope == "node":
        instances = 4
    return owner, instances * (16 if scope == "node" else 1)


def source_values(key, row, provenance):
    arch, arm = row["arch"], row["arm"]
    if key in ("shared.router.hop", "shared.link.hop", arch + ".l1_weight_spad.write"):
        return provenance["noc"]
    if key.startswith(arch + "."):
        return provenance["counts"]
    return provenance["noc"] if arm == "spad" else provenance["cachesim"][arm]


def validate(args):
    suffix = "" if args.profile == "dummy" else "_ng45"
    paths = {"results": args.input / f"results{suffix}.csv",
             "whole_model": args.input / f"whole_model{suffix}.csv",
             "coverage": args.input / "coverage.json",
             "immutability": args.input / "immutability.json", "table": args.table}
    hashes = {key: digest(path) for key, path in paths.items()}
    if args.reference:
        hashes["reference"] = digest(args.reference)
    table = json.loads(args.table.read_text())
    coverage = json.loads(paths["coverage"].read_text())
    immutability = json.loads(paths["immutability"].read_text())
    rows = read_csv(paths["results"])
    models = read_csv(paths["whole_model"])
    by = indexed(rows)
    reference = indexed(read_csv(args.reference)) if args.reference else None
    if reference is not None:
        require(set(reference) == set(by), "Reference row identities differ")
    require(len(rows) == 559 * 3, "Expected exactly 559 x 3 result rows")
    require(len(models) == 120, "Expected 120 whole-model groups")
    require(coverage["status"] == "collected" and coverage["report_complete"] is True,
            "Stage-2 collection is incomplete")
    for field, expected in (("result_rows", 1677), ("whole_model_groups", 120),
                            ("completed_cases", 559), ("failed_cases", 0)):
        require(coverage[field] == expected, f"Coverage mismatch: {field}")
    require(not coverage.get("errors"), "Stage-2 reports errors")
    require(coverage["count_artifacts_unchanged"] is True and immutability["unchanged"] is True,
            "Count immutability failed")
    require(immutability["before_sha256"] == immutability["after_sha256"], "Count snapshot hashes differ")
    require(immutability["files"] > 0 and immutability["files"] == coverage["count_artifact_files"],
            "Count artifact inventory differs")
    for when in ("before", "after"):
        snapshot = args.input / f"counts_{when}.json"
        if snapshot.exists():
            require(digest(snapshot) == immutability[f"{when}_sha256"], f"Count snapshot hash mismatch: {when}")
    table_sha = hashes["table"]
    require(coverage.get("energy_table_sha256", coverage.get("dummy_table_sha256")) == table_sha,
            "Coverage table SHA differs")
    profile_name = "dummy" if args.profile == "dummy" else "nangate45"
    require(coverage.get("pricing_profile", "dummy") == profile_name, "Coverage pricing profile differs")
    require(truth(coverage["dummy_prices"]) == (args.profile == "dummy"), "Coverage dummy flag differs")
    require(EXCLUDED <= table.keys(), "Missing excluded table operations")
    marked = {key for key, spec in table.items() if spec.get("source") == "excluded_by_decision"}
    require(marked == EXCLUDED, "Expected exactly the nine excluded table operations")
    for key, spec in table.items():
        for field in PRICE_FIELDS:
            value = number(spec[field], key + "." + field)
            require(key not in EXCLUDED or value == 0, f"Excluded price is nonzero: {key}.{field}")

    errors = defaultdict(lambda: {"max_absolute_error": 0.0, "max_relative_error": 0.0, "checks": 0})

    def close(actual, expected, label):
        actual, expected = number(actual, label), number(expected, label)
        absolute = abs(actual - expected)
        relative = absolute / max(abs(actual), abs(expected)) if actual or expected else 0.0
        record = errors[label.split(":", 1)[0]]
        record["checks"] += 1
        record["max_absolute_error"] = max(record["max_absolute_error"], absolute)
        record["max_relative_error"] = max(record["max_relative_error"], relative)
        require(math.isclose(actual, expected, rel_tol=TOLERANCE, abs_tol=TOLERANCE),
                f"{label}: {actual} != {expected} (absolute error {absolute})")

    case_arms, grouped_rows = defaultdict(set), defaultdict(list)
    module_parts = defaultdict(lambda: [[], []])
    denominators, scope_cases = defaultdict(list), defaultdict(set)
    term_count = 0
    for row in rows:
        identity = row_key(row)
        arch, capture, layer, sample, arm = identity
        require(arch in ARCHES and arm in ARMS and sample == "0" and row["n"] == "1",
                f"Invalid result identity: {identity}")
        case_arms[(arch, capture, layer)].add(arm)
        require(row["energy_table_sha256"] == table_sha, f"Result table SHA differs: {identity}")
        expected_status = "DUMMY" if args.profile == "dummy" else "NG45_INTERIM"
        require(row["pricing_status"] == expected_status, f"Result pricing label differs: {identity}")
        require(truth(row["dummy_prices"]) == (args.profile == "dummy"), "Result dummy flag differs")
        terms = structured(row["breakdown"])
        provenance = structured(row["input_count_provenance"])
        require(terms and isinstance(terms, dict), f"No breakdown: {identity}")
        require(json.loads(row["counts_json"]) == provenance["counts"], f"Count sources differ: {identity}")
        cycles = number(row["total_cycles"], "cycles")
        seconds = number(row["T_s"], "latency")
        frequency = number(row["frequency_MHz"], "frequency")
        require(frequency == 500 and seconds == cycles / (frequency * 1e6), f"Cycle/time identity differs: {identity}")
        timing_source = provenance["noc"] if arm == "spad" else provenance["cachesim"][arm]
        require(cycles == number(timing_source["total_cycles"], "source cycles"), f"Source cycles differ: {identity}")
        if reference is not None:
            old = reference[identity]
            immutable = {key for key in row if key.startswith("count_")}
            require(immutable == {key for key in old if key.startswith("count_")}, "Count column set differs")
            for key in (*sorted(immutable), "counts_json", "total_cycles", "T_s", "frequency_MHz", "trace_sha256"):
                require(row[key] == old[key], f"Reference value differs exactly: {identity}/{key}")
            old_terms = structured(old["breakdown"])
            require(set(terms) == set(old_terms), f"Reference term set differs: {identity}")
            for key, term in terms.items():
                for field in ("count", "count_expression"):
                    require(term[field] == old_terms[key][field], f"Reference term differs exactly: {identity}/{key}/{field}")

        module_dynamic, inventory = defaultdict(list), {}
        for key, term in terms.items():
            require(key in table, f"Missing price: {key}")
            spec = table[key]
            count = number(term["count"], key + ".count")
            close(count, evaluate(term["count_expression"], source_values(key, row, provenance)),
                  f"count_evaluation:{identity}/{key}")
            energy = count * number(spec["dynamic_energy_nJ"], key)
            close(term["E_dyn_nJ"], energy, f"term_energy:{identity}/{key}")
            owner, instances = owner_inventory(key, spec)
            physical = (instances, number(spec["leakage_power_mW"], key), number(spec["area_mm2"], key))
            require(owner not in inventory or inventory[owner] == physical, f"Inconsistent physical owner: {owner}")
            inventory[owner] = physical
            module_dynamic[owner].append(energy)
            term_count += 1
        modules = {}
        for owner, (instances, power, area) in inventory.items():
            modules[owner] = (math.fsum(module_dynamic[owner]), power * instances * seconds * 1e6)
        dynamic = math.fsum(value[0] for value in modules.values())
        leakage = math.fsum(value[1] for value in modules.values())
        total = math.fsum(math.fsum(value) for value in modules.values())
        close(row["E_dyn_nJ"], dynamic, f"row_dynamic:{identity}")
        close(row["E_leak_nJ"], leakage, f"row_leakage:{identity}")
        close(number(row["E_dyn_nJ"], "dynamic") + number(row["E_leak_nJ"], "leakage"), total,
              f"row_module_total:{identity}")
        close(row["area_mm2"], math.fsum(n * area for n, _, area in inventory.values()), f"row_area:{identity}")
        close(row["EDP_nJ_s"], (dynamic + leakage) * seconds, f"row_edp:{identity}")
        grouped_rows[(arch, capture, arm)].append(row)
        for scope in ((arch, arm), (arch, "ALL")):
            denominators[scope].append(number(row["E_dyn_nJ"], "dynamic") + number(row["E_leak_nJ"], "leakage"))
            scope_cases[scope].add((capture, layer))
            for owner, values in modules.items():
                parts = module_parts[(*scope, owner)]
                parts[0].append(values[0])
                parts[1].append(values[1])

    require(len(case_arms) == 559 and all(arms == set(ARMS) for arms in case_arms.values()), "Case arm coverage differs")
    states = coverage["case_states"]
    require(set(states) == {"/".join(case) for case in case_arms} and set(states.values()) == {"complete"},
            "Coverage case identities/statuses differ")
    arch_counts = Counter(case[0] for case in case_arms)
    require(arch_counts == {arch: 107 if arch == "prosperity" else 113 for arch in ARCHES}, "Architecture case counts differ")
    infeasible = Counter((case["arch"], case["trace_relative_dir"]) for case in coverage["infeasible"])
    require(sum(infeasible.values()) == 6, "Expected six infeasible layers")
    model_keys, complete_groups, hatched_groups = set(), 0, 0
    captures = {row["capture"] for row in rows}
    for model in models:
        arch, capture, arm = key = (model["arch"], model["benchmark"], model["arm"])
        require(key not in model_keys, "Duplicate whole-model group")
        model_keys.add(key)
        group = grouped_rows.get(key, [])
        missing = infeasible[(arch, capture)]
        expected = len(group) + missing
        complete = bool(expected) and missing == 0
        require(truth(model["coverage_complete"]) == complete, f"Model completeness differs: {key}")
        for field, value in (("completed_layers", len(group)), ("feasible_layers", len(group)),
                             ("expected_layers", expected), ("infeasible_layers", missing),
                             ("failed_layers", 0), ("oom_layers", 0)):
            require(int(model[field]) == value, f"Whole-model coverage differs: {key}/{field}")
        require(model["coverage"] == f"{len(group)}/{expected}", f"Coverage label differs: {key}")
        require(model["energy_table_sha256"] == table_sha, f"Whole-model table SHA differs: {key}")
        require(model["pricing_status"] == expected_status and truth(model["dummy_prices"]) == (args.profile == "dummy"),
                f"Whole-model pricing label differs: {key}")
        complete_status = "complete_dummy_prices" if args.profile == "dummy" else "complete_ng45_interim"
        require(model["status"] == (complete_status if complete else "missing_layers"),
                f"Whole-model status differs: {key}")
        require(model["sample"] == "0" and model["n"] == "1", f"Whole-model sample differs: {key}")
        energy = math.fsum(float(row["E_dyn_nJ"]) + float(row["E_leak_nJ"]) for row in group)
        latency = math.fsum(float(row["T_s"]) for row in group)
        layer_edp = math.fsum(float(row["EDP_nJ_s"]) for row in group)
        for field, value in (("energy_nJ", energy), ("latency_s", latency), ("layer_EDP_nJ_s", layer_edp)):
            close(model["partial_sum_" + field], value, f"model_partial:{key}/{field}")
            if complete:
                close(model["sum_" + field], value, f"model_sum:{key}/{field}")
            else:
                require(model["sum_" + field] == "", f"Hatched model has total: {key}/{field}")
        if complete:
            close(model["model_EDP_nJ_s"], energy * latency, f"model_edp:{key}")
            complete_groups += 1
        else:
            require(model["model_EDP_nJ_s"] == "", f"Hatched model has EDP: {key}")
            hatched_groups += 1
    require(model_keys == {(arch, capture, arm) for arch in ARCHES for capture in captures for arm in ARMS},
            "Whole-model identity coverage differs")
    require((complete_groups, hatched_groups) == (117, 3), "Expected 117 complete groups and three hatches")

    full, top, groups = [], [], []
    for scope in sorted(denominators):
        denominator = math.fsum(denominators[scope])
        require(denominator > 0, f"Zero energy denominator: {scope}")
        base = {"scope": "arch_all_arms" if scope[1] == "ALL" else "arch_arm", "arch": scope[0],
                "arm": scope[1], "completed_cases": len(scope_cases[scope]),
                "case_arm_rows": len(denominators[scope]), "denominator_energy_nJ": denominator,
                "denominator_definition": DENOMINATOR + (" across all three arms" if scope[1] == "ALL" else " in this arm"),
                "pricing_profile": profile_name, "pricing_status": expected_status,
                "energy_table_sha256": table_sha}
        members = []
        for (arch, arm, owner), parts in module_parts.items():
            if (arch, arm) != scope:
                continue
            dynamic, leakage = (math.fsum(part) for part in parts)
            total = dynamic + leakage
            members.append({**base, "physical_module": owner, "E_dyn_nJ": dynamic,
                            "E_leak_nJ": leakage, "E_total_nJ": total, "energy_share": total / denominator})
        members.sort(key=lambda member: (-member["E_total_nJ"], member["physical_module"]))
        close(math.fsum(member["E_total_nJ"] for member in members), denominator, f"scope_module_total:{scope}")
        for rank, member in enumerate(members, 1):
            member["rank"] = rank
        full.extend(members)
        top.extend(members[:3])
        groups.append({**base, "top3": members[:3]})
    for key, path in paths.items():
        require(digest(path) == hashes[key], f"Input changed during validation: {path}")
    if args.reference:
        require(digest(args.reference) == hashes["reference"], "Reference changed during validation")
    validation = {"status": "passed" if reference is not None else "passed_without_reference",
                  "profile": profile_name, "input_hashes": hashes, "source_paths": {k: str(v) for k, v in paths.items()},
                  "reference": str(args.reference) if args.reference else None,
                  "reference_counts_expressions_cycles_latency_exact": reference is not None,
                  "reference_note": "exact comparison completed" if reference is not None else "NOT CHECKED: supply --reference for T97 immutability comparison",
                  "rows": len(rows), "cases": len(case_arms), "terms": term_count,
                  "cases_per_architecture": dict(arch_counts), "complete_whole_models": complete_groups,
                  "hatched_whole_models": hatched_groups, "excluded_operations": sorted(EXCLUDED),
                  "table_operations": len(table), "all_prices_finite_nonnegative": True,
                  "arithmetic_tolerance": {"relative": TOLERANCE, "absolute": TOLERANCE},
                  "arithmetic_checks": dict(errors), "denominator_definition": DENOMINATOR,
                  "aggregation_imports": False, "simulator_or_pricing_executed": False}
    return full, top, groups, validation


def save_json(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--table", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--reference", type=Path)
    parser.add_argument("--profile", choices=("ng45", "dummy"), default="ng45")
    args = parser.parse_args()
    args.input, args.table, args.out = args.input.resolve(), args.table.resolve(), args.out.resolve()
    if args.reference:
        args.reference = args.reference.resolve()
    require(args.out != args.input and not args.input.is_relative_to(args.out), "Output overlaps input root")
    require(not args.out.exists() or (args.out.is_dir() and not any(args.out.iterdir())), "Output must be new or empty")
    args.out.mkdir(parents=True, exist_ok=True)
    try:
        full, top, groups, validation = validate(args)
    except (ValueError, KeyError, TypeError, OSError, SyntaxError, ZeroDivisionError) as error:
        save_json(args.out / "validation.json", {"status": "failed", "error": str(error),
                  "profile": args.profile, "input": str(args.input), "table": str(args.table)})
        print(f"Validation failed: {error}", file=sys.stderr)
        return 1
    for name, rows in (("full_module_energy.csv", full), ("top3.csv", top)):
        with (args.out / name).open("w", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
    save_json(args.out / "top3.json", {"profile": args.profile, "groups": groups})
    save_json(args.out / "validation.json", validation)
    print(json.dumps({"status": validation["status"], "rows": validation["rows"],
                      "module_rows": len(full), "top3_rows": len(top), "out": str(args.out)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
