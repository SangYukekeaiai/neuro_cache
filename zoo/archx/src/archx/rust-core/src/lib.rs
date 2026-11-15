use std::collections::HashMap;
use indexmap::IndexMap;
use pyo3::prelude::*;
use pyo3::types::PyDict;
use log::{debug, warn, error};

mod graph;
mod metric;
mod aggregate;
mod paths;

use graph::ArchxGraphInner;
use metric::{MetricValue, SingleMetric, fmt_py};
use aggregate::{
    aggregate_module, aggregate_summation, aggregate_summation_multiop,
    aggregate_specified, compute_path_count, aggregate_event_count,
};

// ---------------------------------------------------------------------------
// ArchxGraph — the PyO3 class exposed to Python
// ---------------------------------------------------------------------------

#[pyclass]
pub struct ArchxGraph {
    inner: ArchxGraphInner,
}

#[pymethods]
impl ArchxGraph {
    #[new]
    fn new() -> Self {
        ArchxGraph { inner: ArchxGraphInner::new() }
    }

    // ---- Construction ------------------------------------------------------

    fn add_node(&mut self, name: &str, performance: Option<&str>) -> PyResult<()> {
        self.inner.add_node(name, performance);
        Ok(())
    }

    /// Add a directed edge. Returns True if an edge for this (source, target)
    /// already existed and was merged (no parallel edge created), else False.
    fn add_edge(&mut self, source: &str, target: &str) -> PyResult<bool> {
        let (_, merged) = self.inner.add_edge(source, target)
            .map_err(|e| pyo3::exceptions::PyValueError::new_err(e))?;
        Ok(merged)
    }

    fn has_node(&self, name: &str) -> bool {
        self.inner.has_node(name)
    }

    // ---- Inspection --------------------------------------------------------

    fn get_all_node_names(&self) -> Vec<String> {
        self.inner.all_node_names()
    }

    fn get_leaf_names(&self) -> Vec<String> {
        self.inner.leaf_names()
    }

    /// Leaf module names carrying `tag`, in leaf insertion order. Lets the Python
    /// tag-aggregation wrapper drive the per-module loop itself (matching main).
    fn get_tag_modules(&self, tag: &str) -> Vec<String> {
        self.inner.leaf_indices().iter()
            .filter(|&&idx| self.inner.graph[idx].tags.iter().any(|t| t == tag))
            .map(|&idx| self.inner.graph[idx].name.clone())
            .collect()
    }

    fn is_leaf(&self, name: &str) -> PyResult<bool> {
        let idx = self.inner.get_index(name)
            .ok_or_else(|| pyo3::exceptions::PyValueError::new_err(
                format!("Node '{}' not found", name)))?;
        Ok(self.inner.is_leaf(idx))
    }

    fn get_performance_path(&self, name: &str) -> PyResult<Option<String>> {
        let idx = self.inner.get_index(name)
            .ok_or_else(|| pyo3::exceptions::PyValueError::new_err(
                format!("Node '{}' not found", name)))?;
        Ok(self.inner.graph[idx].performance.clone())
    }

    fn get_out_neighbors(&self, name: &str) -> PyResult<Vec<String>> {
        let idx = self.inner.get_index(name)
            .ok_or_else(|| pyo3::exceptions::PyValueError::new_err(
                format!("Node '{}' not found", name)))?;
        Ok(self.inner.out_neighbor_names(idx))
    }

    // ---- Metric initialisation (called from metric.py) ---------------------

    /// Set all node metrics to Single{0.0, unit} for each metric in metric_units.
    fn init_metrics(&mut self, metric_units: HashMap<String, String>) -> PyResult<()> {
        for idx in self.inner.graph.node_indices() {
            for (metric, unit) in &metric_units {
                self.inner.graph[idx].metrics.insert(
                    metric.clone(),
                    MetricValue::Single(SingleMetric { value: 0.0, unit: unit.clone() }),
                );
            }
        }
        Ok(())
    }

