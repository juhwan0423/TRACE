"""Freeze, run, resume and evaluate a paired simulation inspection comparison.

Scene annotations are evaluator inputs. Only the unchanged Harness public
context reaches a planner. This runner does not synthesize a person-loss event.
"""
import argparse
import asyncio
from datetime import datetime, timezone
import fcntl
import hashlib
from importlib.metadata import version
import json
import math
from pathlib import Path
import random
import sys
import time
import urllib.request
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from tracebot.comparison_metrics import evaluate
from tracebot.comparison_policies import CameraOnlyPlanner, FixedOrderVerificationPlanner
from tracebot.harness import Harness
from tracebot.providers.harness_planner import OllamaPlanner
from tracebot.providers.ollama import make_adapter
from tracebot.providers.person_gate import detector_config, with_person_gate, configure_detector_environment
from real2sim_harness_tools import Real2SimTools, remote

POLICIES = ('fixed_order', 'trace', 'camera_only', 'agent_gate_off', 'agent_gate_on')
GOAL = ('An operator requests inspection of the worker. Determine presence and '
        'observable posture using fresh camera evidence; no person-loss event has '
        'been asserted. Move to another viewpoint if needed, or hand off unresolved uncertainty.')
RESET_DESCRIPTION = ('Reset Spot articulation to entrance; settle six simulation seconds; '
                     'freeze authored worker skin/colliders at specified pose. '
                     'Existing scene physics persists; this is not a full-state checkpoint restore.')


def read_json(path):
    return json.loads(Path(path).read_text())


def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(data, indent=2, ensure_ascii=False) + '\n')
    temporary.replace(path)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def source_files():
    files = list((ROOT / 'src/tracebot').rglob('*.py'))
    files += [ROOT / 'scripts' / name for name in (
        'run_real2sim_comparison.py', 'real2sim_harness_tools.py',
        'real2sim_navigation.py', 'real2sim_monitor_scene.py',
        'real2sim_worker_scene.py', 'comparison_gate_control.py',
        'comparison_evaluator_capture.py', 'comparison_support_annotations.py', 'comparison_detector_audit.py')]
    files += [ROOT / 'reports/DETECTOR_GATE_COHORT_20261108.md']
    return sorted(set(files))


def validate_confirmatory_gate(manifest, config, detector):
    if manifest['evaluation_role'] != 'confirmatory':
        return
    scenes = manifest['scenarios']
    if (len(scenes) != 20 or manifest['repetitions'] != 1
            or not manifest.get('preflight_complete') or not manifest.get('archive_all_detector_frames')):
        raise ValueError('Confirmatory gate cohort requires 20 preflighted conditions and full frame archive')
    for posture in ('standing', 'lying'):
        subset = [s for s in scenes if s['actual_posture'] == posture]
        if len(subset) != 10 or sum(s['answerable'] for s in subset) != 8:
            raise ValueError('Require 10 of each posture, with 8 answerable and 2 unanswerable')
    if any(detector[k] != v for k,v in
           dict(confidence=.60, archive_confidence=.05, nms_iou=.7, max_det=300).items()):
        raise ValueError('Confirmatory detector recipe must remain .60/.05/.70/300')
    if not config.get('fixed_gate') or not config.get('evaluator_capture') or not config.get('evaluator_calibration'):
        raise ValueError('Fixed gate and calibrated evaluator capture required')


