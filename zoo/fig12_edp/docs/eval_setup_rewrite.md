# Evaluation methodology rewrite (LaTeX, drop-in for src/08_evaluation.tex §Methodology)

Grounded in the fig12_edp campaign (zoo/fig12_edp/docs/{workflow,
input_trace_and_layers, workload_layer_scope, noc_dram_energy}.md and
zoo/archx/zoo/snn_edp/CONFIGURATION.md). `\figplaceholder` marks unfinished
figures. TODO markers flag numbers to pin before submission.

```latex
\subsection{Methodology}
\label{sec:eval-method}

\textbf{Workloads.}
We evaluate eight pre-trained spiking networks spanning three families:
spiking CNNs (LoAS-trained VGG16 and ResNet-19 on CIFAR-100 at
$T{=}4$~\cite{loas}, VGG16 at $T{=}32$, and an event-driven VGG on
CIFAR10-DVS and DVS128-Gesture), and spiking transformers
(Spikformer~\cite{spikformer}, Spike-driven Transformer~\cite{sdt}, and
SpikingLM~\cite{spikinglm}).
We capture the per-layer input spike tensors of each network and replay
them in every experiment.
We evaluate the spiking convolutional and spiking-GEMM layers and
exclude fully connected layers from whole-model aggregates.

% Benchmark table commented out for space; add back if room allows.
% (Re-enable the Table~\ref{tab:eval-workloads} reference above with it.)
% \begin{table}[t]
%   \centering
%   \caption{Evaluated workloads. $T$ is the number of timesteps; every
%   benchmark provides 500 captured input samples.}
%   \label{tab:eval-workloads}
%   \small
%   \begin{tabular}{lllc}
%     \toprule
%     Network & Dataset & Type & $T$ \\
%     \midrule
%     VGG16 (LoAS)        & CIFAR-100       & CNN         & 4  \\
%     ResNet-19 (LoAS)    & CIFAR-100       & CNN         & 4  \\
%     VGG16               & CIFAR-10        & CNN         & 32 \\
%     VGG (SMA-AZO)       & CIFAR10-DVS     & CNN (event) & 10 \\
%     VGG (SMA-AZO)       & DVS128-Gesture  & CNN (event) & 16 \\
%     Spikformer-4-384    & CIFAR-100       & Transformer & 4  \\
%     SDT-2-512           & CIFAR-100       & Transformer & 4  \\
%     SpikingLM           & % TODO: dataset
%                           & Transformer & 4  \\
%     \bottomrule
%   \end{tabular}
% \end{table}

\textbf{Software setup.}
Our flow has four stages.
(1)~The SNN scheduler (Section~\ref{sec:snn-scheduler}) formulates each
layer's mapping as a mixed-integer program and solves it with Gurobi,
producing one schedule per layer and architecture.
(2)~The weight trace generator (Section~\ref{sec:trace-gen}) replays the
captured spike tensors against the schedule through its core models of
the six node architectures -- SpinalFlow, PTB, LoAS, Prosperity,
GustavSNN~\cite{spinalflow,ptb,loas,prosperity,gustavsnn},
% TODO: sixth architecture name + cite
and emits the per-node weight traces.
(3)~An event-driven NoC simulator (Section~\ref{sec:txn-sim})
replays the traces on the multi-node system and reports per-transaction
traffic and cycle counts; the cache simulator
(Section~\ref{sec:cache}) replays the same streams against the
neuromorphic cache hierarchy.
(4)~The archx simulator~\cite{agraph}
% TODO: A-graph citation key
compiles the counted activity of stages 2--3 into per-module access
counts, then binds a versioned technology-characterization table to
produce energy, leakage, and area; updating the characterization reruns
only this last stage.

\textbf{Hardware setup.}
The system is a $4\times4$ mesh of 16 nodes clocked at 500\,MHz.
Compute logic is synthesized in the ASAP7 7\,nm predictive PDK at the
500\,MHz target~\cite{asap7}.
% TODO: cite asap7; confirm synthesis tool + corner (e.g., Cadence Genus, TT 25C)
On-chip SRAM is characterized with CACTI at the 7\,nm node; mesh
links use ASAP7 wire energy per mm with the link length taken from the
floorplan pitch.
% TODO: router energy -- 7nm synthesized router pending; placeholder contract in energy model
Off-chip memory is DDR4 characterized with CACTI-7: per-burst activate,
read/write, and precharge energy, per-bit I/O energy, and standing
refresh power over the design's own simulated runtime.
The cache configuration under test uses a two-level hierarchy
(16\,KiB, 8-way L1; 512\,KiB, 16-way L2; 64-byte lines; 16/32 MSHRs)
unless a design-space axis varies it (Section~\ref{sec:eval-cache-dse}).

\textbf{Metrics.}
We report off-chip traffic in DRAM payload bytes, latency in cycles,
energy, power, area, and energy--delay product (EDP).
Whole-model results sum all kept layers of a network before forming
ratios ($\mathrm{EDP} = \sum E \cdot \sum t$); layer-level results report
individual layers.
```

## Figure placeholders for unfinished figures (drop where each RQ needs them)

```latex
% RQ2 (fig:eval-scaling) -- data pending: 24/130 multi-node cases
\begin{figure}[t]
  \centering
  \figplaceholder{eval_scaling}{\linewidth}{Utilization and DRAM traffic vs.\ on-chip capacity}
  \caption{Compute utilization (left) and off-chip traffic normalized to
  the $1\times$ single node (right) as total on-chip capacity grows
  $1{-}16\times$, for one grown single node versus 16 equal-capacity
  nodes. Traffic counts DRAM payload bytes (weight, psum, vmem); the
  dotted line is the weights-only compulsory floor.}
  \Description{Placeholder: two-panel capacity-scaling figure; data pending.}
  \label{fig:eval-scaling}
\end{figure}

% RQ3 roofline (replaces the \todo at 08_evaluation.tex:99)
\begin{figure}[t]
  \centering
  \figplaceholder{eval_roofline}{\linewidth}{Roofline: scratchpad vs.\ cache designs}
  \caption{Roofline at the RQ3 operating point (64\,SOP/cycle compute
  roof, 128\,B/cycle DRAM roof). Scratchpad designs sit on the bandwidth
  roof at low operational intensity; the neuromorphic cache fetches only
  spike-selected weights, raising intensity toward the compute roof.
  % TODO: Belady ceiling marker if RQ4 runs
  }
  \Description{Placeholder: log-log roofline with one marker per design; data pending.}
  \label{fig:eval-roofline}
\end{figure}
```

## Notes (not for the paper)

- Sample counts and the 113/151-layer scope numbers are deliberately NOT
  in the text (user, 2026-11-16: few samples; keep scope rule short).
  The benchmark table is commented out; re-add with its \ref if space
  allows.
- ASAP7 status per CONFIGURATION.md: SRAM/cache/DRAM rows are priced
  (CACTI); own-RTL compute rows are "pending synthesis" with null metrics.
  The hardware paragraph states the method (what the numbers will be when
  synthesis lands), not a claim that all rows are characterized today.
- Router energy is an explicit pending placeholder in the energy model
  (32 nm archx source rejected as implausible); keep the TODO until the
  7 nm characterization lands.
- Workload table cites: spikformer/sdt/spikinglm/asap7 keys must exist in
  refs.bib -- check before \input.
```