    /// Populate a leaf node with hardware interface results, instance count, and tags.
    /// `metrics` is a Python dict:
    ///   single-op:  { metric_name: {"value": float, "unit": str}, ... }
    ///   multi-op:   { metric_name: { op_name: {"value": float, "unit": str}, ... }, ... }
    fn set_module_data(
        &mut self,
        node_name: &str,
        metrics: &PyDict,
        instance: f64,
        tags: Vec<String>,
    ) -> PyResult<()> {
        let idx = self.inner.get_index(node_name)
            .ok_or_else(|| pyo3::exceptions::PyValueError::new_err(
                format!("Node '{}' not found", node_name)))?;

        for (key, val) in metrics.iter() {
            let metric_name: String = key.extract()?;
            // Try to interpret as single-op first: {"value": float, "unit": str}
            if let Ok(d) = val.downcast::<PyDict>() {
                if d.contains("value")? && d.contains("unit")? {
                    // Single-op metric
                    let value: f64 = d.get_item("value")
                        .unwrap().unwrap().extract()?;
                    let unit: String = d.get_item("unit")
                        .unwrap().unwrap().extract()?;
                    self.inner.graph[idx].metrics.insert(
                        metric_name,
                        MetricValue::Single(SingleMetric { value, unit }),
                    );
                } else {
                    // Multi-op metric: keys are operation names
                    let mut ops: IndexMap<String, SingleMetric> = IndexMap::new();
                    for (op_key, op_val) in d.iter() {
                        let op_name: String = op_key.extract()?;
                        let op_dict: &PyDict = op_val.downcast()?;
                        let value: f64 = op_dict.get_item("value")
                            .unwrap().unwrap().extract()?;
                        let unit: String = op_dict.get_item("unit")
                            .unwrap().unwrap().extract()?;
                        ops.insert(op_name, SingleMetric { value, unit });
                    }
                    self.inner.graph[idx].metrics.insert(
                        metric_name,
                        MetricValue::MultiOp(ops),
                    );
                }
            }
        }

        self.inner.graph[idx].instance = instance;
        self.inner.graph[idx].tags = tags;
        Ok(())
    }

    // ---- Edge property setters (called from performance.py) ----------------

    fn set_edge_count(&mut self, source: &str, target: &str, count: f64) -> PyResult<()> {
        let eidx = self.inner.find_edge(source, target)
            .ok_or_else(|| pyo3::exceptions::PyValueError::new_err(
                format!("Edge '{}' -> '{}' not found", source, target)))?;
        self.inner.graph[eidx].count = count;
        Ok(())
    }

    fn set_edge_aggregation(&mut self, source: &str, target: &str, agg: &str) -> PyResult<()> {
        let eidx = self.inner.find_edge(source, target)
            .ok_or_else(|| pyo3::exceptions::PyValueError::new_err(
                format!("Edge '{}' -> '{}' not found", source, target)))?;
        self.inner.graph[eidx].aggregation = agg.to_string();
        Ok(())
    }

    fn set_edge_operation(
        &mut self,
        source: &str,
        target: &str,
        operation: HashMap<String, String>,
    ) -> PyResult<()> {
        let eidx = self.inner.find_edge(source, target)
            .ok_or_else(|| pyo3::exceptions::PyValueError::new_err(
                format!("Edge '{}' -> '{}' not found", source, target)))?;
        self.inner.graph[eidx].operation = operation.into_iter().collect();
        Ok(())
    }

    fn set_edge_factor(
        &mut self,
        source: &str,
        target: &str,
        factor: HashMap<String, f64>,
    ) -> PyResult<()> {
        let eidx = self.inner.find_edge(source, target)
            .ok_or_else(|| pyo3::exceptions::PyValueError::new_err(
                format!("Edge '{}' -> '{}' not found", source, target)))?;
        self.inner.graph[eidx].factor = factor.into_iter().collect();
        Ok(())
    }