def validate_manifest(manifest):
    policies = manifest['policies']
    if len(policies) < 2 or len(set(policies)) != len(policies) or not set(policies) <= set(POLICIES):
        raise ValueError('At least two distinct supported policies are required')
    if type(manifest['repetitions']) is not int or manifest['repetitions'] < 1:
        raise ValueError('Positive integer repetitions required')
    ids = set()
    for scene in manifest['scenarios']:
        if not scene['scenario_id'] or scene['scenario_id'] in ids:
            raise ValueError('Scenario IDs must be nonempty and unique')
        ids.add(scene['scenario_id'])
        if scene['actual_posture'] not in ('lying', 'standing'):
            raise ValueError('Physical posture must be lying or standing')
        if type(scene['answerable']) is not bool:
            raise ValueError('Answerability requires an explicit external annotation')
        for key in ('position', 'rotation'):
            if len(scene[key]) != 3 or any(isinstance(v, bool) or not math.isfinite(v) for v in scene[key]):
                raise ValueError('Finite XYZ scene parameters required')
        if not scene.get('geometry_evidence'):
            raise ValueError('Geometry evidence reference required before freezing')
    if not ids:
        raise ValueError('At least one scenario required')
    if manifest['evaluation_role'] not in ('development', 'confirmatory'):
        raise ValueError('Declare development or confirmatory role explicitly')


def schedule_trials(manifest):
    validate_manifest(manifest)
    rng = random.Random(manifest['seed'])
    blocks = [(s, r) for s in manifest['scenarios']
              for r in range(manifest['repetitions'])]
    rng.shuffle(blocks)
    first = rng.randrange(len(manifest['policies']))
    rows = []
    for index, (scene, repetition) in enumerate(blocks):
        policies = manifest['policies']
        offset = (first + index) % len(policies)
        for policy in policies[offset:] + policies[:offset]:
            # Posture variants at one placement are not independent layouts.
            rows.append(dict(trial_id=f't{len(rows):04d}', scene_id=scene['scenario_id'],
                             scenario_id=scene.get('independent_group_id', scene['scenario_id']),
                             repetition_id=f"{scene['scenario_id']}:{repetition}", policy=policy))
    return rows


def model_identity(config):
    base = config['endpoint'].rsplit('/api/', 1)[0]
    with urllib.request.urlopen(base + '/api/tags', timeout=5) as response:
        tags = json.load(response)
    matches = [m for m in tags['models'] if m.get('name') == config['model']]
    if len(matches) != 1 or not matches[0].get('digest'):
        raise RuntimeError('Configured model/digest unavailable; no fallback allowed')
    with urllib.request.urlopen(base + '/api/version', timeout=5) as response:
        version = json.load(response)
    return dict(model=matches[0], ollama=version, endpoint=config['endpoint'])


