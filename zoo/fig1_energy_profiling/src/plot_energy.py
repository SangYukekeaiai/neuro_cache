"""Render Figure 1 from validated whole-model energy statistics.

Off-chip segments only, renormalized so each architecture's 256 KiB
off-chip energy is 1; per-bar labels give the gap to that baseline.
"""
import csv
import hashlib
import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
from matplotlib import font_manager as fm
from matplotlib import pyplot as plt
from matplotlib.ticker import StrMethodFormatter
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
ARCHES=('ptb','loas','gustavsnn')
NAMES=('PTB','LoAS','GustavSNN')
BARS=('128k','256k','512k','1m','ideal')
LABELS=('$128$K','$256$K','$512$K','$1$M','Ideal')
SEGMENTS=('off_chip_weights','off_chip_other')
LEGEND=('Off-chip weights','Off-chip other')
COLORS=('#D55E00','#999999')
HATCHES=('//','xx')
BASELINE='256k'


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    csv_path=ROOT/'outputs/fig1_numbers.csv'
    validation=json.loads((ROOT/'outputs/energy_validation.json').read_text())
    if sha(csv_path)!=validation['csv_sha256']['fig1_numbers.csv']:raise ValueError('unvalidated figure CSV')
    rows=list(csv.DictReader(csv_path.open()))
    data={(r['arch'],r['bar'],r['segment']):r for r in rows}
    available={f.name for f in fm.fontManager.ttflist}
    textfont='Gill Sans' if 'Gill Sans' in available else 'Cantarell' if 'Cantarell' in available else 'DejaVu Sans'
    plt.rcParams.update({'font.family':textfont,'font.size':8,'axes.labelsize':8,'xtick.labelsize':7,
        'ytick.labelsize':8,'legend.fontsize':7,'mathtext.fontset':'custom','mathtext.rm':'DejaVu Sans',
        'mathtext.it':'DejaVu Sans','mathtext.bf':'DejaVu Sans','mathtext.cal':'DejaVu Sans','pdf.fonttype':42,'ps.fonttype':42})
    fig,axes=plt.subplots(1,3,figsize=(7.0,2.2),sharey=True)
    handles=[]
    tops={}
    for arch in ARCHES:
        norm=sum(float(data[(arch,BASELINE,s)]['normalized_mean']) for s in SEGMENTS)
        tops[arch]=[sum(float(data[(arch,b,s)]['normalized_mean']) for s in SEGMENTS)/norm for b in BARS]
    maximum=max(max(v) for v in tops.values())
    for ai,(arch,title,ax) in enumerate(zip(ARCHES,NAMES,axes)):
        norm=sum(float(data[(arch,BASELINE,s)]['normalized_mean']) for s in SEGMENTS)
        x=np.arange(5);bottom=np.zeros(5)
        for segment,color,hatch,label in zip(SEGMENTS,COLORS,HATCHES,LEGEND):
            values=np.array([float(data[(arch,b,segment)]['normalized_mean']) for b in BARS])/norm
            bars=ax.bar(x,values,.73,bottom=bottom,color=color,hatch=hatch,edgecolor='#333333',linewidth=.35,label=label)
            if ai==0:handles.append(bars[0])
            bottom+=values
        for xi,(b,total) in enumerate(zip(BARS,tops[arch])):
            if b==BASELINE:continue
            ax.text(xi,total+maximum*.03,f'${(total-1)*100:+.0f}\\%$',ha='center',va='bottom',fontsize=6.5)
        ax.axhline(1,color='#555555',lw=.7,ls='--',zorder=0)
        ax.set_xticks(x,LABELS);ax.set_title(title,fontweight='bold',fontsize=9,pad=2)
        ax.set_ylim(0,maximum*1.18);ax.spines[['top','right']].set_visible(False)
        ax.set_axisbelow(True);ax.grid(axis='y',alpha=.15,linewidth=.4)
        ax.yaxis.set_major_formatter(StrMethodFormatter('${x:g}$'))
    axes[0].set_ylabel('Normalized off-chip energy',fontsize=7.5)
    fig.legend(handles,LEGEND,loc='upper center',bbox_to_anchor=(.53,1.02),ncol=2,frameon=False)
    fig.subplots_adjust(left=.075,right=.995,bottom=.14,top=.80,wspace=.12)
    for extension in ('pdf','png'):
        fig.savefig(ROOT/f'outputs/fig1_energy_profiling.{extension}',dpi=300,bbox_inches='tight')
    plt.close(fig)
    caption=('Figure 1. Off-chip energy of single-node PTB, LoAS, and GustavSNN as the weight SRAM grows from 128 KiB to 1 MiB, '
             'normalized to each architecture\'s 256 KiB configuration (dashed); labels give the gap to that baseline. '
             'Ideal fetches only spike-selected weights (n = 10 samples, 12 spiking VGG16 convolution layers; '
             'ASAP7 synthesis-only logic prices, table SHA256 '+validation['table_sha256'][:16]+'…).')
    (ROOT/'outputs/caption.txt').write_text(caption+'\n')
    provenance={'input_csv_sha256':sha(csv_path),'energy_validation_sha256':sha(ROOT/'outputs/energy_validation.json'),
        'ideal_dedup_audit_sha256':sha(ROOT/'outputs/self_checks/ideal_dedup_audit/verification.json'),
        'temporal_order_audit_sha256':sha(ROOT/'outputs/self_checks/temporal_order/priced_verification.json'),
        'runtime_prediction_sha256':sha(ROOT/'outputs/self_checks/whole_run_ideal/runtime_prediction.csv'),
        'ideal_semantics':validation['ideal_semantics'],
        'display':'off-chip segments only, renormalized to baseline off-chip total; compute and local SRAM omitted from the stacks; no CIs drawn',
        'table_sha256':validation['table_sha256'],'plot_code_sha256':sha(Path(__file__)),
        'font':textfont,'digit_font':'DejaVu Sans','font_note':'Gill Sans unavailable; Cantarell is the installed humanist-sans fallback' if textfont!='Gill Sans' else 'Gill Sans',
        'files':{n:sha(ROOT/'outputs'/n) for n in ('fig1_energy_profiling.pdf','fig1_energy_profiling.png','caption.txt')},
        'command':'MPLCONFIGDIR=zoo/fig1_energy_profiling/outputs/mplconfig conda run -n gurobi python -B zoo/fig1_energy_profiling/src/plot_energy.py'}
    (ROOT/'outputs/figure_provenance.json').write_text(json.dumps(provenance,indent=2)+'\n')
    print(json.dumps({k:provenance[k] for k in ('font','display')},indent=2))


if __name__=='__main__':main()
