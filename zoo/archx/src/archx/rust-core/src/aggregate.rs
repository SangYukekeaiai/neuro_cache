use std::collections::HashSet;
use petgraph::graph::{DiGraph, NodeIndex};
use petgraph::visit::EdgeRef;
use petgraph::Direction;
use log::{debug, info, error};

use crate::graph::{NodeData, EdgeData};
use crate::metric::{MetricValue, fmt_py};
use crate::paths::{all_paths, topological_sort_subgraph};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

fn is_leaf(graph: &DiGraph<NodeData, EdgeData>, idx: NodeIndex) -> bool {
    graph.neighbors_directed(idx, Direction::Outgoing).next().is_none()
}

/// Unit string of a node's metric (every node carries the metric unit after init).
fn metric_unit(graph: &DiGraph<NodeData, EdgeData>, idx: NodeIndex, metric: &str) -> String {
    match graph[idx].metrics.get(metric) {
        Some(MetricValue::Single(s)) => s.unit.clone(),
        Some(MetricValue::MultiOp(ops)) => ops.values().next().map(|s| s.unit.clone()).unwrap_or_default(),
        None => String::new(),
    }
}

/// Get the metric value from a target node, resolving multi-op via the edge's operation map.
/// Mirrors the Python `get_metric_value`, including its operation-legality assertion.
fn get_metric_value(
    graph: &DiGraph<NodeData, EdgeData>,
    edge_src: NodeIndex,
    edge_tgt: NodeIndex,
    metric: &str,
) -> Result<f64, String> {
    let node = &graph[edge_tgt];
    match node.metrics.get(metric) {
        Some(MetricValue::Single(s)) => Ok(s.value),
        Some(MetricValue::MultiOp(ops)) => {
            // look up which operation this edge specifies
            let edge_idx = graph.find_edge(edge_src, edge_tgt)
                .ok_or_else(|| format!("Edge '{}' -> '{}' not found", graph[edge_src].name, node.name))?;
            let op = graph[edge_idx].operation.get(metric)
                .ok_or_else(|| format!(
                    "Invalid operation for metric '{}' in module '{}'; multi-operation module requires an operation",
                    metric, node.name))?
                .to_lowercase();
            match ops.get(&op) {
                Some(s) => Ok(s.value),
                None => {
                    let msg = format!(
                        "Invalid operation <{}> for metric <{}> in module <{}>; legal values: {:?}.",
                        op, metric, node.name, ops.keys().collect::<Vec<_>>());
                    error!("{}", msg);
                    Err(msg)
                }
            }
        }
        None => Ok(0.0),
    }
}

/// Compute total path count * factor from workload_idx to event_idx.
pub fn compute_path_count(
    graph: &DiGraph<NodeData, EdgeData>,
    workload_idx: NodeIndex,
    event_idx: NodeIndex,
    metric: &str,
) -> f64 {
    let paths = all_paths(graph, workload_idx, event_idx);
    let mut total = 0.0;
    for path in &paths {
        let mut path_count = 1.0;
        let mut path_factor = 1.0;
        for &eidx in path {
            path_count *= graph[eidx].count;
            if let Some(&f) = graph[eidx].factor.get(metric) {
                path_factor *= f;
            }
            let (s, t) = graph.edge_endpoints(eidx).unwrap();
            debug!("  Path (<{}> -> <{}>) updates event count to <{}> and event factor to <{}>.",
                   graph[s].name, graph[t].name, fmt_py(path_count), fmt_py(path_factor));
        }
        let delta = path_count * path_factor;
        total += delta;
        debug!("  Total event count (<{}> -> <{}>) is increased by <{}> = count <{}> * factor <{}>.",
               graph[workload_idx].name, graph[event_idx].name, fmt_py(delta), fmt_py(path_count), fmt_py(path_factor));
    }
    total
}

// ---------------------------------------------------------------------------
// Mode: module
// ---------------------------------------------------------------------------

