"""Bounded model-directed tool loop. Policy, clocks and actuators remain host-owned."""
import asyncio
from dataclasses import asdict
import json
import math
import time
from .core import Incident, State, TERMINAL
from .context import ContextGraph
from .providers.single_frame_vlm import incident_decision

ACTIONS = {'observe', 'inspect', 'wait', 'stop', 'escalate'}


def validate_action(value, catalog):
    if not isinstance(value, dict) or set(value) not in ({'tool', 'target', 'reason'}, {'tool', 'target', 'reason', 'question_id'}):
        raise ValueError('expected tool, target, reason only')
    if any(type(value[k]) is not str for k in value):
        raise ValueError('action fields must be strings')
    if not value['reason'].strip() or len(value['reason']) > 500:
        raise ValueError('bounded nonempty reason required')
    if (value['tool'], value['target']) not in {(x['tool'], x['target']) for x in catalog}:
        raise ValueError('tool/target not currently available')
    return value


class Harness:
    def __init__(self, episode, planner, tools, *, budget=180., wall_budget=900.,
                 operation_timeout=180., motion_timeout=600., max_steps=12, max_age=45., emit=None):
        for value in (budget, wall_budget, operation_timeout, motion_timeout, max_age):
            if not math.isfinite(value) or value <= 0:
                raise ValueError('finite positive limits required')
        if type(max_steps) is not int or not 1 <= max_steps <= 100:
            raise ValueError('max_steps must be 1..100')
        self.episode, self.planner, self.tools = episode, planner, tools
        self.budget, self.wall_budget, self.operation_timeout = budget, wall_budget, operation_timeout
        self.max_steps, self.max_age = max_steps, max_age
        self.motion_timeout = motion_timeout
        self.emit = emit or (lambda event: None)
        self.incident = None
        self.trace, self.memory, self.failed_targets = [], [], set()
        self.last_target = None
        self.awaiting_body_observation = False
        self.viewpoint_arrived_at = None
        self.evidence_records = []
        self.questions = ContextGraph(episode, max_age=max_age)
        self.active_question = None
        self.started = time.monotonic()
        self.wall_end = self.started + wall_budget
        self.completed = False
        self.error = None
        self.stop_error = None
        self._pending = set()
        self._last_action = None
        self._repeat = 0

    def log(self, kind, **fields):
        if kind in ('tool_start', 'tool_result') and self.active_question:
            fields.setdefault('question_id', self.active_question)
        event = dict(kind=kind, episode=self.episode,
                     wall_elapsed=time.monotonic()-self.started,
                     sim_time=self.incident.now if self.incident else None, **fields)
        self.trace.append(event)
        self.emit(event)

    def escalate(self, reason):
        if self.incident and self.incident.state not in TERMINAL:
            self.incident._finish(State.UNKNOWN, self.incident.now, reason)
            self.log('terminal', state=self.incident.state.value, reason=reason)

    async def refresh(self):
        snapshot = await asyncio.wait_for(self.tools.snapshot(), timeout=5)
        now = snapshot['now']
        if not math.isfinite(now) or not snapshot['playing']:
            raise RuntimeError('simulation stopped or clock invalid')
        if self.incident:
            self.questions.advance(now)
            self.incident.tick(now)  # rejects reset/backwards clock
        return snapshot

    async def guarded(self, coroutine, timeout=None):
        """Check deadlines independently of planning/inference/tool completion."""
        task = asyncio.create_task(coroutine)
        self._pending.add(task)
        def settled(future):
            self._pending.discard(future)
            if not future.cancelled():
                future.exception()  # retrieve late errors even after the caller has stopped waiting
        task.add_done_callback(settled)
        end = min(self.wall_end, time.monotonic()+(self.operation_timeout if timeout is None else timeout))
        try:
            while True:
                await self.refresh()
                if self.incident.state in TERMINAL:
                    raise TimeoutError('incident simulation deadline')
                if time.monotonic() >= end:
                    raise TimeoutError('operation/wall deadline')
                if task.done():
                    return task.result()
                await asyncio.wait({task}, timeout=.1)
        finally:
            if not task.done():
                task.cancel()
                # A transport may suppress cancellation; never apply its late output.
                await asyncio.wait({task}, timeout=.05)

    def catalog(self):
        result = [dict(tool='observe', target=c, description='Capture and analyze a NEW frame')
                  for c in ('fixed', 'body')]
        result += [dict(tool='inspect', target=k, description=v['description'])
                   for k, v in self.tools.locations.items()
                   if k not in self.failed_targets and k != self.last_target
                   and not self.awaiting_body_observation]
        result += [dict(tool=k, target='', description=d) for k, d in (
            ('wait','Wait 2 simulation seconds then reconsider'),
            ('stop','Cancel motion and hold; does not close incident'),
            ('escalate','Local unresolved handoff; never a safe/danger assertion'))]
        if self._repeat >= 2:
            result = [x for x in result if (x['tool'], x['target']) != self._last_action]
        for item in result:
            item.update(question_ids=['presence', 'lying'],
                expected_evidence=('new image' if item['tool']=='observe' else
                    'new viewpoint; subsequent image required' if item['tool']=='inspect' else None),
                estimated_seconds=None,
                availability='host catalog; reachability not guaranteed')
        return result

    def context(self):
        i = self.incident
        return dict(goal='Resolve an observed person-loss incident with fresh evidence within budget.',
                    episode=self.episode, state=i.state.value,
                    remaining_sim_seconds=max(0, i.deadline-i.now),
                    remaining_wall_seconds=max(0, self.wall_end-time.monotonic()),
                    motion_status=i.motion_status, current_viewpoint=self.last_target,
                    required_next_evidence=('fresh body observation at the arrived viewpoint'
                        if self.awaiting_body_observation else None),
                    observations=self.memory[-8:],
                    recent_events=[e for e in self.trace if e['kind'] in ('tool_result','rejected','planner_error')][-8:],
                    available_tools=self.catalog(), context_graph=self.questions.planning())

    async def execute(self, action):
        tool, target = action['tool'], action['target']
        self.active_question = action['question_id']
        self.log('tool_start', action=action)
        if tool == 'observe':
            evidence, observation, record = await self.guarded(self.tools.observe(target, self.episode))
            now = self.incident.now
            valid = (evidence.episode == self.episode and evidence.generation == self.incident.generation
                     and evidence.subject == self.incident.subject
                     and math.isfinite(evidence.capture_time) and math.isfinite(evidence.received_time)
                     and self.incident.opened <= evidence.capture_time <= evidence.received_time <= now
                     and now-evidence.capture_time <= self.max_age
                     and evidence.id not in self.incident.seen_ids
                     and evidence.source == target
                     and evidence.capture_time > self.incident.latest_by_source.get(evidence.source, -math.inf))
            accepted = False
            if valid:
                self.questions.observe(evidence, observation, now)
                accepted = (self.questions.supports_danger() and
                            self.incident.accept(evidence, incident_decision(observation), now, self.max_age))
                # Observation memory never includes local file names, scenario labels or human truth.
                if target == 'body' and record['status'] == 'ok' and self.viewpoint_arrived_at is not None and evidence.capture_time > self.viewpoint_arrived_at:
                    self.awaiting_body_observation = False
                self.memory.append(dict(evidence_id=evidence.id, camera=target,
                    capture_time=evidence.capture_time, status=record['status'],
                    observation=asdict(observation)))
            self.evidence_records.append(dict(evidence=asdict(evidence), inference=record, valid=valid, accepted=accepted))
            self.log('tool_result', tool=tool, target=target, status=record['status'],
                     latency_wall_seconds=record.get('latency_wall_seconds'),
                     evidence_id=evidence.id, question_id=action['question_id'], valid=valid, accepted=accepted,
                     observation=asdict(observation) if valid else None)
        elif tool == 'inspect':
            attempt = self.incident.motion('moving', self.incident.now)
            self.last_target = None  # moving/failed motion is not the previous arrived viewpoint
            try:
                result = await self.guarded(self.tools.inspect(target), self.motion_timeout)
                status = result['status']
                if status not in ('arrived','failed','timed_out','cancelled'):
                    raise ValueError('invalid motion result')
                self.incident.motion(status, self.incident.now, attempt_id=attempt)
                if status == 'arrived':
                    self.last_target = target
                    self.awaiting_body_observation = True
                    self.viewpoint_arrived_at = self.incident.now
                else:
                    self.failed_targets.add(target)
                self.log('tool_result', tool=tool, target=target, status=status)
            except Exception:
                self.failed_targets.add(target)
                self.incident.motion('failed', self.incident.now, attempt_id=attempt)
                await asyncio.wait_for(self.tools.stop(), timeout=5)
                raise
        elif tool == 'wait':
            until = self.incident.now+2
            while self.incident.now < until and self.incident.state not in TERMINAL:
                if time.monotonic() >= self.wall_end:
                    raise TimeoutError('wall deadline')
                await asyncio.sleep(.1)
                await self.refresh()
            self.log('tool_result', tool=tool, target=target, status='waited')
        elif tool == 'stop':
            await self.guarded(self.tools.stop())
            self.incident.motion('cancelled', self.incident.now)
            self.last_target = None
            self.log('tool_result', tool=tool, target=target, status='stopped')
        elif tool == 'escalate':
            self.escalate('agent requested unresolved handoff: '+action['reason'])

    async def run(self, initial_observations=None):
        errors = 0
        try:
            snapshot = await self.refresh()
            self.incident = Incident(self.episode, snapshot['now'], snapshot['now']+self.budget)
            self.incident.tick(snapshot['now'])
            self.questions.advance(snapshot['now'])
            self.memory = list(initial_observations or [])
            self.log('opened', deadline=self.incident.deadline)
            for step in range(self.max_steps):
                await self.refresh()
                if self.incident.state in TERMINAL:
                    break
                if time.monotonic() >= self.wall_end:
                    self.escalate('wall budget exhausted');break
                state = self.context()
                self.log('planning', step=step, context=state)
                try:
                    action = await self.guarded(self.planner.choose(state))
                    validate_action(action, state['available_tools'])
                    binding_source = 'planner' if 'question_id' in action else 'host_legacy_fallback'
                    action = self.questions.bind(action)
                except TimeoutError as e:
                    self.log('planner_error', error=str(e));self.escalate(str(e));break
                except (ValueError, KeyError, TypeError, json.JSONDecodeError) as e:
                    errors += 1;self.log('rejected', error=str(e))
                    if errors >= 3:self.escalate('invalid planner output limit');break
                    continue
                self.log('decision', action=action, question_binding_source=binding_source)
                pair = (action['tool'], action['target'])
                self._repeat = self._repeat+1 if pair == self._last_action else 1
                self._last_action = pair
                try:
                    await self.execute(action)
                    errors = 0
                except TimeoutError as e:
                    errors += 1
                    self.log('tool_result', tool=action['tool'], target=action['target'], status='timeout')
                    if (self.incident.state in TERMINAL or time.monotonic() >= self.wall_end
                            or errors >= 3):
                        self.escalate(str(e));break
                    # A tool timeout is feedback for replanning while global budgets remain.
                except Exception as e:
                    errors += 1
                    self.log('tool_result', tool=action['tool'], target=action['target'],
                             status='error', error=type(e).__name__+': '+str(e))
                    if errors >= 3:self.escalate('tool failure limit');break
                if self.incident.state in TERMINAL:break
            if self.incident.state not in TERMINAL:self.escalate('step budget exhausted')
            self.completed = self.incident.state in TERMINAL
        except asyncio.CancelledError:
            self.error = 'cancelled';self.escalate('execution cancelled')
            raise
        except Exception as e:
            self.error = type(e).__name__+': '+str(e)
            self.log('aborted', error=self.error)
            self.escalate('execution aborted; unresolved')
        finally:
            for task in list(self._pending):task.cancel()
            try:await asyncio.wait_for(self.tools.stop(), timeout=5)
            except Exception as e:
                self.stop_error = str(e);self.completed = False
                self.log('stop_failed', error=self.stop_error)
            self.log('finished', state=self.incident.state.value if self.incident else None,
                     completed=self.completed, error=self.error)
        return self.report()

    def report(self):
        return dict(episode=self.episode, completed=self.completed, error=self.error,
                    agent_decisions=sum(e['kind']=='decision' for e in self.trace),
                    executed_tools=sum(e['kind']=='tool_start' for e in self.trace),
                    agent_cycle_exercised=any(e['kind']=='decision' for e in self.trace),
                    stop_error=self.stop_error, state=self.incident.state.value if self.incident else None,
                    incident_events=self.incident.events if self.incident else [],
                    trace=self.trace, observations=self.memory, evidence_records=self.evidence_records,
                    context_snapshot=self.questions.snapshot() if math.isfinite(self.questions.now) else None,
                    wall_seconds=time.monotonic()-self.started)