    fn get_edge_count(&self, source: &str, target: &str) -> PyResult<f64> {
        let eidx = self.inner.find_edge(source, target)
            .ok_or_else(|| pyo3::exceptions::PyValueError::new_err(
                format!("Edge '{}' -> '{}' not found", source, target)))?;
        Ok(self.inner.graph[eidx].count)
    }

    fn get_edge_aggregation(&self, source: &str, target: &str) -> PyResult<String> {
        let eidx = self.inner.find_edge(source, target)
            .ok_or_else(|| pyo3::exceptions::PyValueError::new_err(
                format!("Edge '{}' -> '{}' not found", source, target)))?;
        Ok(self.inner.graph[eidx].aggregation.clone())
    }

    /// Set a per-node specified-mode metric value (from performance model output).
    fn set_node_specified_metric(
        &mut self,
        node_name: &str,
        metric_name: &str,
        value: f64,
        unit: &str,
    ) -> PyResult<()> {
        let idx = self.inner.get_index(node_name)
            .ok_or_else(|| pyo3::exceptions::PyValueError::new_err(
                format!("Node '{}' not found", node_name)))?;
        self.inner.graph[idx].specified_metrics.insert(
            metric_name.to_string(),
            SingleMetric { value, unit: unit.to_string() },
        );
        Ok(())
    }

    fn get_node_specified_metric(&self, node_name: &str, metric_name: &str) -> PyResult<Option<f64>> {
        let idx = self.inner.get_index(node_name)
            .ok_or_else(|| pyo3::exceptions::PyValueError::new_err(
                format!("Node '{}' not found", node_name)))?;
        Ok(self.inner.graph[idx].specified_metrics.get(metric_name).map(|s| s.value))
    }

    // ---- query_module_metric -----------------------------------------------

    /// Returns {"value": float, "unit": str}.
    #[pyo3(signature = (metric, module=None, operation=None))]
    fn query_module_metric(
        &self,
        py: Python<'_>,
        metric: &str,
        module: Option<&str>,
        operation: Option<&str>,
    ) -> PyResult<PyObject> {
        let module = module.ok_or_else(|| pyo3::exceptions::PyValueError::new_err(
            "module argument is required"))?;

        let idx = self.inner.get_index(module)
            .ok_or_else(|| {
                let msg = format!("Invalid module <{}>.", module);
                error!("{}", msg);
                pyo3::exceptions::PyValueError::new_err(msg)
            })?;

        if !self.inner.is_leaf(idx) {
            let msg = format!("Invalid event <{}>; this function requires a module.", module);
            error!("{}", msg);
            return Err(pyo3::exceptions::PyValueError::new_err(msg));
        }

        let node = &self.inner.graph[idx];
        let mv = node.metrics.get(metric)
            .ok_or_else(|| pyo3::exceptions::PyValueError::new_err(
                format!("Metric '{}' not found on module '{}'", metric, module)))?;

        let result = PyDict::new(py);
        match mv {
            MetricValue::Single(s) => {
                if operation.is_some() {
                    warn!("Ignore operation <{}> for metric <{}> in module <{}>; this module requires no specified operation.",
                          operation.unwrap(), metric, module);
                }
                result.set_item("value", s.value)?;
                result.set_item("unit", &s.unit)?;
            }
            MetricValue::MultiOp(ops) => {
                // Mirror Python exactly: a missing operation renders as <None>, and
                // legal values use Python list syntax with single quotes.
                let s = match operation.and_then(|op| ops.get(op)) {
                    Some(s) => s,
                    None => {
                        let legal = ops.keys().map(|k| format!("'{}'", k))
                            .collect::<Vec<_>>().join(", ");
                        let msg = format!(
                            "Invalid operation <{}> for metric <{}> in module <{}>; legal values: [{}].",
                            operation.unwrap_or("None"), metric, module, legal);
                        error!("{}", msg);
                        return Err(pyo3::exceptions::PyValueError::new_err(msg));
                    }
                };
                result.set_item("value", s.value)?;
                result.set_item("unit", &s.unit)?;
            }
        }
        Ok(result.into())
    }

