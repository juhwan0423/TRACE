"""Evaluation-only paired-policy metrics from external trial annotations.

No simulator state or ground truth is sent to a policy. ``evaluate`` takes a
sequence of normalized records and a separate mapping ``trial_id -> truth``.
See reports/COMPARISON_METRICS.md for the schema and denominator definitions.
Only the standard library is required; this module performs no model calls.
"""
from __future__ import annotations

from collections import defaultdict
from itertools import combinations
import math
import random
from statistics import fmean


ANSWERS = {"lying", "standing", "unknown"}
STATUSES = {"completed", "timeout", "error"}
VERDICTS = {"danger", "safe", "unknown"}
ALERT_KINDS = {"danger", "unknown_handoff", "none"}
COST_FIELDS = (
    "tool_calls", "distance_m", "planner_latency_s", "vision_latency_s",
    "wall_latency_s", "sim_latency_s",
)
RATE_METRICS = (
    "answerable_resolution_rate", "expected_response_correct_rate",
    "false_assertion_unanswerable_rate", "incorrect_posture_assertion_rate",
    "unsupported_posture_assertion_rate", "unresolved_rate",
    "safety_unresolved_rate", "timeout_rate", "error_rate",
    "dangerous_case_miss_rate", "dangerous_case_unconfirmed_rate",
    "dangerous_case_wrong_safe_closure_rate", "unsupported_safe_closure_rate",
    "false_alert_rate", "false_danger_alert_rate", "unknown_handoff_rate",
    "deadline_overrun_rate",
)
LATENCY_METRICS = (
    "danger_alert_latency_from_onset_s",
    "danger_alert_latency_from_discernible_s",
    "danger_alert_latency_capped_at_deadline_s",
)
METRICS = RATE_METRICS + COST_FIELDS + LATENCY_METRICS


def _number(value, name, *, optional=False, nonnegative=True):
    if value is None and optional:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a finite number")
    value = float(value)
    if not math.isfinite(value) or (nonnegative and value < 0):
        raise ValueError(f"{name} must be finite and nonnegative")
    return value


def _boolean(value, name, *, optional=False):
    if value is None and optional:
        return None
    if not isinstance(value, bool):
        raise ValueError(f"{name} must be an explicit boolean")
    return value


def _name(value, name):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a nonempty string")
    return value


