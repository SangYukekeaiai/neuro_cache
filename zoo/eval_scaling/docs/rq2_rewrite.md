# RQ2 rewrite (LaTeX, drop-in for src/08_evaluation.tex 5.2)

For boss review before landing in the paper; the current 5.2 will be
commented out, not deleted. Layout mock for the second figure:
`scaling_mock.py` (+png/pdf) in this folder.

```latex
\subsection{RQ2: Multi-Node Scheduling}
\label{sec:eval-multi-node}

\textbf{Heuristic versus searched schedules.}
We first measure what the schedule search buys over a strong heuristic.
The baseline fixes the inter-tile loop order to a STEMS-style
time-batched order~\cite{eissa2025stems} (single-core in the original)
and runs it through our multi-node scheduler, so both schedules execute
on the same hardware; the searched schedule is the best one the MIP
scheduler finds.
Figure~\ref{fig:eval-heuristic-gap} reports the off-chip memory traffic
of both schedules for each node architecture.
% TODO: results: traffic gap per architecture; state the MIP optimality gap

\begin{figure}[t]
    \centering
    \figplaceholder{eval_heuristic_gap}{\linewidth}{Off-chip traffic: heuristic vs.\ searched schedule}
    \caption{Off-chip memory traffic of the STEMS-style time-batched
    heuristic schedule and of the searched best schedule on the same
    multi-node hardware, per node architecture.}
    \Description{Placeholder box comparing heuristic and searched schedule memory traffic per architecture; no data shown yet.}
    \label{fig:eval-heuristic-gap}
\end{figure}

\textbf{Memory scaling.}
Each node in our system runs a fixed dataflow schedule, and
Figure~\ref{fig:spinalflow-saturation} already shows that scaling the
node itself saturates: performance stops improving once the node-level
array grows past its published size.
The remaining scaling axis is therefore memory, which we study here.
We sweep the on-chip memory capacity over $1\times$, $2\times$, and
$4\times$ the published configuration for three designs: a single node
with a grown scratchpad, the multi-node design with every node's
scratchpad grown by the same factor (the node count stays fixed across
the sweep), and the multi-node design with the neuromorphic cache in
place of the scratchpad.
Figure~\ref{fig:eval-scaling} reports performance (top row) and DRAM
traffic (bottom row), one column per node architecture.
The sweep shows where additional scratchpad capacity stops paying off
because the fixed dataflow leaves it underused, and how the cache
spends the same capacity.
% TODO: results

\begin{figure*}[t]
    \centering
    \figplaceholder{eval_scaling}{\textwidth}{Performance and DRAM traffic vs.\ memory capacity: single node, multi-node, multi-node cache}
    \caption{Performance (top) and DRAM traffic (bottom) at $1\times$,
    $2\times$, and $4\times$ the published on-chip memory capacity, for a
    single node, the multi-node design at fixed node count, and the
    multi-node design with the neuromorphic cache; one column per node
    architecture.}
    \Description{Placeholder box for a two-row, five-column line chart of performance and DRAM traffic versus memory capacity; no data shown yet.}
    \label{fig:eval-scaling}
\end{figure*}
```

## Notes (not for the paper)

- "Fig 2" node-scalability reference resolved to
  `\ref{fig:spinalflow-saturation}` (the node-level $N$ sweep in
  Motivation). Change if a different figure was meant.
- The scaling figure is `figure*` (full width): five columns do not fit
  in one column.
- Old 5.2 content to comment out when landing: the STEMS `\todo`, the
  $K$/$T$-splits paragraph and `tab:eval-kt-split`, the 1--16$\times$
  capacity-sweep paragraph, and the old `fig:eval-scaling` environment
  (the label is reused by the new figure, so comment the old one out).
- Heuristic-gap figure assumed single-column; no mock made for it yet,
  say the word if one is wanted.
```