    // ---- aggregate_event_metric --------------------------------------------

    #[pyo3(signature = (metric, metric_aggregation, metric_unit, workload=None, event=None))]
    fn aggregate_event_metric(
        &mut self,
        py: Python<'_>,
        metric: &str,
        metric_aggregation: &str,
        metric_unit: &str,
        workload: Option<&str>,
        event: Option<&str>,
    ) -> PyResult<PyObject> {
        let event = event.ok_or_else(|| pyo3::exceptions::PyValueError::new_err(
            "event argument is required"))?;

        let event_idx = self.inner.get_index(event)
            .ok_or_else(|| {
                let msg = format!("Invalid event <{}>.", event);
                error!("{}", msg);
                pyo3::exceptions::PyValueError::new_err(msg)
            })?;

        let workload_idx = match workload {
            Some(w) if w != event => Some(
                self.inner.get_index(w)
                    .ok_or_else(|| {
                        let msg = format!("Invalid workload <{}>.", w);
                        error!("{}", msg);
                        pyo3::exceptions::PyValueError::new_err(msg)
                    })?
            ),
            _ => None,
        };

        // Mirrors Python's path-existence assertion: the event must be reachable from
        // the workload (otherwise the query is ill-posed; do not silently return 0).
        if let Some(w_idx) = workload_idx {
            if crate::paths::all_paths(&self.inner.graph, w_idx, event_idx).is_empty() {
                let msg = format!("Invalid event <{}> in workload <{}>.", event, workload.unwrap());
                error!("{}", msg);
                return Err(pyo3::exceptions::PyValueError::new_err(msg));
            }
        }

        // Reset all non-leaf metric values to 0.0
        let non_leaf_ids: Vec<_> = self.inner.graph.node_indices()
            .filter(|&idx| !self.inner.is_leaf(idx))
            .collect();
        for idx in non_leaf_ids {
            if let Some(m) = self.inner.graph[idx].metrics.get_mut(metric) {
                if m.is_single() {
                    let s = m.as_single_mut();
                    let was_nonzero = s.value != 0.0;
                    s.value = 0.0;
                    // match Python: only trace the reset when the value was nonzero
                    if was_nonzero {
                        debug!("  Reset metric <{}> in event <{}> to 0.", metric, self.inner.graph[idx].name);
                    }
                }
            }
        }

        // Final per-mode "Total value" traces mirror the Python wording exactly,
        // including the "= single value X * count Y" suffix where main emits it.
        let result_value = match metric_aggregation {
            "module" => {
                if workload.is_some() {
                    warn!("Ignore workload <{}> in aggregation <module>.", workload.unwrap());
                }
                let mut evaluated = std::collections::HashSet::new();
                let v = aggregate_module(&self.inner.graph, event_idx, event, metric, &mut evaluated)
                    .map_err(pyo3::exceptions::PyValueError::new_err)?;
                match workload {
                    Some(w) => debug!("  Total value (<{}> -> <{}>) = <{}> <{}>.", w, event, fmt_py(v), metric_unit),
                    None => debug!("  Total value (<{}>) = <{}> <{}>.", event, fmt_py(v), metric_unit),
                }
                v
            }
            "summation" => {
                let is_leaf = self.inner.is_leaf(event_idx);
                let is_multi_op = self.inner.graph[event_idx].metrics
                    .get(metric)
                    .map(|m| m.is_multi_op())
                    .unwrap_or(false);

                match workload_idx {
                    Some(w_idx) => {
                        let w = workload.unwrap();
                        if is_leaf && is_multi_op {
                            let v = aggregate_summation_multiop(
                                &self.inner.graph, w_idx, event_idx, metric)
                                .map_err(pyo3::exceptions::PyValueError::new_err)?;
                            debug!("  Total value (<{}> -> <{}>) = <{}> <{}>.", w, event, fmt_py(v), metric_unit);
                            v
                        } else {
                            let total_count = compute_path_count(
                                &self.inner.graph, w_idx, event_idx, metric);
                            aggregate_summation(&mut self.inner.graph, event_idx, metric)
                                .map_err(pyo3::exceptions::PyValueError::new_err)?;
                            let pre = self.inner.graph[event_idx].metrics[metric].as_single().value;
                            let v = pre * total_count;
                            debug!("  Total value (<{}> -> <{}>) = <{}> <{}> = single value <{}> * count <{}>.",
                                   w, event, fmt_py(v), metric_unit, fmt_py(pre), fmt_py(total_count));
                            v
                        }
                    }
                    None => {
                        // Mirrors Python L280: with no workload, a leaf event must be a
                        // single-operation module (no operation is specified to disambiguate).
                        if is_leaf && is_multi_op {
                            let msg = format!(
                                "Invalid module <{}> for aggregation <summation>; this aggregation does not support multi-operation module.",
                                event);
                            error!("{}", msg);
                            return Err(pyo3::exceptions::PyValueError::new_err(msg));
                        }
                        aggregate_summation(&mut self.inner.graph, event_idx, metric)
                            .map_err(pyo3::exceptions::PyValueError::new_err)?;
                        let v = self.inner.graph[event_idx].metrics[metric].as_single().value;
                        match workload {
                            Some(w) => debug!("  Total value (<{}> -> <{}>) = <{}> <{}>.", w, event, fmt_py(v), metric_unit),
                            None => debug!("  Total value (<{}>) = <{}> <{}>.", event, fmt_py(v), metric_unit),
                        }
                        v
                    }
                }
            }
            "specified" => {
                if self.inner.is_leaf(event_idx) {
                    let msg = format!(
                        "Invalid module <{}> for aggregation <specified>; this aggregation requires an event.",
                        event);
                    error!("{}", msg);
                    return Err(pyo3::exceptions::PyValueError::new_err(msg));
                }
                let total_count = match workload_idx {
                    Some(w_idx) => compute_path_count(
                        &self.inner.graph, w_idx, event_idx, metric),
                    None => 1.0,
                };
                aggregate_specified(&mut self.inner.graph, event_idx, metric)
                    .map_err(pyo3::exceptions::PyValueError::new_err)?;
                let pre = self.inner.graph[event_idx].metrics[metric].as_single().value;
                let v = pre * total_count;
                match workload {
                    None => debug!("  Total value (<{}>) = <{}> <{}> = single value <{}>.",
                                   event, fmt_py(v), metric_unit, fmt_py(pre)),
                    Some(w) => debug!("  Total value (<{}> -> <{}>) = <{}> <{}> = single value <{}> * count <{}>.",
                                      w, event, fmt_py(v), metric_unit, fmt_py(pre), fmt_py(total_count)),
                }
                v
            }
            other => {
                return Err(pyo3::exceptions::PyValueError::new_err(
                    format!("Invalid aggregation '{}'; legal: module, summation, specified", other)));
            }
        };

        let result = PyDict::new(py);
        result.set_item("value", result_value)?;
        result.set_item("unit", metric_unit)?;
        Ok(result.into())
    }