def _prepare(record, external_truth):
    r = dict(record)
    t = dict(external_truth)
    for key in ("trial_id", "scenario_id", "repetition_id", "policy"):
        r[key] = _name(r.get(key), key)
    # Conditions are evaluation annotations, never inferred from an answer.
    r["condition"] = _name(t.get("condition"), "truth.condition")
    r["verification_level"] = _name(r.get("verification_level", "unspecified"), "verification_level")
    r["evaluation_role"] = t.get("evaluation_role", "development")
    if r["evaluation_role"] not in {"development", "confirmatory"}:
        raise ValueError("truth.evaluation_role must be development or confirmatory")
    legacy = t.get("posture_label")
    actual = t.get("actual_posture", legacy if legacy in {"lying", "standing"} else None)
    if actual not in {"lying", "standing"} and not (legacy == "unobservable" and actual is None):
        raise ValueError("truth.actual_posture must be lying or standing")
    answerable = _boolean(t.get("answerable", legacy != "unobservable" if legacy else None), "truth.answerable")
    expected = actual if answerable else "unknown"
    if expected is None or t.get("expected_answer", expected) != expected:
        raise ValueError("truth.expected_answer disagrees with actual_posture/answerable")
    t.update(actual_posture=actual, answerable=answerable, expected_answer=expected)
    t["dangerous"] = _boolean(t.get("dangerous"), "truth.dangerous")
    t["assertion_supported"] = _boolean(t.get("assertion_supported"), "truth.assertion_supported", optional=True)
    t["safe_closure_supported"] = _boolean(t.get("safe_closure_supported"), "truth.safe_closure_supported", optional=True)
    start = _number(t.get("incident_start_sim_s"), "truth.incident_start_sim_s")
    deadline = _number(t.get("deadline_sim_s"), "truth.deadline_sim_s")
    if deadline < start:
        raise ValueError("deadline precedes incident start")
    onset = _number(t.get("danger_onset_sim_s"), "truth.danger_onset_sim_s", optional=True)
    discernible = _number(t.get("discernible_observation_sim_s"), "truth.discernible_observation_sim_s", optional=True)
    if onset is not None and not start <= onset <= deadline:
        raise ValueError("danger onset must be inside the incident deadline interval")
    if discernible is not None and discernible < start:
        raise ValueError("discernible observation precedes incident start")
    t.update(incident_start_sim_s=start, deadline_sim_s=deadline,
             danger_onset_sim_s=onset, discernible_observation_sim_s=discernible)
    answer = r.get("inspection_question_answer", "unknown")
    if answer == "unobservable":
        answer = "unknown"  # Live adapter does not establish complete invisibility.
    if answer not in ANSWERS or r.get("status") not in STATUSES:
        raise ValueError("invalid inspection answer or trial status")
    r["inspection_question_answer"] = answer
    if r.get("safety_verdict", "unknown") not in VERDICTS:
        raise ValueError("invalid safety verdict")
    r.setdefault("safety_verdict", "unknown")
    r.setdefault("alert_kind", "none")
    if r["alert_kind"] not in ALERT_KINDS:
        raise ValueError("invalid alert_kind")
    alert = _number(r.get("alert_sim_s"), "alert_sim_s", optional=True)
    end = _number(r.get("end_sim_s"), "end_sim_s", optional=True)
    if (alert is None) != (r["alert_kind"] == "none"):
        raise ValueError("alert_kind and alert_sim_s must agree")
    if alert is not None and alert < start:
        raise ValueError("alert precedes incident start")
    if end is not None and (end < start or alert is not None and alert > end):
        raise ValueError("end_sim_s precedes incident or alert")
    r.update(alert_sim_s=alert, end_sim_s=end)
    for key in COST_FIELDS:
        r[key] = _number(r.get(key), key, optional=True)
    if r["tool_calls"] is not None and not r["tool_calls"].is_integer():
        raise ValueError("tool_calls must be an integer count")
    r["truth"] = t
    return r


def _values(r):
    t = r["truth"]
    answer = r["inspection_question_answer"]
    claim = answer in {"lying", "standing"}
    completed = r["status"] == "completed"
    safe = r["safety_verdict"] == "safe"
    dangerous = t["dangerous"]
    alert = r["alert_sim_s"]
    start, deadline, onset = (t[k] for k in ("incident_start_sim_s", "deadline_sim_s", "danger_onset_sim_s"))
    # An unknown handoff is a notification, but never danger confirmation.
    response_start = onset if onset is not None else start
    timely = alert is not None and response_start <= alert <= deadline
    confirmed = timely and r["alert_kind"] == "danger" and r["safety_verdict"] == "danger"
    supported = t["assertion_supported"]
    safe_supported = t["safe_closure_supported"]
    v = {
        "answerable_resolution_rate": float(completed and answer == t["actual_posture"]) if t["answerable"] else None,
        "expected_response_correct_rate": float(completed and answer == t["expected_answer"]),
        "false_assertion_unanswerable_rate": float(claim) if not t["answerable"] else None,
        "incorrect_posture_assertion_rate": float(claim and answer != t["actual_posture"]) if t["actual_posture"] is not None else None,
        "unsupported_posture_assertion_rate": float(claim and not supported) if not claim or supported is not None else None,
        "unresolved_rate": float(not completed or answer == "unknown"),
        "safety_unresolved_rate": float(r["safety_verdict"] == "unknown"),
        "timeout_rate": float(r["status"] == "timeout"),
        "error_rate": float(r["status"] == "error"),
        "dangerous_case_miss_rate": float(not timely) if dangerous else None,
        "dangerous_case_unconfirmed_rate": float(not confirmed) if dangerous else None,
        "dangerous_case_wrong_safe_closure_rate": float(safe) if dangerous else None,
        "unsupported_safe_closure_rate": float(safe and not safe_supported) if not safe or safe_supported is not None else None,
        "false_alert_rate": float(alert is not None) if not dangerous else None,
        "false_danger_alert_rate": float(r["alert_kind"] == "danger") if not dangerous else None,
        "unknown_handoff_rate": float(r["alert_kind"] == "unknown_handoff"),
        "deadline_overrun_rate": float(r["end_sim_s"] > deadline) if r["end_sim_s"] is not None else None,
    }
    v.update({key: r[key] for key in COST_FIELDS})
    # Success-only observed latencies are explicitly accompanied by miss rates.
    event = dangerous and r["alert_kind"] == "danger" and alert is not None and alert >= response_start
    v["danger_alert_latency_from_onset_s"] = alert - onset if event and onset is not None else None
    disc = t["discernible_observation_sim_s"]
    v["danger_alert_latency_from_discernible_s"] = alert - disc if event and disc is not None else None
    # Non-notified/late cases get the full remaining deadline horizon; this is
    # a capped response cost, NOT an observed latency or a survival estimator.
    capped = None
    if dangerous and onset is not None:
        capped = deadline - onset
        if event:
            capped = min(alert - onset, capped)
    v["danger_alert_latency_capped_at_deadline_s"] = capped
    return v


