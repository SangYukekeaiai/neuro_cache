use indexmap::IndexMap;
use petgraph::graph::{DiGraph, NodeIndex, EdgeIndex};
use petgraph::Direction;
use serde::{Deserialize, Serialize};

use crate::metric::{NodeMetrics, SingleMetric};

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct NodeData {
    pub name: String,
    pub performance: Option<String>,
    /// All metrics (initialized by init_metrics, populated by set_module_data).
    pub metrics: NodeMetrics,
    /// Instance count — only meaningful for leaf (module) nodes.
    pub instance: f64,
    /// Tags — only set for leaf (module) nodes.
    pub tags: Vec<String>,
    /// Extra per-metric values set by performance models in 'specified' mode.
    /// Maps metric_name → SingleMetric. Consulted when a node connects only to leaves.
    pub specified_metrics: IndexMap<String, SingleMetric>,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct EdgeData {
    pub count: f64,
    pub aggregation: String,
    pub operation: IndexMap<String, String>,
    pub factor: IndexMap<String, f64>,
}

impl Default for EdgeData {
    fn default() -> Self {
        EdgeData {
            count: 1.0,
            aggregation: "parallel".to_string(),
            operation: IndexMap::new(),
            factor: IndexMap::new(),
        }
    }
}

pub struct ArchxGraphInner {
    pub graph: DiGraph<NodeData, EdgeData>,
    pub name_to_index: IndexMap<String, NodeIndex>,
}

impl ArchxGraphInner {
    pub fn new() -> Self {
        ArchxGraphInner {
            graph: DiGraph::new(),
            name_to_index: IndexMap::new(),
        }
    }

    pub fn add_node(&mut self, name: &str, performance: Option<&str>) -> NodeIndex {
        let idx = self.graph.add_node(NodeData {
            name: name.to_string(),
            performance: performance.map(|s| s.to_string()),
            metrics: IndexMap::new(),
            instance: 1.0,
            tags: vec![],
            specified_metrics: IndexMap::new(),
        });
        self.name_to_index.insert(name.to_string(), idx);
        idx
    }

    pub fn has_node(&self, name: &str) -> bool {
        self.name_to_index.contains_key(name)
    }

    pub fn get_index(&self, name: &str) -> Option<NodeIndex> {
        self.name_to_index.get(name).copied()
    }

    /// Returns (edge_index, merged) where `merged` is true if an edge for this
    /// (source, target) pair already existed and was reused instead of duplicated.
    pub fn add_edge(&mut self, source: &str, target: &str) -> Result<(EdgeIndex, bool), String> {
        let src = self.name_to_index.get(source)
            .copied()
            .ok_or_else(|| format!("Node '{}' not found", source))?;
        let tgt = self.name_to_index.get(target)
            .copied()
            .ok_or_else(|| format!("Node '{}' not found", target))?;
        // One edge per (source, target): matches main's set-based edge construction.
        // A subevent listed twice under one event must not create a parallel edge.
        if let Some(existing) = self.graph.find_edge(src, tgt) {
            return Ok((existing, true));
        }
        Ok((self.graph.add_edge(src, tgt, EdgeData::default()), false))
    }

    pub fn find_edge(&self, source: &str, target: &str) -> Option<EdgeIndex> {
        let src = self.name_to_index.get(source).copied()?;
        let tgt = self.name_to_index.get(target).copied()?;
        self.graph.find_edge(src, tgt)
    }

    pub fn is_leaf(&self, idx: NodeIndex) -> bool {
        self.graph.neighbors_directed(idx, Direction::Outgoing).next().is_none()
    }

    pub fn leaf_indices(&self) -> Vec<NodeIndex> {
        self.graph.node_indices()
            .filter(|&idx| self.is_leaf(idx))
            .collect()
    }

    pub fn all_node_names(&self) -> Vec<String> {
        self.graph.node_indices()
            .map(|idx| self.graph[idx].name.clone())
            .collect()
    }

    pub fn leaf_names(&self) -> Vec<String> {
        self.leaf_indices().iter()
            .map(|&idx| self.graph[idx].name.clone())
            .collect()
    }

    pub fn out_neighbor_names(&self, idx: NodeIndex) -> Vec<String> {
        self.graph.neighbors_directed(idx, Direction::Outgoing)
            .map(|n| self.graph[n].name.clone())
            .collect()
    }
}
