"""Summarize recorded runs without treating completion as a successful diagnosis."""
import argparse
import hashlib
import json
from pathlib import Path
import statistics


def summarize(path):
    path=Path(path)
    report=json.loads((path/'result.json').read_text())
    manifest=json.loads((path/'manifest.json').read_text())
    conditions=dict(config=manifest['config'],model=manifest['model_config'],files=manifest['files'],
        runtime_revision=manifest['initial_snapshot'].get('runtime_revision','unrecorded'))
    fingerprint=hashlib.sha256(json.dumps(conditions,sort_keys=True).encode()).hexdigest()
    mismatches=[]
    for name,digest in manifest['files'].items():
        source=path/'source'/name
        if not source.exists() or hashlib.sha256(source.read_bytes()).hexdigest()!=digest:
            mismatches.append(name)
    trace=report['trace'];observations=report.get('evidence_records',[])
    # Use the normalized observations logged by the harness, not provider-specific records.
    clear=sum(bool(e.get('valid') and e.get('status')=='ok' and e.get('observation')
        and e['observation'].get('person_visible')=='yes'
        and not e['observation'].get('observation_limitations',[])
        and not e['observation'].get('needs_more_observation',True))
        for e in trace if e['kind']=='tool_result' and e.get('tool')=='observe')
    return dict(episode=report['episode'],conditions=fingerprint,source_verified=not mismatches,
        source_mismatches=mismatches,camera_policy=manifest['config'].get('camera_policy','unrecorded'),
        completed=report['completed'],state=report['state'],error=report['error'],stop_error=report['stop_error'],
        inspection_answered=bool(report.get('inspection_answer')),
        wall_seconds=report['wall_seconds'],decisions=report['agent_decisions'],
        observations=len(observations),valid_observations=sum(bool(r['valid']) for r in observations),
        clear_subject_observations=clear,
        arrivals=sum(r['navigation']['status']=='arrived' for r in report.get('motion_records',[])),
        tool_errors=sum(e['kind']=='tool_result' and e.get('status') in ('error','timeout','failed') for e in trace),
        rejected_actions=sum(e['kind']=='rejected' for e in trace),
        initial_pose=manifest['initial_snapshot'].get('pose'))


def aggregate(rows):
    groups={}
    for row in rows:groups.setdefault(row['conditions'],[]).append(row)
    return [dict(conditions=key,runs=len(items),mean_wall_seconds=statistics.mean(r['wall_seconds'] for r in items),
        completed=sum(r['completed'] for r in items),
        unresolved=sum(r['state']=='escalated_unknown' for r in items),
        all_sources_verified=all(r['source_verified'] for r in items)) for key,items in groups.items()]


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('episodes',nargs='+',type=Path)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    rows=[summarize(path) for path in args.episodes]
    result=dict(runs=rows,groups=aggregate(rows),
        interpretation='Groups match recorded config, model, runtime revision and source hashes. Initial physical states and animation phase still require separate assessment. Clear subject is a VLM claim, not ground-truth accuracy. Completion is not diagnostic success; no false-safe rate is computed without labeled scenarios.')
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2))
    for row in rows:
        print(f"{row['episode']} {row['camera_policy']} {row['state']} {row['wall_seconds']:.1f}s "
              f"arrivals={row['arrivals']} clear={row['clear_subject_observations']}/{row['observations']} "
              f"errors={row['tool_errors']} rejected={row['rejected_actions']}")
