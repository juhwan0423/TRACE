"""Deterministic tool-selection baselines for the unchanged evidence-gated Harness.

These planners only select public catalog entries. They neither interpret pixels nor
declare safe/danger, and must use the same tools, host closure rules and budgets as
the model planner. CameraOnlyPlanner is a bounded no-move reference, not a timed
escalation policy. Instantiate one planner per concurrent episode.
"""
from copy import deepcopy
import json
import time


class _PublicContextPlanner:
    def __init__(self, *, max_observations_per_view=2):
        if type(max_observations_per_view) is not int or max_observations_per_view < 1:
            raise ValueError('max_observations_per_view must be a positive integer')
        self.max_observations_per_view = max_observations_per_view
        self.records = []
        self._episode = None

    def _prepare(self, context):
        episode = context['episode']
        if not isinstance(episode, str) or not episode:
            raise ValueError('a nonempty public episode identifier is required')
        if episode != self._episode:
            self._episode = episode
            self._seen_results = set()
            self._attempts = {}
            self._visited = set()
            self._viewpoint = None
            self._initial_done = False
            self._pending = None

        completed_pending = self._pending is None
        for event in context.get('recent_events', []):
            if event.get('kind') != 'tool_result':
                continue
            # Harness timestamps distinguish calls, including duplicate frames or
            # failed calls. Re-exposing the same event never consumes budget twice.
            identity = json.dumps(event, sort_keys=True, separators=(',', ':'))
            if identity in self._seen_results:
                continue
            self._seen_results.add(identity)
            pair = (event.get('tool'), event.get('target'))
            if pair == self._pending:
                completed_pending = True
            if pair[0] == 'inspect':
                self._visited.add(pair[1])
                self._viewpoint = pair[1] if event.get('status') == 'arrived' else None
            elif pair[0] == 'observe':
                viewpoint = self._viewpoint or context.get('current_viewpoint')
                key = (pair[1], viewpoint if pair[1] == 'body' else 'fixed')
                self._attempts[key] = self._attempts.get(key, 0) + 1
        self._viewpoint = context.get('current_viewpoint')
        if completed_pending:
            self._pending = None
        return {(entry['tool'], entry['target']) for entry in context['available_tools']}

    def _attempt_count(self, camera):
        return self._attempts.get((camera, self._viewpoint if camera == 'body' else 'fixed'), 0)

    @staticmethod
    def _questions(context):
        return {q['id']: q for q in context.get('context_graph', {}).get('questions', [])}

    def _answered(self, context):
        questions = self._questions(context)
        return all(questions.get(q, {}).get('state') == 'resolved' for q in ('presence', 'lying'))

    def _action(self, context, available, tool, target, reason):
        if (tool, target) not in available:
            raise ValueError('comparison planner requires an available host tool: ' + tool)
        questions = self._questions(context)
        question_id = next((q for q in ('presence', 'lying')
                            if questions.get(q, {}).get('state') != 'resolved'), 'presence')
        refs = list(dict.fromkeys(o['evidence_id'] for o in context.get('observations', [])
                                 if isinstance(o.get('evidence_id'), str)))
        action = dict(tool=tool, target=target, reason=reason,
                      question_id=question_id, evidence_ids=refs)
        self._pending = (tool, target) if tool in ('inspect', 'observe') else None
        if tool == 'inspect':
            self._visited.add(target)
        return action

    def _handoff(self, context, available, reason):
        return self._action(context, available, 'escalate', '', reason)

    async def choose(self, context):
        started = time.monotonic()
        available = self._prepare(context)
        if self._pending is not None:
            action = self._handoff(context, available, 'No completed result for the previous tool; hand off unresolved uncertainty.')
        elif any(context.get(key, float('inf')) <= 0
                 for key in ('remaining_sim_seconds', 'remaining_wall_seconds')):
            action = self._handoff(context, available, 'The public remaining budget is exhausted; hand off unresolved uncertainty.')
        else:
            action = self._select(context, available)
        self.records.append(dict(policy=self.policy_id, episode=self._episode,
                                 action=deepcopy(action), raw_action=deepcopy(action),
                                 latency_wall_seconds=time.monotonic() - started))
        return action