def _aggregate(rows):
    values = [_values(r) for r in rows]
    metrics = {}
    for key in METRICS:
        observed = [v[key] for v in values if v[key] is not None]
        metric = dict(value=fmean(observed) if observed else None,
                      denominator=len(observed), missing_or_ineligible=len(rows) - len(observed))
        if key in RATE_METRICS:
            metric["numerator"] = int(sum(observed))
        else:
            metric["minimum"] = min(observed) if observed else None
            metric["maximum"] = max(observed) if observed else None
        metrics[key] = metric
    claims = [r for r in rows if r["inspection_question_answer"] in {"lying", "standing"}]
    return dict(trials=len(rows), independent_scenarios=len({r["scenario_id"] for r in rows}),
                answerable_trials=sum(r["truth"]["answerable"] for r in rows),
                unanswerable_trials=sum(not r["truth"]["answerable"] for r in rows),
                dangerous_trials=sum(r["truth"]["dangerous"] for r in rows),
                posture_assertions=len(claims),
                assertions_with_unknown_support=sum(r["truth"]["assertion_supported"] is None for r in claims),
                metrics=metrics)


def _quantile(values, q):
    values = sorted(values)
    index = (len(values) - 1) * q
    lo = int(index)
    hi = min(lo + 1, len(values) - 1)
    return values[lo] + (values[hi] - values[lo]) * (index - lo)


def _paired(rows, policy_a, policy_b, samples, seed):
    by_policy = {p: {} for p in (policy_a, policy_b)}
    for r in rows:
        if r["policy"] in by_policy:
            by_policy[r["policy"]][(r["scenario_id"], r["repetition_id"])] = r
    aa, bb = by_policy[policy_a], by_policy[policy_b]
    common = sorted(aa.keys() & bb.keys())
    for key in common:
        a, b = aa[key], bb[key]
        for field in ("actual_posture", "answerable", "dangerous", "incident_start_sim_s", "deadline_sim_s", "danger_onset_sim_s"):
            if a["truth"][field] != b["truth"][field]:
                raise ValueError(f"paired external truth differs for {key}: {field}")
        if a["condition"] != b["condition"]:
            raise ValueError(f"paired condition differs for {key}")
    results = {}
    for metric in METRICS:
        clustered = defaultdict(list)
        n = 0
        for key in common:
            a, b = _values(aa[key])[metric], _values(bb[key])[metric]
            if a is not None and b is not None:
                clustered[key[0]].append(b - a)
                n += 1
        # Equal scenario weighting; repetitions only refine a scenario's mean.
        differences = [fmean(clustered[k]) for k in sorted(clustered)]
        estimate = fmean(differences) if differences else None
        interval = None
        if len(differences) >= 2 and samples:
            rng = random.Random(seed)
            draws = [fmean(rng.choices(differences, k=len(differences))) for _ in range(samples)]
            interval = [_quantile(draws, .025), _quantile(draws, .975)]
        results[metric] = dict(difference_b_minus_a=estimate, paired_trials=n,
                               independent_scenarios=len(differences), bootstrap_95_interval=interval,
                               interval_available=interval is not None)
    def missing(keys, present):
        return [dict(scenario_id=s, repetition_id=r, present_policy=present) for s, r in sorted(keys)]
    return dict(policy_a=policy_a, policy_b=policy_b, matched_trial_pairs=len(common),
                missing_policy_b=missing(aa.keys() - bb.keys(), policy_a),
                missing_policy_a=missing(bb.keys() - aa.keys(), policy_b),
                all_trials_paired=aa.keys() == bb.keys(), metrics=results)