def freeze(args):
    out = args.output.resolve()
    if out.exists():
        raise FileExistsError('Use a new output directory; a frozen experiment is immutable')
    manifest, config, model = (read_json(p) for p in (args.manifest, args.config, args.model))
    schedule = schedule_trials(manifest)
    gate_comparison = bool(set(manifest['policies']) & {'agent_gate_off','agent_gate_on'})
    gate_config = None
    detector_packages = None
    if gate_comparison:
        if set(manifest['policies']) != {'agent_gate_off','agent_gate_on'}:
            raise ValueError('Person-gate comparison requires exactly its two matched-agent arms')
        if not getattr(args,'person_gate_config',None):
            raise ValueError('Gate comparison requires --person-gate-config')
        gate_config = detector_config(args.person_gate_config)
        detector_packages = {name: version(name) for name in ('ultralytics','torch','torchvision','Pillow')}
        validate_confirmatory_gate(manifest, config, gate_config)
    if config['view_retry_budget'] != 2 or config['max_steps'] < 12:
        raise ValueError('This fixed three-view comparison requires retry2 and >=12 actions')
    if set(config['fixed_order']) != set(config['locations']) or len(config['fixed_order']) != len(config['locations']):
        raise ValueError('Fixed order must visit each common candidate once')
    identity = model_identity(model)
    contents = {str(p.relative_to(ROOT)): p.read_bytes() for p in source_files()}
    files = {p: hashlib.sha256(data).hexdigest() for p, data in contents.items()}
    runtime = asyncio.run(remote('print(json.dumps(trace_comparison_runtime_provenance))'))
    for name in ('scripts/real2sim_navigation.py', 'scripts/real2sim_monitor_scene.py'):
        attached_hash = runtime.get('files', {}).get(name, runtime.get('source_sha256', {}).get(str(ROOT / name)))
        if attached_hash != files[name]:
            raise RuntimeError('Live attachment source differs from current source: ' + name)
    out.mkdir(parents=True)
    for name in files:
        target = out / 'source' / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(contents[name])
    frozen = dict(schema_version=1, frozen_at=datetime.now(timezone.utc).isoformat(),
                  manifest=manifest, config=config, model_config=model,
                  model_identity=identity, schedule=schedule, files=files, runtime_provenance=runtime,
                  trigger='operator_inspection_request', goal=GOAL,
                  reset_protocol=RESET_DESCRIPTION,
                  physical_scope='authored static posture, not physical falling or injury diagnosis')
    if gate_comparison and manifest['evaluation_role'] == 'confirmatory':
        references = set()
        if manifest.get('preflight_summary'):
            references.add(manifest['preflight_summary'])
        if config.get('evaluator_calibration_source'):
            calibration_path=config['evaluator_calibration_source']
            if read_json(calibration_path)!=config['evaluator_calibration']:
                raise ValueError('Calibration config differs from preflight evidence')
            references.add(calibration_path)
        for camera in ('fixed','body'):
            item=config['evaluator_calibration']['cameras'][camera]
            if item['positive_pixel_count']<=0 or digest(item['frame_file'])!=item['frame_sha256']:
                raise ValueError('Positive calibration image absent or changed')
            references.add(item['frame_file'])
        for scene in manifest['scenarios']:
            references.add(scene['geometry_evidence'])
            references.update(scene.get('coverage_evidence', {}).values())
        captures = {scene['geometry_evidence'] for scene in manifest['scenarios']}
        captures.update(p for scene in manifest['scenarios'] for p in scene.get('coverage_evidence', {}).values())
        for capture in captures:
            references.update(frame['path'] for frame in read_json(capture)['frames'].values())
        frozen['preflight_reference_sha256'] = {str(Path(p).resolve()): digest(p) for p in sorted(references)}
        for i,p in enumerate(sorted(references)):
            target=out/'preflight'/(f'{i:03d}'+Path(p).suffix)
            target.parent.mkdir(exist_ok=True)
            target.write_bytes(Path(p).read_bytes())
    if gate_config:
        frozen['person_gate_config'] = gate_config
        frozen['detector_packages'] = detector_packages
        frozen['comparison_factor'] = 'independent RGB person veto only; same adaptive Qwen and existing host rules'
    write_json(out / 'protocol.json', frozen)
    (out / 'protocol.sha256').write_text(digest(out / 'protocol.json') + '\n')
    print(json.dumps(dict(output=str(out), planned_trials=len(schedule),
                          role=manifest['evaluation_role'], frozen=True)), flush=True)


def verify_frozen(out, *, live=False):
    if digest(out / 'protocol.json') != (out / 'protocol.sha256').read_text().strip():
        raise RuntimeError('Frozen protocol changed')
    frozen = read_json(out / 'protocol.json')
    changed = [p for p, sha in frozen['files'].items() if not (ROOT / p).exists() or digest(ROOT / p) != sha]
    if changed:
        raise RuntimeError('Source differs from frozen protocol: ' + ', '.join(changed))
    damaged = [p for p, sha in frozen['files'].items()
               if not (out / 'source' / p).exists() or digest(out / 'source' / p) != sha]
    if damaged:
        raise RuntimeError('Frozen source copy is missing or changed: ' + ', '.join(damaged))
    if any(not Path(p).is_file() or digest(p)!=value for p,value in frozen.get('preflight_reference_sha256',{}).items()):
        raise RuntimeError('Frozen preflight evidence changed')
    if live:
        if frozen.get('person_gate_config'):
            gate = frozen['person_gate_config']
            if digest(gate['model_path']) != gate['model_sha256']:
                raise RuntimeError('Detector checkpoint changed')
            if any(version(name) != value for name,value in frozen['detector_packages'].items()):
                raise RuntimeError('Detector dependency version changed')
        current = model_identity(frozen['model_config'])
        if current['model']['digest'] != frozen['model_identity']['model']['digest'] or current['ollama'] != frozen['model_identity']['ollama']:
            raise RuntimeError('Model digest or Ollama version changed')
    return frozen