/// Recursively sum all leaf nodes reachable from `current`, multiplied by instance count.
/// Already-visited leaves are skipped to avoid double-counting shared modules.
/// `top_event` is the name of `current`'s parent (the start event for the first call),
/// reproducing the Python trace messages.
pub fn aggregate_module(
    graph: &DiGraph<NodeData, EdgeData>,
    current: NodeIndex,
    top_event: &str,
    metric: &str,
    evaluated: &mut HashSet<NodeIndex>,
) -> Result<f64, String> {
    if is_leaf(graph, current) {
        if !evaluated.insert(current) {
            info!("Ignore repeated module <{}>.", graph[current].name);
            return Ok(0.0); // already counted
        }
        let node = &graph[current];
        // Mirrors Python's `key_list == [value, unit]` assertion: a module's metric
        // must be single-operation for 'module' aggregation.
        let s = match node.metrics.get(metric) {
            Some(MetricValue::Single(s)) => s,
            _ => {
                let msg = format!("Invalid metric <{}> for module <{}>.", metric, node.name);
                error!("{}", msg);
                return Err(msg);
            }
        };
        info!("Aggregate metric <{}> for module <{}> in event <{}>.", metric, node.name, top_event);
        let total = s.value * node.instance;
        debug!("  Total value (<{}> -> <{}>) = <{}> <{}> = single value <{}> * instance <{}>.",
               top_event, node.name, fmt_py(total), s.unit, fmt_py(s.value), fmt_py(node.instance));
        Ok(total)
    } else {
        let mut total = 0.0;
        // Borrow the name (no clone): it is both the log subject and the children's top_event.
        let name: &str = &graph[current].name;
        let children: Vec<NodeIndex> =
            graph.neighbors_directed(current, Direction::Outgoing).collect();
        for child in children {
            debug!("  Check subevent <{}> -> <{}>.", name, graph[child].name);
            total += aggregate_module(graph, child, name, metric, evaluated)?;
        }
        Ok(total)
    }
}

// ---------------------------------------------------------------------------
// Mode: summation
// ---------------------------------------------------------------------------

/// Bottom-up topological aggregation.
/// For each node: parent.metric += count * child_value * factor  for each in-edge.
pub fn aggregate_summation(
    graph: &mut DiGraph<NodeData, EdgeData>,
    start: NodeIndex,
    metric: &str,
) -> Result<(), String> {
    let topo = topological_sort_subgraph(graph, start); // leaves first
    let topo_set: HashSet<NodeIndex> = topo.iter().copied().collect();

    for &v in &topo {
        if is_leaf(graph, v) {
            info!("Aggregate metric <{}> for module <{}>.", metric, graph[v].name);
        } else {
            info!("Aggregate metric <{}> for event <{}>.", metric, graph[v].name);
        }

        // Collect in-edge data first (cannot borrow graph mutably and immutably at once).
        let in_edges: Vec<(NodeIndex, f64, f64)> = graph
            .edges_directed(v, Direction::Incoming)
            .filter(|e| topo_set.contains(&e.source()))
            .map(|e| {
                let factor = e.weight().factor.get(metric).copied().unwrap_or(1.0);
                (e.source(), e.weight().count, factor)
            })
            .collect();

        for (src, count, factor) in in_edges {
            let child_val = get_metric_value(graph, src, v, metric)?;
            let contrib = count * child_val * factor;
            if let Some(m) = graph[src].metrics.get_mut(metric) {
                m.as_single_mut().value += contrib;
            }
            // metric_unit() is inlined into the args so the String clone happens
            // only when DEBUG is actually enabled.
            debug!("  Total value (<{}> -> <{}>) = <{}> <{}> = single value <{}> * count <{}> * factor <{}>.",
                   graph[src].name, graph[v].name, fmt_py(contrib), metric_unit(graph, src, metric),
                   fmt_py(child_val), fmt_py(count), fmt_py(factor));
        }
    }
    Ok(())
}

