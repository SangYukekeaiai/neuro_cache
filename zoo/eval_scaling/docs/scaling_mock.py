"""eval-scaling layout mock v3: memory scaling, 2 rows x 5 architectures.
Rows: performance (top), DRAM traffic (bottom). X: memory capacity 1x/2x/4x,
node count held constant. Three series: single-node spad, multi-node spad,
multi-node cache. All values are synthetic placeholders."""
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

rng = np.random.default_rng(7)
x = np.array([1, 2, 4])                 # on-chip memory capacity / published
ARCHS = ['SpinalFlow', 'PTB', 'LoAS', 'Prosperity', 'GustavSNN']
C_SPAD, C_MULTI, C_CACHE = '#4477aa', '#ee6677', '#228833'
series = [
    ('single-node spad', C_SPAD, 'o', '-'),
    ('multi-node spad', C_MULTI, 's', '--'),
    ('multi-node cache (ours)', C_CACHE, '^', '-.'),
]

fig, axes = plt.subplots(2, 5, figsize=(13.0, 4.6), sharex=True, sharey='row')

for j, arch in enumerate(ARCHS):
    jit = lambda s: 1 + rng.normal(0, s, 3)
    # performance: speedup over single-node 1x (synthetic, saturating single)
    p_single = x.astype(float) ** 0.25 * jit(.02)            # saturates fast
    p_multi = 8.0 * x.astype(float) ** 0.45 * jit(.03)       # scales better
    p_cache = 11.0 * x.astype(float) ** 0.55 * jit(.03)      # best
    p_single[0] = 1.0
    # DRAM traffic normalized to single-node 1x
    t_single = x.astype(float) ** -0.25 * jit(.02)           # flattens
    t_multi = 0.8 * x.astype(float) ** -0.6 * jit(.03)
    t_cache = 0.35 * x.astype(float) ** -0.7 * jit(.03)      # lowest
    t_single[0] = 1.0

    for (lbl, c, m, ls), p, t in zip(series, (p_single, p_multi, p_cache),
                                     (t_single, t_multi, t_cache)):
        axes[0, j].plot(x, p, marker=m, ls=ls, color=c, ms=4,
                        label=lbl if j == 0 else None)
        axes[1, j].plot(x, t, marker=m, ls=ls, color=c, ms=4)
    axes[0, j].set_title(arch, fontsize=9)

for ax in axes.flat:
    ax.set_xscale('log')
    ax.set_xticks(x), ax.set_xticklabels([f'{v}x' for v in x])
    ax.minorticks_off()
    ax.grid(alpha=.25, lw=.5)
    ax.tick_params(labelsize=8)
axes[0, 0].set_ylabel('Speedup / single 1x', fontsize=9)
axes[1, 0].set_ylabel('DRAM traffic / single 1x', fontsize=9)
for ax in axes[1]:
    ax.set_xlabel('Memory capacity', fontsize=8)
axes[0, 0].legend(fontsize=7, loc='upper left', framealpha=.9)
fig.suptitle('MOCK - fake numbers. Memory scaling at fixed node count', fontsize=10)
fig.tight_layout(rect=(0, 0, 1, 0.96))
for ext in ('pdf', 'png'):
    fig.savefig(Path(__file__).with_suffix('.' + ext), dpi=200)
print('Rendered 2x5 memory-scaling layout mock; zero experiment results.')