class CountedTransport:
    def __init__(self, transport):
        self.transport, self.calls = transport, 0

    async def __call__(self, payload):
        self.calls += 1
        return await self.transport(payload)


class TimedPlanner:
    def __init__(self, planner):
        self.planner, self.latencies = planner, []
        self.transport = CountedTransport(planner.transport) if hasattr(planner,'transport') else None
        if self.transport is not None:
            planner.transport = self.transport

    async def choose(self, context):
        started = time.monotonic()
        try:
            return await self.planner.choose(context)
        finally:
            self.latencies.append(time.monotonic() - started)


class TimedAdapter:
    def __init__(self, adapter):
        self.adapter, self.latencies = adapter, []
        self.transport = CountedTransport(adapter.transport) if hasattr(adapter,'transport') else None
        if self.transport is not None:
            adapter.transport = self.transport

    async def infer(self, evidence):
        started = time.monotonic()
        try:
            return await self.adapter.infer(evidence)
        finally:
            self.latencies.append(time.monotonic() - started)


class TrackedTools(Real2SimTools):
    def __init__(self, *args, **kwargs):
        self.fixed_gate = kwargs.pop('fixed_gate', False)
        super().__init__(*args, **kwargs)
        self.pose_samples = []
        self.gate_samples = []

    async def snapshot(self):
        state = await super().snapshot()
        self.pose_samples.append(dict(time=state['now'], pose=state['pose']))
        if self.fixed_gate:
            try:
                gate = await self.remote('print(json.dumps(trace_confirmatory_gate.verify_closed()))')
            except Exception as error:
                self.gate_samples.append(dict(ready=False, error=str(error),
                                              stage='physical_gate_verification'))
                raise
            self.gate_samples.append(gate)
            if not gate['ready']:
                raise RuntimeError('Fixed gate left frozen physical tolerances')
        return state

    def distance(self):
        points = sorted({p['time']: p['pose'] for p in self.pose_samples}.items())
        return sum(math.hypot(b[1][0]-a[1][0], b[1][1]-a[1][1])
                   for a, b in zip(points, points[1:]))


async def prepare_scene(scene, config):
    before = await remote('real2sim_navigation.guard(); print(json.dumps(real2sim_navigation.snapshot()))')
    if not before['playing'] or before['navigation']['status'] == 'moving':
        raise RuntimeError('Expected owned, playing, idle scene; refusing reset')
    await remote((ROOT / 'scripts/real2sim_worker_scene.py').read_text())
    await remote('print(json.dumps(real2sim_worker_scenario.restore()))')
    reset = await remote('print(json.dumps(real2sim_navigation.reset_to_entrance()))')
    deadline = time.monotonic() + 45
    while True:
        await asyncio.sleep(.2)
        state = await remote('print(json.dumps(real2sim_navigation.snapshot()))')
        if not state['playing'] or state['navigation']['status'] == 'failed':
            raise RuntimeError('Simulation reset/settling failed')
        if state['now'] - reset['now'] >= 6:
            break
        if time.monotonic() >= deadline:
            raise TimeoutError('Simulator did not advance six seconds')
    pose = await remote('print(json.dumps(real2sim_worker_scenario.apply(position,rotation,frame)))',
                        position=scene['position'], rotation=scene['rotation'], frame=scene.get('frame', 0))
    gate_ready = None
    if config.get('fixed_gate'):
        await remote("from pathlib import Path\nexec(compile(Path(helper).read_text(),helper,'exec'),globals())\n"
                     "if not globals().get('trace_confirmatory_gate'): trace_confirmatory_gate=ComparisonGateControl(door,real2sim_navigation)\n"
                     "print(json.dumps(trace_confirmatory_gate.apply_closed()))",
                     helper=str(ROOT/'scripts/comparison_gate_control.py'))
        until=time.monotonic()+30
        while True:
            gate_ready=await remote('print(json.dumps(trace_confirmatory_gate.verify_closed()))')
            if gate_ready['ready']:break
            if time.monotonic()>=until:raise RuntimeError('Fixed gate failed initial-state check')
            await asyncio.sleep(.2)
    if config.get('evaluator_capture'):
        await remote("from pathlib import Path\nexec(compile(Path(helper).read_text(),helper,'exec'),globals())\n"
                     "print(json.dumps(install_comparison_evaluator_capture(globals())))",
                     helper=str(ROOT/'scripts/comparison_evaluator_capture.py'))
    # Discard renderer updates from the previous actor transform; observations
    # still request a strictly newer frame after the episode opens.
    await asyncio.sleep(1)
    final = await remote('print(json.dumps(real2sim_navigation.snapshot()))')
    expected, actual = config['initial_pose'], final['pose']
    yaw_error = abs((actual[2] - expected[2] + math.pi) % (2 * math.pi) - math.pi)
    if (not final.get('ready') or final['navigation']['status'] != 'idle'
            or math.dist(actual[:2], expected[:2]) > config['initial_xy_tolerance_m']
            or yaw_error > config['initial_yaw_tolerance_rad']):
        raise RuntimeError('Reset did not reproduce the frozen initial-pose tolerance')
    return dict(before=before, reset=reset, ready=final, worker=pose, fixed_gate=gate_ready)