/// Special case: multi-op leaf with workload specified.
/// Enumerate all paths from workload → event, determine operation per path,
/// accumulate per-op count, then compute total = Σ op_value * op_count.
pub fn aggregate_summation_multiop(
    graph: &DiGraph<NodeData, EdgeData>,
    workload_idx: NodeIndex,
    event_idx: NodeIndex,
    metric: &str,
) -> Result<f64, String> {
    let paths = all_paths(graph, workload_idx, event_idx);

    // op → (metric_value, accumulated_count). `op_order` preserves first-seen order
    // so the final per-op trace is deterministic rather than hash-ordered.
    let mut op_metric: std::collections::HashMap<String, f64> = std::collections::HashMap::new();
    let mut op_count: std::collections::HashMap<String, f64> = std::collections::HashMap::new();
    let mut op_order: Vec<String> = Vec::new();

    for path in &paths {
        let mut path_count = 1.0;
        let mut path_factor = 1.0;

        for &eidx in path {
            path_count *= graph[eidx].count;
            if let Some(&f) = graph[eidx].factor.get(metric) {
                path_factor *= f;
            }
            let (s, t) = graph.edge_endpoints(eidx).unwrap();
            debug!("  Path (<{}> -> <{}>) updates event count to <{}> and event factor to <{}>.",
                   graph[s].name, graph[t].name, fmt_py(path_count), fmt_py(path_factor));
        }

        // Operation is on the last edge (parent → module)
        if let Some(&edge_idx) = path.last() {
            let node = &graph[event_idx];
            // A multi-operation module requires the edge to name a valid operation
            // for this metric. Reject a missing/invalid operation (rather than
            // silently scoring 0) to match the pure-Python engine, which errors.
            let op = match graph[edge_idx].operation.get(metric) {
                Some(o) => o.to_lowercase(),
                None => return Err(format!(
                    "Missing operation for metric <{}> in multi-operation module <{}>; legal values: {:?}.",
                    metric, node.name, node.metrics[metric].op_names())),
            };
            let mval = match node.metrics[metric].get_op_value(&op) {
                Some(v) => v,
                None => return Err(format!(
                    "Invalid operation <{}> for metric <{}> in module <{}>; legal values: {:?}.",
                    op, metric, node.name, node.metrics[metric].op_names())),
            };
            if !op_metric.contains_key(&op) {
                op_order.push(op.clone());
            }
            op_metric.insert(op.clone(), mval);
            let delta = path_count * path_factor;
            *op_count.entry(op.clone()).or_insert(0.0) += delta;
            debug!("  Total event count (<{}> : <{}>) is increased by <{}> = count <{}> * factor <{}>.",
                   graph[event_idx].name, op, fmt_py(delta), fmt_py(path_count), fmt_py(path_factor));
        }
    }

    let mut total = 0.0;
    for op in &op_order {
        let val = op_metric[op];
        let cnt = op_count.get(op).copied().unwrap_or(0.0);
        let contrib = val * cnt;
        total += contrib;
        debug!("  Total value (<{}> : <{}>) = <{}> <{}> = single value <{}> * count <{}>.",
               graph[event_idx].name, op, fmt_py(contrib), metric_unit(graph, event_idx, metric), fmt_py(val), fmt_py(cnt));
    }
    Ok(total)
}

// ---------------------------------------------------------------------------
// aggregate_event_count — path count using edge counts only (no factor)
// ---------------------------------------------------------------------------

/// Count how many times `event` executes under `workload` by summing the
/// product of edge counts over every path from workload → event.
pub fn aggregate_event_count(
    graph: &DiGraph<NodeData, EdgeData>,
    workload_idx: NodeIndex,
    event_idx: NodeIndex,
) -> f64 {
    let paths = all_paths(graph, workload_idx, event_idx);
    let mut total = 0.0;
    for path in &paths {
        let mut path_count = 1.0;
        for &eidx in path {
            path_count *= graph[eidx].count;
            let (s, t) = graph.edge_endpoints(eidx).unwrap();
            debug!("  Path (<{}> -> <{}>) updates event count to <{}>.",
                   graph[s].name, graph[t].name, fmt_py(path_count));
        }
        total += path_count;
        debug!("  Total event count (<{}> -> <{}>) is increased by <{}>.",
               graph[workload_idx].name, graph[event_idx].name, fmt_py(path_count));
    }
    total
}

// ---------------------------------------------------------------------------
// Mode: specified
// ---------------------------------------------------------------------------