    // Tag aggregation is driven from the Python wrapper (it loops over
    // get_tag_modules() calling aggregate_event_metric per module) so the
    // per-module SUCCESS trace is emitted by Python, matching the main engine.

    // ---- aggregate_event_count -----------------------------------------------

    #[pyo3(signature = (workload=None, event=None))]
    fn aggregate_event_count(
        &self,
        workload: Option<&str>,
        event: Option<&str>,
    ) -> PyResult<f64> {
        let event = event.ok_or_else(|| pyo3::exceptions::PyValueError::new_err(
            "event argument is required"))?;

        // If no workload or workload == event, count is 1.0
        match workload {
            None => {
                debug!("  Total value (<{}>) = <{}>.", event, fmt_py(1.0));
                Ok(1.0)
            }
            Some(w) if w == event => {
                debug!("  Total value (<{}>) = <{}>.", event, fmt_py(1.0));
                Ok(1.0)
            }
            Some(w) => {
                let w_idx = self.inner.get_index(w)
                    .ok_or_else(|| {
                        let msg = format!("Invalid workload <{}>.", w);
                        error!("{}", msg);
                        pyo3::exceptions::PyValueError::new_err(msg)
                    })?;
                let e_idx = self.inner.get_index(event)
                    .ok_or_else(|| {
                        let msg = format!("Invalid event <{}>.", event);
                        error!("{}", msg);
                        pyo3::exceptions::PyValueError::new_err(msg)
                    })?;
                // Mirrors Python's path-existence assertion: event must be reachable.
                if crate::paths::all_paths(&self.inner.graph, w_idx, e_idx).is_empty() {
                    let msg = format!("Invalid event <{}> in workload <{}>.", event, w);
                    error!("{}", msg);
                    return Err(pyo3::exceptions::PyValueError::new_err(msg));
                }
                let total = aggregate_event_count(&self.inner.graph, w_idx, e_idx);
                debug!("  Total value (<{}> -> <{}>) = <{}>.", w, event, fmt_py(total));
                Ok(total)
            }
        }
    }