def external_truth(scene, config, role):
    return dict(condition=scene['condition'], actual_posture=scene['actual_posture'],
                answerable=scene['answerable'],
                expected_answer=scene['actual_posture'] if scene['answerable'] else 'unknown',
                dangerous=scene['actual_posture'] == 'lying', safe_closure_supported=False,
                incident_start_sim_s=0, deadline_sim_s=config['budget_seconds'],
                wall_budget_s=config.get('wall_budget_seconds'),
                danger_onset_sim_s=0 if scene['actual_posture'] == 'lying' else None,
                discernible_observation_sim_s=None, assertion_supported=None,
                evaluation_role=role, geometry_evidence=scene['geometry_evidence'],
                onset_definition='authored posture at inspection start; not physical fall onset')


async def run_trial(out, frozen, entry):
    from tracebot.comparison_records import normalize_report
    cfg = frozen['config']
    scene = next(s for s in frozen['manifest']['scenarios'] if s['scenario_id'] == entry['scene_id'])
    trial = out / 'trials' / entry['trial_id']
    trial.mkdir(parents=True, exist_ok=False)
    write_json(trial / 'started.json', dict(**entry, started_at=datetime.now(timezone.utc).isoformat()))
    truth = external_truth(scene, cfg, frozen['manifest']['evaluation_role'])
    write_json(trial / 'external_truth.json', truth)
    report = None
    planner = adapter = tools = None
    preparation = None
    preparation_attempted = False
    try:
        preparation_attempted = True
        preparation = await prepare_scene(scene, cfg)
        write_json(trial / 'preparation.json', preparation)
        adapter = TimedAdapter(make_adapter(frozen['model_config']))
        observation_adapter = adapter
        if entry['policy'] == 'agent_gate_on':
            configure_detector_environment(ROOT)
            observation_adapter = with_person_gate(adapter, frozen['person_gate_config'])
        capture_options = dict(fixed_gate=True) if cfg.get('fixed_gate') else {}
        if cfg.get('evaluator_capture'):
            capture_options.update(evaluator_output=trial/'evaluator',
                                   evaluator_calibration=cfg['evaluator_calibration'])
        tools = TrackedTools(observation_adapter, cfg['locations'], trial / 'frames', **capture_options)
        if entry['policy'] in ('trace','agent_gate_off','agent_gate_on'):
            policy = OllamaPlanner(frozen['model_config'])
        elif entry['policy'] == 'fixed_order':
            policy = FixedOrderVerificationPlanner(cfg['fixed_order'], max_observations_per_view=cfg['view_retry_budget'])
        else:
            policy = CameraOnlyPlanner(max_observations_per_view=cfg['view_retry_budget'])
        planner = TimedPlanner(policy)
        def emit(event):
            with (trial / 'events.jsonl').open('a') as handle:
                handle.write(json.dumps(event, ensure_ascii=False) + '\n')
            if event['kind'] in ('decision', 'tool_result', 'terminal', 'aborted', 'finished'):
                print(json.dumps(dict(trial_id=entry['trial_id'], **event), ensure_ascii=False), flush=True)
        harness = Harness(str(uuid.uuid4()), planner, tools,
            budget=cfg['budget_seconds'], wall_budget=cfg['wall_budget_seconds'],
            operation_timeout=cfg['operation_timeout_seconds'], motion_timeout=cfg['motion_timeout_seconds'],
            max_steps=cfg['max_steps'], max_age=cfg['max_evidence_age_seconds'],
            view_retry_budget=cfg['view_retry_budget'], finish_on_inspection_answer=True,
            goal=GOAL, emit=emit)
        try:
            await harness.run()
        finally:
            report = harness.report()
            report.update(config=cfg, planner_records=policy.records, motion_records=tools.motion_records,
                          pose_samples=tools.pose_samples,
                          planner_call_latencies=planner.latencies, vision_call_latencies=adapter.latencies)
            if cfg.get('evaluator_capture'):
                report['captured_evidence'] = tools.captured_evidence
                report['fixed_gate_samples'] = tools.gate_samples
            report['person_gate_cost'] = dict(enabled=entry['policy']=='agent_gate_on',
                calls=getattr(observation_adapter,'detector_calls',0),
                latency_wall_seconds=sum(getattr(observation_adapter,'detector_latencies',[])))
            write_json(trial / 'result.json', report)
            metadata = {key: entry[key] for key in ('trial_id', 'scenario_id', 'repetition_id', 'policy')}
            record = normalize_report(report, **metadata, condition=scene['condition'],
                verification_level='live_isaac_qwen',
                timings=dict(planner_latency_s=sum(planner.latencies), vision_latency_s=sum(adapter.latencies),
                             wall_latency_s=report['wall_seconds'], distance_m=tools.distance()))
            record['scene_id'] = entry['scene_id']
            record['person_gate_cost'] = report['person_gate_cost']
            record['model_calls'] = sum(x.transport.calls for x in (planner,adapter) if x.transport is not None)
            answers = [e['wall_elapsed'] for e in report['trace'] if e['kind']=='inspection_answer']
            record['answer_wall_s'] = answers[0] if answers else None
            terminals = [e['wall_elapsed'] for e in report['trace'] if e['kind']=='terminal']
            record['alert_wall_s'] = terminals[0] if terminals else None
            write_json(trial / 'record.json', record)
            if frozen['manifest'].get('archive_all_detector_frames'):
                from comparison_detector_audit import archive_frames
                try:
                    archive = await archive_frames(report, frozen['person_gate_config'], trial/'detector_audit.json', ROOT)
                    write_json(trial/'detector_audit_cost.json', dict(archive, excluded_from_online_cost=True))
                except BaseException as error:
                    write_json(trial/'integrity_or_availability_error.json',
                               dict(stage='posttrial_detector_archive',error=str(error),exclude_from_confirmatory_claims=True))
                    raise
            if cfg.get('fixed_gate') and any(not sample['ready'] for sample in tools.gate_samples):
                write_json(trial/'integrity_or_availability_error.json',
                           dict(stage='physical_gate_control',error='Fixed gate left frozen tolerances',
                                exclude_from_confirmatory_claims=True))
                raise RuntimeError('Fixed gate physical control violation; inspect before continuing')
    except Exception as error:
        write_json(trial / 'runner_error.json', dict(type=type(error).__name__, message=str(error)))
        if not (trial / 'record.json').exists():
            # Never remove setup/infrastructure failures from the planned denominator.
            record = dict(**entry, condition=scene['condition'], inspection_question_answer='unknown',
                          safety_verdict='unknown', alert_kind='none', status='error', alert_sim_s=None,
                          end_sim_s=None, verification_level='live_isaac_qwen',
                          tool_calls=report.get('executed_tools') if report is not None else 0 if tools is None else None,
                          distance_m=tools.distance() if tools is not None else None,
                          planner_latency_s=sum(planner.latencies) if planner is not None else None,
                          vision_latency_s=sum(adapter.latencies) if adapter is not None else None,
                          wall_latency_s=report.get('wall_seconds') if report is not None else None,
                          sim_latency_s=None, runner_error=str(error),
                          failure_stage='report_normalization' if report is not None else 'setup')
            write_json(trial / 'record.json', record)
        # Infrastructure failures need inspection, not blind reset/retry.
        raise
    finally:
        if preparation_attempted:
            try:
                await remote('print(json.dumps(real2sim_worker_scenario.restore()))')
            except Exception as error:
                write_json(trial / 'cleanup_error.json', dict(error=str(error)))
                raise RuntimeError('Trial cleanup failed; inspect owned scene before continuing') from error