/// Parallel/sequential aggregation over non-leaf children only.
/// Leaf children are ignored (their values come from performance models via specified_metrics).
pub fn aggregate_specified(
    graph: &mut DiGraph<NodeData, EdgeData>,
    start: NodeIndex,
    metric: &str,
) -> Result<(), String> {
    let topo = topological_sort_subgraph(graph, start); // leaves first

    for &v in &topo {
        if is_leaf(graph, v) {
            info!("Ignore module <{}>.", graph[v].name);
            continue;
        }
        info!("Aggregate metric <{}> for event <{}>.", metric, graph[v].name);

        // Collect out-edge data before mutating
        let out_data: Vec<(NodeIndex, f64, f64, String, bool)> = graph
            .edges_directed(v, Direction::Outgoing)
            .map(|e| {
                let tgt = e.target();
                let count = e.weight().count;
                let factor = e.weight().factor.get(metric).copied().unwrap_or(1.0);
                let agg = e.weight().aggregation.clone();
                let tgt_is_leaf = is_leaf(graph, tgt);
                (tgt, count, factor, agg, tgt_is_leaf)
            })
            .collect();

        let mut parallel_max: f64 = 0.0;
        let mut sequential_acc: f64 = 0.0;
        let mut connect_leaf_only = true;
        let mut connect_leaf_any = false;

        for (tgt, count, factor, agg, tgt_is_leaf) in &out_data {
            if *tgt_is_leaf {
                // Mirrors Python L460: a module under 'specified' must be single-operation.
                match graph[*tgt].metrics.get(metric) {
                    Some(MetricValue::Single(_)) => {}
                    _ => {
                        let msg = format!(
                            "Invalid metric <{}> for event <{}>; legal metric: {{'value': float, 'unit': str}}.",
                            metric, graph[*tgt].name);
                        error!("{}", msg);
                        return Err(msg);
                    }
                }
                connect_leaf_any = true;
                debug!("  Ignore module <{}>.", graph[*tgt].name);
            } else {
                connect_leaf_only = false;
                let child_val = match graph[*tgt].metrics.get(metric) {
                    Some(m) => m.as_single().value,
                    None => 0.0,
                };
                let contribution = child_val * count * factor;
                debug!("  Total value (<{}>) = <{}> <{}> = single value <{}> * count <{}> * factor <{}>.",
                       graph[*tgt].name, fmt_py(contribution), metric_unit(graph, *tgt, metric),
                       fmt_py(child_val), fmt_py(*count), fmt_py(*factor));
                if agg == "parallel" {
                    if contribution > parallel_max {
                        debug!("  Update parallel maximum metric value to <{}>, based on event <{}>.",
                               fmt_py(contribution), graph[*tgt].name);
                        parallel_max = contribution;
                    }
                } else {
                    debug!("  Update sequential accumulated metric value by <{}>, based on event <{}>.",
                           fmt_py(contribution), graph[*tgt].name);
                    sequential_acc += contribution;
                }
            }
        }

        // Mirrors Python case2 (L493): a node connected to no modules must not carry an injected metric.
        if !connect_leaf_any && graph[v].specified_metrics.contains_key(metric) {
            let msg = format!(
                "  Invalid metric <{}> in event <{}>, since it is connected to no modules; check the performance model.",
                metric, graph[v].name);
            error!("{}", msg);
            return Err(msg);
        }

        let result = if connect_leaf_only {
            // Mirrors Python case1 (L488): a node connected only to modules must have a
            // value injected by its performance model.
            match graph[v].specified_metrics.get(metric) {
                Some(s) => s.value,
                None => {
                    let msg = format!(
                        "  Missing metric <{}> in event <{}>, since it is only connected to modules; check the performance model.",
                        metric, graph[v].name);
                    error!("{}", msg);
                    return Err(msg);
                }
            }
        } else {
            sequential_acc + parallel_max
        };

        if let Some(m) = graph[v].metrics.get_mut(metric) {
            m.as_single_mut().value = result;
        }
        debug!("  Total value (<{}>) = <{}> <{}>.", graph[v].name, fmt_py(result), metric_unit(graph, v, metric));
    }
    Ok(())
}
