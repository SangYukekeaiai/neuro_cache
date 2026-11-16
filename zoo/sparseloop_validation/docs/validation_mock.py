"""LoAS-only cycles-panel layout. All plotted values are synthetic placeholders."""
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

rng=np.random.default_rng(7)
p=np.array([.05,.1,.3,.5,.9])
x=np.linspace(.02,1,100)
curve=lambda values: .08+.92*values**.8
fig,ax=plt.subplots(figsize=(5.2,3.4))
ax.plot(x,curve(x),color='0.25',lw=1.2,label='Sparseloop, hypergeometric (Tier B)')
y=curve(p)*(1+rng.normal(0,.02,len(p)))
ax.errorbar(p,y,yerr=.03*curve(p),fmt='s',color='#4477aa',capsize=2.5,
            label='nocsim, Bernoulli (3-seed range)')
density=np.linspace(.12,.75,12)
ax.scatter(density,curve(density)*(1+rng.normal(0,.08,12)),marker='^',color='#ee6677',
           label='nocsim, real traces (Tier C)')
ax.scatter(density,curve(density)*(1+rng.normal(0,.04,12)),marker='^',facecolors='none',edgecolors='#ee6677',
           label='Sparseloop, actual-data (Tier C)')
ax.text(.03,.97,'LoAS\nTier B MAE: pending\nTier C gap: pending',transform=ax.transAxes,va='top',fontsize=8)
ax.set(xlim=(0,1),ylim=(0,1.25),xlabel='Operand density',ylabel='Processing cycles / dense reference')
ax.legend(loc='lower right',fontsize=7,framealpha=.9)
fig.suptitle('Layout mock — no measured validation results',fontsize=10)
fig.tight_layout()
for ext in ('pdf','png'):
    fig.savefig(Path(__file__).with_suffix('.'+ext),dpi=200)
print('Rendered LoAS-only illustrative layout; zero experiment results.')
