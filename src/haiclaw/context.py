"""Versioned question/evidence resolution. No model-authored closure rules."""
from copy import deepcopy
import hashlib
import json
import math

RULE_VERSION = 'trace-context/1'
TEMPLATES = {
    'presence': {'proposition': 'Is the subject visible in the monitored scope?',
                 'requires': ['fresh scoped observation', 'clear visibility',
                              'trusted complete coverage for absence']},
    'lying': {'proposition': 'Is the visible subject lying?',
              'requires': ['fresh scoped observation', 'visible subject', 'clear posture']},
}


class ContextGraph:
    def __init__(self, episode, subject='person-1', scope='work-area', max_age=45.):
        if not math.isfinite(max_age) or max_age <= 0:
            raise ValueError('positive finite max_age required')
        self.episode, self.subject, self.scope = episode, subject, scope
        self.max_age = max_age
        self.now = -math.inf
        self._evidence = {}
        self._revoked = set()
        self._questions = {}
        self._history = []
        for kind in TEMPLATES:
            self._questions[kind] = dict(id=kind, template=kind, **deepcopy(TEMPLATES[kind]),
                state='unresolved', value=None, evidence_ids=[])
        self._questions['risk'] = dict(id='risk', template='derived-visible-lying',
            proposition='Do current observations support visible lying?',
            dependencies=['presence', 'lying'], requires=['presence=true and lying=true'],
            state='unresolved', value=None, evidence_ids=[])

    def advance(self, now):
        if not math.isfinite(now) or now < self.now:
            raise ValueError('finite monotonic context clock required')
        self.now = now
        self._resolve('clock/evidence validity')

    def observe(self, evidence, observation, now, *, complete_coverage=False):
        """Coverage is a host/sensor assertion, never inferred from 'not visible'."""
        self.advance(now)
        e = evidence
        if (e.episode != self.episode or e.subject != self.subject or e.generation != 0
                or not all(math.isfinite(t) for t in (e.capture_time,e.received_time,e.quality))
                or not 0 <= e.quality <= 1
                or not e.capture_time <= e.received_time <= now
                or now-e.capture_time >= self.max_age
                or not e.source or not e.artifact
                or tuple(observation.evidence_ids) != (e.id,)):
            return False
        if e.id in self._evidence:
            return False
        # Preserve interpretation separately from the conditions that authorize it.
        claims = {}
        clear = (not observation.observation_limitations and not observation.needs_more_observation
                 and e.quality >= .7 and not e.reason)
        if clear and observation.person_visible == 'yes':
            claims['presence'] = True
            if observation.posture in ('lying', 'standing', 'seated'):
                claims['lying'] = observation.posture == 'lying'
        elif clear and observation.person_visible == 'no' and complete_coverage is True:
            claims['presence'] = False
        self._evidence[e.id] = dict(id=e.id, episode=e.episode, subject=e.subject,
            scope=self.scope, source=e.source, capture_time=e.capture_time,
            received_time=e.received_time, expires_at=e.capture_time+self.max_age,
            reference=e.artifact, quality=e.quality, reason=e.reason,
            interpretation=dict(needs_more_observation=observation.needs_more_observation,
                person_visible=observation.person_visible,
                posture=observation.posture, limitations=list(observation.observation_limitations)),
            complete_coverage=complete_coverage is True, claims=claims)
        self._resolve('observation '+e.id)
        return True

    def revoke(self, evidence_id, now):
        self.advance(now)
        if evidence_id not in self._evidence:
            raise KeyError(evidence_id)
        self._revoked.add(evidence_id)
        self._resolve('revoked '+evidence_id)

    def _resolve(self, reason):
        active = [e for e in self._evidence.values()
                  if e['id'] not in self._revoked and self.now < e['expires_at']]
        for kind in TEMPLATES:
            q = self._questions[kind]
            supports = [e for e in active if kind in e['claims']]
            values = {e['claims'][kind] for e in supports}
            state = 'conflicted' if len(values)>1 else 'resolved' if values else 'unresolved'
            self._update(q,state,next(iter(values)) if len(values)==1 else None,
                         sorted(e['id'] for e in supports),reason)
        p,l = self._questions['presence'],self._questions['lying']
        # A false/unknown posture is not evidence of industrial safety.
        state = ('conflicted' if 'conflicted' in (p['state'],l['state']) else
                 'resolved' if p['state']==l['state']=='resolved' and p['value'] and l['value'] else 'unresolved')
        self._update(self._questions['risk'],state,True if state=='resolved' else None,
                     sorted(set(p['evidence_ids']+l['evidence_ids'])),reason)

    def _update(self,q,state,value,refs,reason):
        before = (q['state'],q['value'],q['evidence_ids'])
        if before == (state,value,refs):
            return
        old = deepcopy(q)
        q.update(state=state,value=value,evidence_ids=refs)
        self._history.append(dict(time=self.now,question_id=q['id'],before=old,
            after=deepcopy(q),reason=reason,
            reopened=old['state']=='resolved' and state!='resolved'))

    def planning(self):
        return dict(rule_version=RULE_VERSION,scope=self.scope,subject=self.subject,
                    questions=deepcopy(list(self._questions.values())))

    def supports_danger(self):
        return self._questions['risk']['state'] == 'resolved'

    def bind(self, action):
        """Legacy callers get an explicit host-selected question, logged as such."""
        result = dict(action)
        qid = result.get('question_id')
        if qid is None:
            qid = next((k for k in TEMPLATES if self._questions[k]['state']!='resolved'), 'presence')
            result['question_id'] = qid
        if qid not in TEMPLATES:
            raise ValueError('action must address a registered observable question')
        return result

    def snapshot(self):
        payload = dict(schema_version=1,rule_version=RULE_VERSION,episode=self.episode,
            subject=self.subject,scope=self.scope,time=self.now,max_age=self.max_age,
            questions=deepcopy(self._questions),evidence=deepcopy(self._evidence),
            revoked=sorted(self._revoked),history=deepcopy(self._history))
        encoded=json.dumps(payload,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
        return dict(payload=payload,sha256=hashlib.sha256(encoded).hexdigest())
