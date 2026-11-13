"""Reproduce presentation figures from finalized evaluator output (no model calls)."""
import json
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
ROOT=Path(__file__).resolve().parents[2]
OUT=Path(__file__).resolve().parent
SOURCE=ROOT/'artifacts/comparisons/20261109_scoped_limitations_01/detector_gate_summary.json'
d=json.loads(SOURCE.read_text())
assert d['comparison_complete'] and d['grounding_annotation_complete']
s=d['strata'][0]['policies'];arms=['agent_gate_off','agent_gate_on']
colors=['#758399','#167D9A'];labels=['Gate OFF','Gate ON']
plt.rcParams.update({'font.family':'DejaVu Sans','font.size':13,'axes.spines.top':False,'axes.spines.right':False,'axes.titleweight':'bold','pdf.fonttype':42,'ps.fonttype':42,'svg.fonttype':'none'})
def save(fig,name):
 for ext in ['png','pdf','svg']:fig.savefig(OUT/f'{name}.{ext}',dpi=300,facecolor='white')
 plt.close(fig)
fig,axs=plt.subplots(1,3,figsize=(13.33,6.0))
fig.subplots_adjust(left=.065,right=.98,top=.72,bottom=.24,wspace=.40)
fig.suptitle('Inspection performance and operating cost',x=.065,y=.96,ha='left',fontsize=23,fontweight='bold')
fig.text(.065,.875,'Same revised host rules in both arms | 20 attempted trials per arm',fontsize=13,color='#4B5563')
metrics=[('grounded_correct_within_budget_rate','Grounded correct answers','Higher is better',True),('presence_unsupported_assertion_risk','Target-absent assertions','Lower is better',True),('wall_latency_s','Mean elapsed time','Lower is better',False)]
for ax,(key,title,direction,rate) in zip(axs,metrics):
 vals=[s[a][key]['value']*100 if rate else s[a]['costs'][key]['value'] for a in arms]
 ax.bar(labels,vals,color=colors,width=.54,zorder=3)
 ax.set_title(title,fontsize=15,pad=29)
 ax.text(.5,1.045,direction,transform=ax.transAxes,ha='center',fontsize=11,color='#64748B')
 ax.set_ylim(0,100 if rate else 350)
 ax.set_ylabel('Trials (%)' if rate else 'Seconds')
 ax.set_yticks([0,25,50,75,100] if rate else [0,100,200,300])
 ax.grid(axis='y',color='#E2E8F0',zorder=0);ax.set_axisbelow(True)
 for i,v in enumerate(vals):
  text=f"{v:.0f}%\n({s[arms[i]][key]['numerator']}/20)" if rate else f'{v:.1f} s'
  ax.text(i,v+(3 if rate else 9),text,ha='center',va='bottom',fontweight='bold',fontsize=14)
fig.text(.065,.115,'Development rerun in one lab; paired conditions. Descriptive results, not proof of superiority.',fontsize=11,color='#475569')
fig.text(.065,.065,'Grounding: target visibility checked by simulation masks; cited-frame posture reviewed by one human.',fontsize=10.5,color='#475569')
save(fig,'trace_final_results')
# Supporting chart: every elapsed-time observation, avoiding a mean-only presentation.
records=json.loads((SOURCE.parent/'records.json').read_text())
fig,ax=plt.subplots(figsize=(8,5.5));fig.subplots_adjust(left=.14,right=.96,bottom=.22,top=.84)
rng=np.random.default_rng(20261109)
for i,arm in enumerate(arms):
 vals=np.array([r['wall_latency_s'] for r in records if r['policy']==arm]);assert len(vals)==20
 ax.scatter(i+rng.uniform(-.12,.12,len(vals)),vals,color=colors[i],alpha=.8,s=38,edgecolors='white',linewidths=.5)
 ax.hlines(vals.mean(),i-.22,i+.22,color='#0F172A',linewidth=2.5)
 ax.text(i+.25,vals.mean(),f'{vals.mean():.1f} s',va='center',fontsize=11)
ax.set_xticks([0,1],labels);ax.set_xlim(-.5,1.65);ax.set_ylim(bottom=0)
ax.set_ylabel('Elapsed time (seconds)');ax.set_title('Elapsed time across all attempted trials',pad=18)
ax.grid(axis='y',alpha=.2);ax.set_axisbelow(True)
fig.text(.14,.09,'Each point = one trial; black line = mean. Includes timeouts.\n20 trials per arm; one-lab development rerun.',fontsize=10,color='#475569')
save(fig,'trace_elapsed_distribution')
print(OUT)