class FixedOrderVerificationPlanner(_PublicContextPlanner):
    """Observe an initial camera, then visit each supplied viewpoint at most once.

    A viewpoint order is fixed before trials, never ranked from scene truth or
    camera interpretation. Each view gets up to max_observations_per_view new
    captures while observable questions remain unresolved and the host allows it.
    Failed/unavailable locations are skipped; failed post-arrival evidence cannot
    authorize another move against the host's required-next-evidence gate.
    """
    policy_id = 'fixed-order-verification/1'

    def __init__(self, viewpoints, *, initial_camera='fixed', max_observations_per_view=2):
        if isinstance(viewpoints, str):
            raise ValueError('viewpoints must be an ordered sequence, not a string')
        self.viewpoints = tuple(viewpoints)
        if any(not isinstance(v, str) or not v for v in self.viewpoints):
            raise ValueError('viewpoint identifiers must be nonempty strings')
        if len(set(self.viewpoints)) != len(self.viewpoints):
            raise ValueError('viewpoint order must not contain duplicates')
        if initial_camera not in ('fixed', 'body', None):
            raise ValueError('initial_camera must be fixed, body or None')
        self.initial_camera = initial_camera
        super().__init__(max_observations_per_view=max_observations_per_view)

    def _select(self, context, available):
        if context.get('required_next_evidence'):
            if (('observe', 'body') in available and
                    self._attempt_count('body') < self.max_observations_per_view):
                return self._action(context, available, 'observe', 'body',
                                    'Seek a fresh body-camera observation after arrival; arrival alone is not evidence.')
            return self._handoff(context, available,
                                 'Required fresh post-arrival evidence remains unavailable after the bounded attempts.')
        if self._answered(context):
            return self._handoff(context, available,
                                 'Observable questions are answered; the unchanged host determines the incident outcome.')
        if not self._initial_done:
            camera = self.initial_camera
            if (camera is not None and ('observe', camera) in available and
                    self._attempt_count(camera) < self.max_observations_per_view):
                return self._action(context, available, 'observe', camera,
                                    'Seek new evidence from the predefined initial camera within the fixed attempt budget.')
            self._initial_done = True
        if (self._viewpoint in self._visited and ('observe', 'body') in available and
                self._attempt_count('body') < self.max_observations_per_view):
            return self._action(context, available, 'observe', 'body',
                                'Use the remaining predefined camera attempt at this arrived viewpoint.')
        for target in self.viewpoints:
            if target not in self._visited and ('inspect', target) in available:
                return self._action(context, available, 'inspect', target,
                                    'Visit the next available viewpoint in the predefined order, then request new evidence.')
        return self._handoff(context, available,
                             'The predefined available views are exhausted; remaining uncertainty requires handoff.')


class CameraOnlyPlanner(_PublicContextPlanner):
    """Use a fixed number of fresh camera attempts at the unchanged initial pose.

    No fallback to another camera or movement is permitted. The same host may
    finish earlier on sufficient evidence. Otherwise this reference hands off.
    """
    policy_id = 'camera-only/1'

    def __init__(self, camera='fixed', *, max_observations_per_view=2):
        if camera not in ('fixed', 'body'):
            raise ValueError('camera must be fixed or body')
        self.camera = camera
        super().__init__(max_observations_per_view=max_observations_per_view)

    def _select(self, context, available):
        if self._answered(context):
            return self._handoff(context, available,
                                 'Observable questions are answered; the unchanged host determines the incident outcome.')
        if (('observe', self.camera) in available and
                self._attempt_count(self.camera) < self.max_observations_per_view):
            return self._action(context, available, 'observe', self.camera,
                                'Seek new evidence at the unchanged camera pose within the predefined attempt budget.')
        return self._handoff(context, available,
                             'The no-move camera attempts are exhausted or unavailable; hand off unresolved uncertainty.')
