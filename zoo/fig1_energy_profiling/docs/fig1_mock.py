import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

archs = ['PTB', 'LoAS', 'GustavSNN']
bars  = ['64KB', '256KB', '1MB', 'Ideal']   # 3 baseline SRAM sizes + ideal (at 256KB)
# dummy normalized energy, baseline@256KB = 1.0 per arch
# segments: compute, on-chip SRAM, off-chip weight, off-chip other
data = {
 'PTB':       [[0.18,0.14,0.82,0.08],[0.18,0.16,0.58,0.08],[0.18,0.20,0.46,0.08],[0.18,0.16,0.09,0.08]],
 'LoAS':      [[0.22,0.12,0.74,0.07],[0.22,0.14,0.52,0.07],[0.22,0.18,0.42,0.07],[0.22,0.14,0.07,0.07]],
 'GustavSNN': [[0.15,0.17,0.90,0.09],[0.15,0.19,0.66,0.09],[0.15,0.24,0.52,0.09],[0.15,0.19,0.11,0.09]],
}
segs   = ['Compute', 'On-chip SRAM', 'Off-chip (weights)', 'Off-chip (other)']
colors = ['#4477AA', '#CCBB44', '#EE6677', '#BBBBBB']

fig, ax = plt.subplots(figsize=(7.0, 3.1), dpi=160)
W, gap_in, gap_between = 0.19, 0.03, 0.35
xticks, xlabels = [], []
for gi, a in enumerate(archs):
    x0 = gi * (4*W + 3*gap_in + gap_between)
    for bi, b in enumerate(bars):
        x = x0 + bi*(W+gap_in)
        bottom = 0.0
        vals = data[a][bi]
        for si, v in enumerate(vals):
            hatch = '//' if b == 'Ideal' and si == 2 else None
            ax.bar(x, v, W, bottom=bottom, color=colors[si],
                   edgecolor='white', linewidth=0.6, hatch=hatch)
            bottom += v
        if b == 'Ideal':
            ax.text(x, bottom + 0.03, 'ideal', ha='center', fontsize=7.5, style='italic')
        xticks.append(x); xlabels.append(b)
    ax.text(x0 + 1.5*(W+gap_in), -0.33, a, ha='center', fontsize=10, fontweight='bold')

ax.set_xticks(xticks); ax.set_xticklabels(xlabels, fontsize=7.5)
ax.set_ylabel('Normalized energy', fontsize=9)
ax.set_ylim(0, 1.45)
ax.spines[['top','right']].set_visible(False)
ax.grid(axis='y', alpha=0.25, linewidth=0.5)
ax.set_axisbelow(True)
handles = [plt.Rectangle((0,0),1,1,color=c) for c in colors]
ax.legend(handles, segs, fontsize=7.5, ncol=4, frameon=False,
          loc='upper center', bbox_to_anchor=(0.5, 1.14))
# annotation arrow: gap
ax.annotate('', xy=(2*(4*W+3*gap_in+gap_between)+3*(W+gap_in), 0.55),
            xytext=(2*(4*W+3*gap_in+gap_between)+3*(W+gap_in)+0.18, 1.15),
            arrowprops=dict(arrowstyle='->', lw=1.0, color='#333333'))
ax.text(2*(4*W+3*gap_in+gap_between)+2.4*(W+gap_in)+0.42, 1.2,
        'load only\nneeded weights', fontsize=7.5, ha='center', color='#333333')
plt.tight_layout()
plt.savefig('fig1_mockup.png', bbox_inches='tight')
plt.savefig('fig1_mockup.pdf', bbox_inches='tight')
print('saved')
