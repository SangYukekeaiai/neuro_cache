"""Render Figure 1 from validated whole-model energy statistics."""
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
SEGMENTS=('compute','on_chip_sram','off_chip_weights','off_chip_other')
LEGEND=('Compute','Local SRAM','Off-chip weights','Off-chip other')
COLORS=('#0072B2','#E69F00','#D55E00','#999999')
HATCHES=('', '..', '//', 'xx')


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
    fig,axes=plt.subplots(1,3,figsize=(7.0,4.0),sharey=True)
    maximum=max(float(r['normalized_mean'])+float(r['normalized_error_upper']) for r in rows if r['segment']=='total')
    handles=[]
    for ai,(arch,title,ax) in enumerate(zip(ARCHES,NAMES,axes)):
        x=np.arange(5);bottom=np.zeros(5)
        for segment,color,hatch,label in zip(SEGMENTS,COLORS,HATCHES,LEGEND):
            values=np.array([float(data[(arch,b,segment)]['normalized_mean']) for b in BARS])
            bars=ax.bar(x,values,.73,bottom=bottom,color=color,hatch=hatch,edgecolor='#333333',linewidth=.35,label=label)
            if ai==0:handles.append(bars[0])
            bottom+=values
        errors=[[float(data[(arch,b,'total')][field]) for b in BARS] for field in ('normalized_error_lower','normalized_error_upper')]
        ax.errorbar(x,bottom,yerr=errors,fmt='none',color='black',capsize=2,lw=.65)
        ax.axhline(1,color='#555555',lw=.7,ls='--',zorder=0)
        ax.set_xticks(x,LABELS);ax.set_title(title,fontweight='bold',fontsize=9)
        ax.set_ylim(0,maximum*1.12);ax.spines[['top','right']].set_visible(False)
        ax.set_axisbelow(True);ax.grid(axis='y',alpha=.15,linewidth=.4)
        ax.yaxis.set_major_formatter(StrMethodFormatter('${x:g}$'))
    axes[0].set_ylabel('Normalized whole-model energy')
    fig.legend(handles,LEGEND,loc='upper center',bbox_to_anchor=(.51,.92),ncol=4,frameon=False)
    fig.suptitle('ASAP7 synthesis-only estimates',fontsize=9,fontweight='bold',y=.99)
    fig.subplots_adjust(left=.085,right=.99,bottom=.39,top=.78,wspace=.15)
    footer=('Weight SRAM only; baseline $256$ KiB = $1$ per architecture; $n=10$ samples, $12$ conv layers.\n'
            'Baselines: $95\\%$ t CI. Ideal: runtime-bound midpoint; whiskers cover bounds plus sample CI.\n'
            'Ideal runtime bracketed by compute/DRAM-occupancy bounds; exact first-use timing within.\n'
            'Unique-union dynamics: SPD $32$B packets, $64$B DRAM energy bursts; gray = standing DRAM/IO leakage.\n'
            'Genus synthesis only (no P&R), mixed corners/unconstrained I/O; state SRAM: capacity/leakage only.')
    fig.text(.085,.23,footer,ha='left',va='top',fontsize=6.3,linespacing=1.4)
    short=validation['table_sha256'][:16]
    fig.text(.085,.02,'Table SHA256: '+short+'… (full hash in caption/provenance)',fontsize=6)
    for extension in ('pdf','png'):
        fig.savefig(ROOT/f'outputs/fig1_energy_profiling.{extension}',dpi=300,bbox_inches='tight')
    plt.close(fig)
    caption=('Figure 1. Whole-model energy for single-node PTB (8 COUT PEs), LoAS (16), and GustavSNN (1 HO x 8 COUT). '
             'Each bar sums all 12 kept B09 VGG16 convolution layers per sample, then reports the mean of samples 000–009. '
             'Bars and Student-t 95% CI half-widths (df=9) are divided by the architecture\'s fixed mean 256KiB baseline; '
             'the intervals describe sample-mean energy on that scale, not uncertainty of a ratio estimator. '
             'Traversal is HO→WO→COUT with resident T for PTB/LoAS, and COUT→HO→WO→T for GustavSNN; weights remain resident across GustavSNN pixel/time visits. '
             'Only weight SRAM capacity is swept; fixed psum/vmem provisions are 256/512KiB, charged once for area/leakage with zero added dynamic accesses. '
             'Native register/LIF/RF activity remains in compute. Ideal retains 256KiB geometry and native compute work; its leakage follows the midpoint of its own analytic duration bounds, '
             'substituting only the deduplicated union of weight words touched across all spikes, timesteps, pixels and tiles: DRAM reads, IO bytes and local fills. Existing unique-union dynamic counts are packetized as SPD transfers (32-byte packets, with the existing 64-byte DRAM energy-accounting burst rounding), not deduplicated cache lines. This immediate figure retains the saved per-layer compulsory-union transfer grouping; exact first-use transfer grouping remains pending. Ideal runtime bracketed by compute/DRAM-occupancy bounds; exact first-use timing within. Whiskers envelope the lower-bound mean minus its 95% sample CI and the upper-bound mean plus its 95% sample CI; they are not an exact-runtime confidence interval. No GB or inter-node inventory is present. '
             'Off-chip other contains standing DDR4/IO leakage; no non-weight DRAM dynamic transfers are emitted. '
             'Logic prices use Genus synthesis-only reports, linear width/depth interpolation and additive primitive compositions, without post-route parasitics. '
             'Default library declarations are mixed (AO/INVBUF/OA/SEQ 0.77V/0C; SIMPLE 0.70V/25C); I/O is unconstrained. '
             'SRAM is the FN-CACTI 7nm/0.7V extrapolated physical model; commodity DDR4/IO retain pinned CACTI7 prices. '
             'No post-route or end-to-end 500MHz timing signoff is claimed. Table SHA256: '+validation['table_sha256']+'.')
    (ROOT/'outputs/caption.txt').write_text(caption+'\n')
    provenance={'input_csv_sha256':sha(csv_path),'energy_validation_sha256':sha(ROOT/'outputs/energy_validation.json'),
        'ideal_dedup_audit_sha256':sha(ROOT/'outputs/self_checks/ideal_dedup_audit/verification.json'),
        'temporal_order_audit_sha256':sha(ROOT/'outputs/self_checks/temporal_order/priced_verification.json'),
        'runtime_prediction_sha256':sha(ROOT/'outputs/self_checks/whole_run_ideal/runtime_prediction.csv'),
        'ideal_semantics':validation['ideal_semantics'],
        'table_sha256':validation['table_sha256'],'plot_code_sha256':sha(Path(__file__)),
        'font':textfont,'digit_font':'DejaVu Sans','font_note':'Gill Sans unavailable; Cantarell is the installed humanist-sans fallback' if textfont!='Gill Sans' else 'Gill Sans',
        'files':{n:sha(ROOT/'outputs'/n) for n in ('fig1_energy_profiling.pdf','fig1_energy_profiling.png','caption.txt')},
        'command':'MPLCONFIGDIR=zoo/fig1_energy_profiling/outputs/mplconfig conda run -n gurobi python -B zoo/fig1_energy_profiling/src/plot_energy.py'}
    (ROOT/'outputs/figure_provenance.json').write_text(json.dumps(provenance,indent=2)+'\n')
    print(json.dumps(provenance,indent=2))


if __name__=='__main__':main()