    // ---- Serialisation -----------------------------------------------------

    fn save_json(&self, path: &str) -> PyResult<()> {
        use std::fs::File;
        use std::io::BufWriter;

        // Serialise as a simple JSON structure
        let nodes: Vec<serde_json::Value> = self.inner.graph.node_indices().map(|idx| {
            let n = &self.inner.graph[idx];
            serde_json::json!({
                "name": n.name,
                "performance": n.performance,
                "instance": n.instance,
                "tags": n.tags,
                "metrics": serialize_metrics(&n.metrics),
                "specified_metrics": serialize_specified(&n.specified_metrics),
            })
        }).collect();

        let edges: Vec<serde_json::Value> = self.inner.graph.edge_indices().map(|eidx| {
            let (src, tgt) = self.inner.graph.edge_endpoints(eidx).unwrap();
            let e = &self.inner.graph[eidx];
            serde_json::json!({
                "source": self.inner.graph[src].name,
                "target": self.inner.graph[tgt].name,
                "count": e.count,
                "aggregation": e.aggregation,
                "operation": e.operation,
                "factor": e.factor,
            })
        }).collect();

        let doc = serde_json::json!({ "nodes": nodes, "edges": edges });
        let file = File::create(path)
            .map_err(|e| pyo3::exceptions::PyIOError::new_err(e.to_string()))?;
        serde_json::to_writer_pretty(BufWriter::new(file), &doc)
            .map_err(|e| pyo3::exceptions::PyIOError::new_err(e.to_string()))?;
        Ok(())
    }

    #[staticmethod]
    fn load_json(path: &str) -> PyResult<Self> {
        use std::fs::File;
        use std::io::BufReader;

        let file = File::open(path)
            .map_err(|e| pyo3::exceptions::PyIOError::new_err(e.to_string()))?;
        let doc: serde_json::Value = serde_json::from_reader(BufReader::new(file))
            .map_err(|e| pyo3::exceptions::PyValueError::new_err(e.to_string()))?;

        let mut inner = ArchxGraphInner::new();

        for node in doc["nodes"].as_array().unwrap_or(&vec![]) {
            let name = node["name"].as_str().unwrap();
            let perf = node["performance"].as_str();
            let idx = inner.add_node(name, perf);
            inner.graph[idx].instance = node["instance"].as_f64().unwrap_or(1.0);
            inner.graph[idx].tags = node["tags"].as_array().unwrap_or(&vec![])
                .iter().filter_map(|v| v.as_str().map(|s| s.to_string())).collect();
            inner.graph[idx].metrics = deserialize_metrics(&node["metrics"]);
            inner.graph[idx].specified_metrics = deserialize_specified(&node["specified_metrics"]);
        }

        for edge in doc["edges"].as_array().unwrap_or(&vec![]) {
            let src = edge["source"].as_str().unwrap();
            let tgt = edge["target"].as_str().unwrap();
            let (eidx, _) = inner.add_edge(src, tgt)
                .map_err(|e| pyo3::exceptions::PyValueError::new_err(e))?;
            inner.graph[eidx].count = edge["count"].as_f64().unwrap_or(1.0);
            inner.graph[eidx].aggregation = edge["aggregation"]
                .as_str().unwrap_or("parallel").to_string();
            inner.graph[eidx].operation = edge["operation"].as_object()
                .map(|m| m.iter().map(|(k, v)| (k.clone(), v.as_str().unwrap_or("").to_string())).collect())
                .unwrap_or_default();
            inner.graph[eidx].factor = edge["factor"].as_object()
                .map(|m| m.iter().map(|(k, v)| (k.clone(), v.as_f64().unwrap_or(1.0))).collect())
                .unwrap_or_default();
        }

        Ok(ArchxGraph { inner })
    }
}

