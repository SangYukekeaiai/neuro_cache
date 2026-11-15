"""Plot all fifteen layer-8 results, explicitly marked as dummy-price output."""
import csv
import json
from pathlib import Path
import textwrap
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib import font_manager
from matplotlib.ticker import LogFormatterMathtext
import numpy as np
HERE=Path(__file__).resolve().parent
ARCHES=('spinalflow','ptb','loas','gustavsnn','prosperity')
ARMS=('spad','cacheA','cacheB')


def main():
    rows=list(csv.DictReader((HERE/'comparison.csv').open()))
    by={(r['arch'],r['arm']):r for r in rows}
    assert len(rows)==len(by)==15
    assert all(r['incomplete']=='True' and np.isfinite(float(r['EDP_nJ_s'])) and float(r['EDP_nJ_s'])>0 for r in rows)
    fonts={f.name for f in font_manager.fontManager.ttflist}
    face=next(f for f in ('Gill Sans','Gill Sans MT','Lato','Cantarell','DejaVu Sans') if f in fonts)
    plt.rcParams.update({'font.family':face,'font.size':8,'pdf.fonttype':42,'mathtext.fontset':'custom',
                         'mathtext.rm':face,'mathtext.it':face,'mathtext.bf':face,'mathtext.cal':face,
                         'axes.spines.top':False,'axes.spines.right':False})
    fig,ax=plt.subplots(figsize=(7,4.7))
    colors=('#999999','#0072B2','#E69F00');hatches=('','//','..')
    x=np.arange(5);width=.24
    for i,arm in enumerate(ARMS):
        values=[float(by[(a,arm)]['EDP_nJ_s'])*1e-3 for a in ARCHES]
        ax.bar(x+(i-1)*width,values,width,color=colors[i],hatch=hatches[i],edgecolor='black',linewidth=.45,label=arm)
    ax.set_yscale('log');ax.yaxis.set_major_formatter(LogFormatterMathtext())
    ax.set_ylabel('EDP (mJ ms; logarithmic scale)')
    ax.set_xticks(x,('SpinalFlow','PTB','LoAS','GustavSNN','Prosperity'))
    ax.set_xlim(-.65,4.65);ax.set_ylim(.1,200)
    ax.legend(frameon=False,ncol=3,loc='lower center',bbox_to_anchor=(.5,1.01))
    ax.set_title('VGG16 layer 8 — DUMMY PRICES',fontsize=11,pad=32)
    caption=('DUMMY placeholder pending ASAP7 synthesis. B09 loas_vgg16_T4_n500, layer_08_core_features_27 (kept 3x3 convolution), sample 0. '
             'Five architectures x three memory arms; n=1, no variance estimate or error bars. EDP=(dynamic+leakage energy) x simulated latency, shown in mJ ms on a log axis. '
             'All pending prices are filled with retired-characterization magnitudes, archived composition estimates or stated uncharacterized magnitudes, including router/controllers. '
             'All rows remain flagged incomplete; these finite totals are neither final characterization nor lower bounds. CacheA: next_access d4, distance_aware d1/t9; cacheB policies unchanged.')
    fig.text(.09,.025,textwrap.fill(caption,123),ha='left',va='bottom',fontsize=7)
    fig.tight_layout(rect=(0,.29,1,1))
    out=HERE.parents[1]/'figures';out.mkdir(exist_ok=True)
    fig.savefig(out/'layer8_dummy_edp.pdf',bbox_inches='tight')
    fig.savefig(out/'layer8_dummy_edp.png',dpi=300,bbox_inches='tight')
    (out/'layer8_dummy_edp.caption.txt').write_text(caption+'\n')
    (out/'layer8_dummy_edp.provenance.json').write_text(json.dumps({'source':str(HERE/'comparison.csv'),'font':face,'font_fallback':face not in ('Gill Sans','Gill Sans MT'),'table':json.loads((HERE/'output_paths.json').read_text())['dummy_table_sha256']},indent=2)+'\n')
    print(json.dumps({'pdf':str(out/'layer8_dummy_edp.pdf'),'png':str(out/'layer8_dummy_edp.png'),'font':face}))


if __name__=='__main__':main()
