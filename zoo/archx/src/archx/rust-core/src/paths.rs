use std::collections::HashSet;
use petgraph::graph::{DiGraph, NodeIndex, EdgeIndex};
use petgraph::visit::EdgeRef;
use petgraph::Direction;
use petgraph::algo::toposort;

use crate::graph::{NodeData, EdgeData};

/// All simple paths from src to dst, each returned as the sequence of EdgeIndex
/// traversed. Replaces graph_tool's gt.all_paths().
///
/// Backtracking DFS over a single shared buffer + visited set (a path Vec is
/// allocated only when a complete path is found, not cloned at every branch).
/// Returning edge indices lets callers index edge weights directly and avoids
/// re-resolving each (src,tgt) with the O(out-degree) `find_edge`, which would be
/// O(N^2) across all paths through a high-fanout node.
pub fn all_paths(
    graph: &DiGraph<NodeData, EdgeData>,
    src: NodeIndex,
    dst: NodeIndex,
) -> Vec<Vec<EdgeIndex>> {
    let mut results = Vec::new();
    let mut edge_path = Vec::new();
    let mut visited = HashSet::new();
    visited.insert(src);
    all_paths_dfs(graph, src, dst, &mut edge_path, &mut visited, &mut results);
    results
}

fn all_paths_dfs(
    graph: &DiGraph<NodeData, EdgeData>,
    current: NodeIndex,
    dst: NodeIndex,
    edge_path: &mut Vec<EdgeIndex>,
    visited: &mut HashSet<NodeIndex>,
    results: &mut Vec<Vec<EdgeIndex>>,
) {
    if current == dst {
        results.push(edge_path.clone());
        return;
    }
    for e in graph.edges_directed(current, Direction::Outgoing) {
        let neighbor = e.target();
        if visited.insert(neighbor) {
            edge_path.push(e.id());
            all_paths_dfs(graph, neighbor, dst, edge_path, visited, results);
            edge_path.pop();
            visited.remove(&neighbor);
        }
    }
}

/// Returns nodes reachable from `start` in bottom-up order (leaves first, start last).
/// Replaces topological_sort_reverse() from the Python code.
pub fn topological_sort_subgraph(
    graph: &DiGraph<NodeData, EdgeData>,
    start: NodeIndex,
) -> Vec<NodeIndex> {
    // Forward BFS to find all nodes reachable from start
    let reachable = reachable_from(graph, start);

    // Full topological sort of the graph
    let topo = match toposort(graph, None) {
        Ok(order) => order,
        Err(_) => panic!("Graph contains a cycle; expected a DAG"),
    };

    // Filter to reachable only, then reverse (bottom-up)
    let mut filtered: Vec<NodeIndex> = topo.into_iter()
        .filter(|n| reachable.contains(n))
        .collect();
    filtered.reverse();
    filtered
}

/// BFS forward from `start` — returns set of all reachable nodes (including start).
pub fn reachable_from(
    graph: &DiGraph<NodeData, EdgeData>,
    start: NodeIndex,
) -> HashSet<NodeIndex> {
    let mut visited = HashSet::new();
    let mut queue = vec![start];
    while let Some(node) = queue.pop() {
        if visited.insert(node) {
            for neighbor in graph.neighbors_directed(node, Direction::Outgoing) {
                queue.push(neighbor);
            }
        }
    }
    visited
}