def evaluate(records, ground_truth, *, bootstrap_samples=2000, seed=20261107,
             expected_policies=None):
    """Return JSON-serializable summaries and paired scenario bootstrap results.

    Failed and timed-out records are retained. Missing policy records are listed,
    never silently manufactured or discarded from per-policy summaries. Bootstrap
    intervals use matched pairs only and are withheld with fewer than two
    independent scenarios. Development and confirmatory records, and distinct
    verification levels, are never pooled.
    """
    if isinstance(bootstrap_samples, bool) or not isinstance(bootstrap_samples, int) or bootstrap_samples < 0:
        raise ValueError("bootstrap_samples must be a nonnegative integer")
    if expected_policies is not None:
        expected_policies = list(expected_policies)
        if len(set(expected_policies)) != len(expected_policies) or not expected_policies:
            raise ValueError("expected_policies must contain unique policy names")
        for policy in expected_policies:
            _name(policy, "expected policy")
    prepared = []
    seen_ids, seen_pair_keys = set(), set()
    for raw in records:
        trial_id = raw.get("trial_id")
        if trial_id in seen_ids:
            raise ValueError(f"duplicate trial_id: {trial_id}")
        if trial_id not in ground_truth:
            raise ValueError(f"missing external ground truth: {trial_id}")
        r = _prepare(raw, ground_truth[trial_id])
        if expected_policies is not None and r["policy"] not in expected_policies:
            raise ValueError(f"unexpected policy: {r['policy']}")
        key = (r["evaluation_role"], r["verification_level"], r["policy"], r["scenario_id"], r["repetition_id"])
        if key in seen_pair_keys:
            raise ValueError(f"duplicate policy/scenario/repetition: {key}")
        seen_ids.add(trial_id)
        seen_pair_keys.add(key)
        prepared.append(r)
    strata = defaultdict(list)
    for r in prepared:
        strata[(r["evaluation_role"], r["verification_level"])].append(r)
    policies = sorted(expected_policies if expected_policies is not None else {r["policy"] for r in prepared})
    output = []
    for (role, level), rows in sorted(strata.items()):
        summaries = {p: _aggregate([r for r in rows if r["policy"] == p]) for p in policies}
        conditions = {}
        for condition in sorted({r["condition"] for r in rows}):
            subset = [r for r in rows if r["condition"] == condition]
            conditions[condition] = {
                "policies": {p: _aggregate([r for r in subset if r["policy"] == p]) for p in policies},
                "paired": [_paired(subset, a, b, bootstrap_samples, seed) for a, b in combinations(policies, 2)],
            }
        output.append(dict(evaluation_role=role, verification_level=level, policies=summaries,
                           by_condition=conditions,
                           paired=[_paired(rows, a, b, bootstrap_samples, seed) for a, b in combinations(policies, 2)]))
    complete = bool(prepared) and len(policies) >= 2 and all(
        pair["all_trials_paired"] for stratum in output for pair in stratum["paired"])
    return dict(schema_version=1, records=len(prepared), strata=output,
                expected_policies=policies, comparison_complete=complete,
                unused_ground_truth_ids=sorted(set(ground_truth) - seen_ids),
                bootstrap=dict(samples=bootstrap_samples, seed=seed, unit="independent scenario_id",
                               estimand="mean across scenarios of within-scenario paired repetition differences (B minus A)",
                               missing_pairs="listed; retained in policy summaries, excluded only from paired estimates"),
                interpretation={
                    "standing_is_not_safe": True,
                    "unknown_and_failures_remain_in_denominators": True,
                    "unanswerable_abstention_can_be_expected_correct_but_is_unresolved": True,
                    "unsupported_assertions_require_external_support_annotation": True,
                    "observed_alert_latency_is_not_a_miss_penalty": True,
                    "capped_latency_is_deadline_capped_cost_not_observed_or_survival_estimate": True,
                    "negative_discernible_latency_means_alert_preceded_annotated_observation": True,
                    "development_results_are_not_confirmatory": True,
                })