// ---------------------------------------------------------------------------
// JSON serialisation helpers
// ---------------------------------------------------------------------------

fn serialize_metrics(metrics: &metric::NodeMetrics) -> serde_json::Value {
    let mut map = serde_json::Map::new();
    for (name, mv) in metrics {
        let val = match mv {
            MetricValue::Single(s) => serde_json::json!({"value": s.value, "unit": s.unit}),
            MetricValue::MultiOp(ops) => {
                let mut omap = serde_json::Map::new();
                for (op, s) in ops {
                    omap.insert(op.clone(), serde_json::json!({"value": s.value, "unit": s.unit}));
                }
                serde_json::Value::Object(omap)
            }
        };
        map.insert(name.clone(), val);
    }
    serde_json::Value::Object(map)
}

fn serialize_specified(specs: &IndexMap<String, SingleMetric>) -> serde_json::Value {
    let mut map = serde_json::Map::new();
    for (name, s) in specs {
        map.insert(name.clone(), serde_json::json!({"value": s.value, "unit": s.unit}));
    }
    serde_json::Value::Object(map)
}

fn deserialize_metrics(v: &serde_json::Value) -> metric::NodeMetrics {
    let mut m = IndexMap::new();
    if let Some(obj) = v.as_object() {
        for (name, val) in obj {
            if val.get("value").is_some() && val.get("unit").is_some() {
                m.insert(name.clone(), MetricValue::Single(SingleMetric {
                    value: val["value"].as_f64().unwrap_or(0.0),
                    unit: val["unit"].as_str().unwrap_or("").to_string(),
                }));
            } else if let Some(ops_obj) = val.as_object() {
                let mut ops = IndexMap::new();
                for (op, sv) in ops_obj {
                    ops.insert(op.clone(), SingleMetric {
                        value: sv["value"].as_f64().unwrap_or(0.0),
                        unit: sv["unit"].as_str().unwrap_or("").to_string(),
                    });
                }
                m.insert(name.clone(), MetricValue::MultiOp(ops));
            }
        }
    }
    m
}

fn deserialize_specified(v: &serde_json::Value) -> IndexMap<String, SingleMetric> {
    let mut m = IndexMap::new();
    if let Some(obj) = v.as_object() {
        for (name, val) in obj {
            m.insert(name.clone(), SingleMetric {
                value: val["value"].as_f64().unwrap_or(0.0),
                unit: val["unit"].as_str().unwrap_or("").to_string(),
            });
        }
    }
    m
}

// ---------------------------------------------------------------------------
// Module registration
// ---------------------------------------------------------------------------

#[pymodule]
fn _core(m: &Bound<'_, PyModule>) -> PyResult<()> {
    // Bridge Rust `log` records into Python's logging (and thence loguru, via the
    // intercept handler installed in archx/__init__.py). Level filtering is left to
    // Python: pyo3-log caches the effective Python logging level, so disabled levels
    // (e.g. debug! when running at INFO) cost nothing on the Rust hot path.
    let _ = pyo3_log::try_init();
    m.add_class::<ArchxGraph>()?;
    Ok(())
}
