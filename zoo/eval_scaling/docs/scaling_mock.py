"""eval-scaling layout mock v2: ONE architecture (LoAS), three capacity-spending
strategies. All plotted values are synthetic placeholders; the single-node spad
utilization fall anchors loosely on fig1's measured 92.8% -> ~49%."""
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

rng = np.random.default_rng(3)
x = np.array([1, 2, 4, 8, 16])          # total on-chip capacity / published
C_SPAD, C_MULTI, C_CACHE = '#4477aa', '#ee6677', '#228833'
FLOOR = 0.12                            # compulsory-traffic placeholder

fig, (ax_u, ax_t) = plt.subplots(1, 2, figsize=(8.0, 3.1))

# --- series (synthetic) ---------------------------------------------------
u0 = 0.92
u_spad = u0 * x.astype(float) ** -0.33 * (1 + rng.normal(0, .01, 5))   # falls
u_multi = np.full(5, u0) * (1 + rng.normal(0, .015, 5))                # flat
u_cache = (u0 + (0.97 - u0) * (1 - x.astype(float) ** -0.8)) \
          * (1 + rng.normal(0, .008, 5))                               # rises
u_multi[0] = u_spad[0]                   # shared x1 baseline (N=1, spad)

t_spad = x.astype(float) ** -0.25 * (1 + rng.normal(0, .015, 5))       # flattens
t_multi = np.maximum(x.astype(float) ** -0.75, FLOOR) * (1 + rng.normal(0, .02, 5))
t_cache = np.maximum(x.astype(float) ** -0.85, FLOOR) * (1 + rng.normal(0, .02, 5))
for t in (t_spad, t_multi, t_cache):
    t[0] = 1.0

series = [
    ('single node, grown spad', C_SPAD, 'o', '-'),
    ('multi-node, equal total', C_MULTI, 's', '--'),
    ('multi-node, cache (ours)', C_CACHE, '^', '-.'),
]

# --- left panel: utilization ---------------------------------------------
for (lbl, c, m, ls), y in zip(series, (u_spad, u_multi, u_cache)):
    ax_u.errorbar(x, y, yerr=.02, fmt=m, ls=ls, color=c, capsize=2, label=lbl)
ax_u.set(ylim=(0, 1.05), ylabel='Compute utilization U',
         xlabel='Total on-chip capacity (x published)', xscale='log')
ax_u.annotate(f'{u_cache[-1]/u_spad[-1]:.1f}x', xy=(16, (u_spad[-1]+u_cache[-1])/2),
              xytext=(-30, 0), textcoords='offset points', fontsize=8)

# --- right panel: off-chip traffic ---------------------------------------
for (lbl, c, m, ls), y in zip(series, (t_spad, t_multi, t_cache)):
    ax_t.errorbar(x, y, yerr=.02, fmt=m, ls=ls, color=c, capsize=2)
ax_t.axhline(FLOOR, color='0.4', lw=.8, ls=':')
ax_t.text(1.05, FLOOR + .02, 'compulsory floor', fontsize=7, color='0.35')
ax_t.set(ylim=(0, 1.1), ylabel='Off-chip words / x1',
         xlabel='Total on-chip capacity (x published)', xscale='log')

for ax in (ax_u, ax_t):
    ax.set_xticks(x), ax.set_xticklabels([f'{v}x' for v in x])
    ax.minorticks_off()
    ax.grid(alpha=.25, lw=.5)
    ax.tick_params(labelsize=8)
ax_u.legend(fontsize=7, loc='lower left', framealpha=.9)
fig.suptitle('LoAS - layout mock, no measured results', fontsize=10)
fig.tight_layout()
for ext in ('pdf', 'png'):
    fig.savefig(Path(__file__).with_suffix('.' + ext), dpi=200)
print('Rendered one-arch three-strategy layout mock; zero experiment results.')