def grounding_annotations_complete(records, annotations):
    for record in records:
        if record.get('inspection_question_answer') not in ('standing', 'lying'):
            continue
        # A claim with no cited RGB is already unsupported, not unannotated.
        if not record.get('normalization', {}).get('answer_evidence_ids'):
            continue
        annotation = annotations.get(record['trial_id'], {})
        present = annotation.get('claim_target_present')
        if type(present) is not bool:
            return False
        if present and annotation.get('claim_observed_posture') not in ('standing', 'lying', 'unreadable'):
            return False
    return True


def summarize(out, *, verify=True):
    frozen = verify_frozen(out) if verify else read_json(out / 'protocol.json')
    records, truth, missing, integrity_blocked = [], {}, [], []
    for entry in frozen['schedule']:
        trial = out / 'trials' / entry['trial_id']
        flags = [name for name in ('integrity_or_availability_error.json', 'cleanup_error.json')
                 if (trial / name).exists()]
        if frozen['manifest'].get('archive_all_detector_frames') and (trial/'record.json').exists():
            audit=read_json(trial/'detector_audit.json') if (trial/'detector_audit.json').exists() else {}
            if not audit.get('complete'):
                flags.append('incomplete_detector_archive')
        if flags:
            integrity_blocked.append(dict(**entry, markers=flags))
        if (trial / 'record.json').exists():
            record = read_json(trial / 'record.json')
            if any(record.get(key) != value for key, value in entry.items()):
                raise RuntimeError('Saved result does not match its planned trial: ' + entry['trial_id'])
            records.append(record)
            truth[entry['trial_id']] = read_json(trial / 'external_truth.json')
        else:
            missing.append(entry)
    summary = evaluate(records, truth, expected_policies=frozen['manifest']['policies'])
    if set(frozen['manifest']['policies']) == {'agent_gate_off','agent_gate_on'}:
        from tracebot.detector_gate_metrics import evaluate_gate
        annotation_path = out / 'support_annotations.json'
        annotations = read_json(annotation_path) if annotation_path.exists() else {}
        if frozen['config'].get('evaluator_capture'):
            from comparison_support_annotations import build_support
            generated = build_support(out, records)
            write_json(out/'segmentation_support_annotations.json',generated)
            for trial_id, human in annotations.items():
                automatic=generated.get(trial_id)
                if automatic is None:continue
                if set(human['evidence_ids']) != set(automatic['evidence_ids']):
                    raise ValueError('Human annotation references differ from actual cited frames')
                present=automatic['claim_target_present']
                if (human.get('claim_target_present') is not None and present is not None
                        and human['claim_target_present']!=present):
                    raise ValueError('Human presence annotation conflicts with verified segmentation; review required')
                automatic['claim_observed_posture']=human.get('claim_observed_posture')
                automatic['posture_source']='external_human_annotation'
            annotations=generated
        gate_metrics = evaluate_gate(records, truth, annotations,
            expected_trial_ids=[entry['trial_id'] for entry in frozen['schedule']])
        gate_metrics.update(integrity_blocked_trials=integrity_blocked,
                            schedule_complete=not missing,
                            execution_complete=not missing and not integrity_blocked)
        annotation_complete=grounding_annotations_complete(records, annotations) and all(
            policy['presence_unsupported_assertion_risk']['unknown']==0
            and policy['grounded_correct_within_budget_rate']['unknown']==0
            for stratum in gate_metrics['strata'] for policy in stratum['policies'].values())
        gate_metrics['grounding_annotation_complete']=bool(not missing and annotation_complete)
        gate_metrics['comparison_complete']=bool(not missing and not integrity_blocked and annotation_complete)
        write_json(out / 'detector_gate_summary.json', gate_metrics)
    summary.update(planned_trials=len(frozen['schedule']), missing_planned_trials=missing,
                   schedule_complete=not missing,
                   integrity_blocked_trials=integrity_blocked,
                   comparison_complete=summary['comparison_complete'] and not missing and not integrity_blocked)
    write_json(out / 'summary.json', summary)
    write_json(out / 'records.json', records)
    write_json(out / 'external_truth.json', truth)
    print(json.dumps(dict(recorded=len(records), planned=len(frozen['schedule']),
                          schedule_complete=not missing, output=str(out / 'summary.json'))), flush=True)
    return summary


