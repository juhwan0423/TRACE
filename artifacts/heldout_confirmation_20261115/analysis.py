"""Pre-registered pooled analysis for the TRACE held-out gate confirmation (2026-11-15).
Read-only: consumes each frozen cohort's records.json, external_truth.json,
segmentation_support_annotations.json and (optional) support_annotations.json written by
`run_real2sim_comparison.py evaluate`. Never calls a model, detector or simulator.

P1 (primary): presence-unsupported posture assertion per attempted trial. H1: gate ON < OFF.
   Exact one-sided sign test on discordant condition pairs, alpha 0.05.
   Sensitivity: placement-cluster sign test (sum over the two postures of OFF-ON).
S1: grounded-correct-within-budget per attempted trial. Two-sided exact McNemar; ON-OFF
   difference with placement-cluster bootstrap 95% CI (10000 resamples, seed 20261115);
   non-inferiority margin -0.10 (pre-declared).
S2: wall time per trial; paired ON-OFF mean difference with the same cluster bootstrap.
Unknown (null) outcomes are never imputed; analyses report them and identification bounds.
"""
import argparse,json,math,random,sys
from collections import defaultdict
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'src'))
from tracebot.detector_gate_metrics import _prepare,evaluate_gate

def binom_tail(k,n):  # P(X>=k), X~Bin(n,.5)
    return sum(math.comb(n,i) for i in range(k,n+1))/2**n if n else 1.0
def two_sided(b,c):
    n=b+c
    return min(1.0,2*binom_tail(max(b,c),n)) if n else 1.0
def load(cohort):
    rd=lambda n:json.loads((cohort/n).read_text())
    records,truth=rd('records.json'),rd('external_truth.json')
    seg=rd('segmentation_support_annotations.json') if (cohort/'segmentation_support_annotations.json').exists() else {}
    human=rd('support_annotations.json') if (cohort/'support_annotations.json').exists() else {}
    ann={}
    for tid,a in seg.items():
        a=dict(a)
        if tid in human:
            if set(human[tid]['evidence_ids'])!=set(a['evidence_ids']):raise ValueError('annotation/evidence mismatch '+tid)
            a['claim_observed_posture']=human[tid].get('claim_observed_posture')
        ann[tid]=a
    return records,truth,ann
def boot(clusters,fn,seed=20261115,n=10000):
    rng=random.Random(seed);keys=sorted(clusters);vals=[]
    for _ in range(n):
        sample=[clusters[rng.choice(keys)] for _ in keys]
        v=fn([p for c in sample for p in c])
        if v is not None:vals.append(v)
    vals.sort()
    return [vals[int(.025*len(vals))],vals[int(.975*len(vals))-1]] if vals else None
def main():
    ap=argparse.ArgumentParser();ap.add_argument('cohorts',nargs='+',type=Path);ap.add_argument('--out',type=Path);a=ap.parse_args()
    all_rec,all_truth,all_ann,rows=[],{},{},[]
    for ci,c in enumerate(a.cohorts):
        records,truth,ann=load(c)
        for r in records:
            local=r['trial_id'];tid=f'{c.name}:{local}';r=dict(r,trial_id=tid)
            all_rec.append(r);all_truth[tid]=truth[local];all_ann[tid]=ann.get(local)
            row=_prepare(dict(r),all_truth[tid],all_ann[tid]);row['cohort']=c.name;rows.append(row)
    pairs=defaultdict(dict)
    for r in rows:pairs[(r['cohort'],r['repetition_id'])][r['policy']]=r
    incomplete=[list(k) for k,v in pairs.items() if set(v)!={'agent_gate_off','agent_gate_on'}]
    full=[(k,v) for k,v in pairs.items() if set(v)=={'agent_gate_off','agent_gate_on'}]
    cluster=lambda k,v:(k[0],v['agent_gate_off']['scenario_id'])
    def paired(metric):
        b=c=both=neither=unk=0
        for k,v in full:
            off,on=v['agent_gate_off'][metric],v['agent_gate_on'][metric]
            if off is None or on is None:unk+=1;continue
            if off and not on:b+=1
            elif on and not off:c+=1
            elif on and off:both+=1
            else:neither+=1
        return dict(off_only=b,on_only=c,both=both,neither=neither,unknown_pairs=unk)
    def arm_counts(metric):
        out={}
        for p in ('agent_gate_off','agent_gate_on'):
            vals=[r[metric] for r in rows if r['policy']==p]
            out[p]=dict(numerator=sum(v is True for v in vals),unknown=sum(v is None for v in vals),denominator=len(vals))
        return out
    p1=paired('presence_unsupported')
    p1['one_sided_sign_test_p']=binom_tail(p1['off_only'],p1['off_only']+p1['on_only'])
    clus=defaultdict(int)
    for k,v in full:
        o,n=v['agent_gate_off']['presence_unsupported'],v['agent_gate_on']['presence_unsupported']
        if o is not None and n is not None:clus[cluster(k,v)]+=int(o)-int(n)
    pos=sum(d>0 for d in clus.values());neg=sum(d<0 for d in clus.values())
    p1['cluster_sensitivity']=dict(clusters=len(clus),off_worse=pos,on_worse=neg,one_sided_p=binom_tail(pos,pos+neg))
    p1['confirmed_at_0_05']=p1['unknown_pairs']==0 and p1['one_sided_sign_test_p']<.05
    s1=paired('grounded_correct');s1['two_sided_mcnemar_p']=two_sided(s1['off_only'],s1['on_only'])
    clusters=defaultdict(list)
    for k,v in full:clusters[cluster(k,v)].append(v)
    def diff(metric):
        def f(ps):
            d=[(1 if p['agent_gate_on'][metric] else 0)-(1 if p['agent_gate_off'][metric] else 0) for p in ps
               if p['agent_gate_on'][metric] is not None and p['agent_gate_off'][metric] is not None]
            return sum(d)/len(d) if d else None
        return f
    allp=[v for _,v in full]
    s1['on_minus_off']=diff('grounded_correct')(allp);s1['cluster_bootstrap_95ci']=boot(clusters,diff('grounded_correct'))
    s1['noninferior_margin_minus_0_10']=None if s1['unknown_pairs'] or not s1['cluster_bootstrap_95ci'] else s1['cluster_bootstrap_95ci'][0]>-.10
    def wall(ps):
        d=[p['agent_gate_on']['wall_latency_s']-p['agent_gate_off']['wall_latency_s'] for p in ps
           if p['agent_gate_on']['wall_latency_s'] is not None and p['agent_gate_off']['wall_latency_s'] is not None]
        return sum(d)/len(d) if d else None
    s2=dict(on_minus_off_mean_wall_s=wall(allp),cluster_bootstrap_95ci=boot(clusters,wall))
    gate=evaluate_gate(all_rec,all_truth,{k:v for k,v in all_ann.items() if v is not None})
    result=dict(schema='trace_heldout_confirmation_v1',cohorts=[str(c) for c in a.cohorts],trials=len(rows),complete_pairs=len(full),incomplete_pairs=incomplete,
                P1_presence_unsupported=dict(arm_counts=arm_counts('presence_unsupported'),**p1),
                S1_grounded_correct=dict(arm_counts=arm_counts('grounded_correct'),**s1),
                S2_wall_time=s2,pooled_descriptives=gate)
    text=json.dumps(result,indent=1)
    if a.out:a.out.write_text(text+'\n')
    print(json.dumps({k:result[k] for k in ('trials','complete_pairs','P1_presence_unsupported','S1_grounded_correct','S2_wall_time')},indent=1))
if __name__=='__main__':main()