async def run(args):
    out = args.output.resolve()
    frozen = verify_frozen(out, live=True)
    for entry in frozen['schedule']:
        trial = out / 'trials' / entry['trial_id']
        if any((trial / marker).exists() for marker in
               ('integrity_or_availability_error.json', 'cleanup_error.json')):
            raise RuntimeError('Trial has a persistent integrity/cleanup marker; audit before any continuation: ' + str(trial))
        if (trial / 'record.json').exists():
            if frozen['manifest'].get('archive_all_detector_frames'):
                if not (trial/'detector_audit.json').is_file() or not read_json(trial/'detector_audit.json').get('complete'):
                    raise RuntimeError('Recorded trial has incomplete detector archive; audit before continuing')
            continue
        if trial.exists():
            raise RuntimeError('Interrupted trial must be audited and retained before resuming: ' + str(trial))
        verify_frozen(out, live=True)
        runtime = await remote('print(json.dumps(trace_comparison_runtime_provenance))')
        if runtime != frozen['runtime_provenance']:
            raise RuntimeError('Live scene attachment changed')
        try:
            await run_trial(out, frozen, entry)
        finally:
            try:
                verify_frozen(out, live=True)
                runtime = await remote('print(json.dumps(trace_comparison_runtime_provenance))')
                if runtime != frozen['runtime_provenance']:
                    raise RuntimeError('Live scene attachment changed during trial')
                summarize(out)
            except Exception as error:
                write_json(out / 'trials' / entry['trial_id'] / 'integrity_or_availability_error.json',
                           dict(error=str(error), exclude_from_confirmatory_claims=True))
                raise
    if frozen['config'].get('fixed_gate'):
        restored=await remote('print(json.dumps(trace_confirmatory_gate.restore()))')
        write_json(out/'fixed_gate_cleanup.json',restored)
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('freeze', 'run', 'evaluate'))
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--manifest', type=Path)
    parser.add_argument('--config', type=Path, default=ROOT / 'configs/comparison_real2sim.json')
    parser.add_argument('--model', type=Path, default=ROOT / 'configs/vlm_local.json')
    parser.add_argument('--person-gate-config', type=Path,
                        help='Required when freezing matched agent_gate_off/on arms')
    args = parser.parse_args()
    if args.command == 'freeze':
        if args.manifest is None:
            parser.error('freeze requires --manifest')
        freeze(args)
    elif args.command == 'evaluate':
        summarize(args.output.resolve())
    else:
        lock = ROOT / 'artifacts/closed_loop/runner.lock'
        lock.parent.mkdir(parents=True, exist_ok=True)
        with lock.open('a') as handle:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                parser.error('Another TRACE runner owns the scene')
            asyncio.run(run(args))


if __name__ == '__main__':
    main()
