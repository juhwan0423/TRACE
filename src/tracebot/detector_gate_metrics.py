"""Evaluation-only metrics for the same-agent detector-veto ablation.

Consumes normalized trial records and separately stored evaluation annotations.
There is no model, simulator, detector, or policy access here. Missing annotations
produce identification bounds, not an assumed zero failure rate. This supplements
comparison_metrics; it does not reinterpret the old development cohort.
"""
from __future__ import annotations

from collections import defaultdict
import math
from statistics import fmean


COST_FIELDS = (
    "wall_latency_s", "sim_latency_s", "distance_m", "tool_calls",
    "planner_latency_s", "vision_latency_s", "model_calls", "detector_calls",
    "detector_latency_s",
)


def _number(value, name):
    if value is None:
        return None
    if (isinstance(value, bool) or not isinstance(value, (float, int))
            or not math.isfinite(value) or value < 0):
        raise ValueError(f"{name} must be finite and nonnegative, or null")
    return float(value)


def _rate(values):
    known = [v for v in values if v is not None]
    total, positives = len(values), sum(known)
    unknown = total - len(known)
    return dict(
        value=positives / total if total and not unknown else None,
        numerator=positives, denominator=total, unknown=unknown,
        annotated_denominator=len(known),
        annotated_rate=positives / len(known) if known else None,
        identification_bounds=([positives / total, (positives + unknown) / total]
                               if total else None),
    )


def _and(*values):
    if False in values:
        return False
    return None if None in values else True


def _mean(values):
    measured = [value for value in values if value is not None]
    return dict(value=fmean(measured) if measured else None,
                measured_trials=len(measured), total_trials=len(values),
                missing_trials=len(values) - len(measured))


def _prepare(record, truth, annotation):
    row = dict(record)
    for key in ("trial_id", "policy", "scenario_id", "repetition_id"):
        if not isinstance(row.get(key), str) or not row[key].strip():
            raise ValueError(f"{key} must be a nonempty string")
    answer = row.get("inspection_question_answer")
    if answer not in {"standing", "lying", "unknown"}:
        raise ValueError("invalid inspection_question_answer")
    if row.get("status") not in {"completed", "timeout", "error"}:
        raise ValueError("invalid status")
    actual = truth.get("actual_posture")
    if actual not in {"standing", "lying"}:
        raise ValueError("external actual_posture must be standing or lying")
    answerable = truth.get("answerable")
    if answerable is not None and type(answerable) is not bool:
        raise ValueError("external answerable must be boolean or null")
    role = truth.get("evaluation_role", "development")
    if role not in {"development", "confirmatory"}:
        raise ValueError("invalid evaluation_role")
    deadline = _number(truth.get("deadline_sim_s"), "deadline_sim_s")
    wall_budget = _number(truth.get("wall_budget_s"), "wall_budget_s")
    if deadline is None or wall_budget is None:
        raise ValueError("both relative sim deadline and wall budget are required")
    claim = answer != "unknown"
    normalization = row.get("normalization") or {}
    refs = normalization.get("answer_evidence_ids", [])
    if not isinstance(refs, list) or any(not isinstance(x, str) or not x for x in refs):
        raise ValueError("answer_evidence_ids must be a list of nonempty strings")
    if len(set(refs)) != len(refs):
        raise ValueError("duplicate answer_evidence_ids")
    support = dict(annotation or {})
    if annotation is not None:
        annotated_refs = support.get("evidence_ids")
        if (not isinstance(annotated_refs, list)
                or any(not isinstance(x, str) or not x for x in annotated_refs)
                or len(set(annotated_refs)) != len(annotated_refs)
                or set(annotated_refs) != set(refs)):
            raise ValueError("annotation evidence_ids must exactly match claimed evidence")
    present = support.get("claim_target_present")
    if present is not None and not isinstance(present, bool):
        raise ValueError("claim_target_present must be boolean or null")
    visible_posture = support.get("claim_observed_posture")
    if visible_posture not in {"standing", "lying", "unreadable", None}:
        raise ValueError("invalid independent RGB posture annotation")
    if present is False and visible_posture in {"standing", "lying"}:
        raise ValueError("target-absent label conflicts with readable target posture")
    # A claim without any cited frame has no auditable support, even if its
    # label happens to match simulator truth. This is not missing annotation.
    if claim and not refs:
        present, visible_posture = False, "unreadable"
    sim_time = _number(normalization.get("answer_sim_s"), "answer_sim_s")
    # Legacy records do not have answer wall time. End-to-end wall duration is
    # a conservative upper bound; preserve which measurement was used.
    explicit_wall = row.get("answer_wall_s")
    wall_time = _number(explicit_wall if explicit_wall is not None else row.get("wall_latency_s"),
                        "answer_wall_s or wall_latency_s")
    timely = _and(sim_time <= deadline if sim_time is not None else None,
                  wall_time <= wall_budget if wall_time is not None else None)
    grounded = _and(present, visible_posture == answer if visible_posture is not None else None)
    resolution = _and(claim, row["status"] == "completed", answer == actual, timely, grounded)
    absent_assertion = _and(claim, not present if present is not None else None)
    completed_handoff = (answer == "unknown" and row.get("alert_kind") == "unknown_handoff"
                         and row["status"] == "completed")
    handoff_sim = _number(row.get("alert_sim_s"), "alert_sim_s")
    explicit_handoff_wall = row.get("alert_wall_s")
    handoff_wall = _number(explicit_handoff_wall if explicit_handoff_wall is not None
                           else row.get("wall_latency_s"), "alert_wall_s or wall_latency_s")
    handoff_timely = _and(handoff_sim <= deadline if handoff_sim is not None else None,
                          handoff_wall <= wall_budget if handoff_wall is not None else None)
    gate_cost = row.get("person_gate_cost") or {}
    if not isinstance(gate_cost, dict):
        raise ValueError("person_gate_cost must be an object")
    for field, nested in (("detector_calls", "calls"), ("detector_latency_s", "latency_wall_seconds")):
        if row.get(field) is None:
            row[field] = gate_cost.get(nested)
        elif gate_cost.get(nested) is not None and row[field] != gate_cost[nested]:
            raise ValueError(f"{field} disagrees with person_gate_cost.{nested}")
    for field in COST_FIELDS:
        row[field] = _number(row.get(field), field)
        if field.endswith("calls") and row[field] is not None and not row[field].is_integer():
            raise ValueError(f"{field} must be an integer count")
    row.update(
        evaluation_role=role, verification_level=row.get("verification_level", "unspecified"),
        claim=claim, presence_unsupported=absent_assertion, grounded_correct=resolution,
        annotation_present=present, annotation_posture=visible_posture,
        answer_wall_source="answer_wall_s" if explicit_wall is not None else "end_wall_upper_bound",
        actual_posture=actual, answerable=answerable, deadline_sim_s=deadline, wall_budget_s=wall_budget,
        completed_unknown_handoff=completed_handoff,
        completed_unknown_handoff_within_budget=_and(completed_handoff, handoff_timely),
        handoff_sim_s=handoff_sim, handoff_wall_s=handoff_wall,
        handoff_wall_source="alert_wall_s" if explicit_handoff_wall is not None else "end_wall_upper_bound",
    )
    return row


def _summarize_arm(arm):
    handoffs = [row for row in arm if row["completed_unknown_handoff"]]
    return dict(
        trials=len(arm), assertions=sum(r["claim"] for r in arm),
        presence_unsupported_assertion_risk=_rate([r["presence_unsupported"] for r in arm]),
        presence_unsupported_given_assertion=_rate([r["presence_unsupported"] for r in arm if r["claim"]]),
        grounded_correct_within_budget_rate=_rate([r["grounded_correct"] for r in arm]),
        unresolved_rate=_rate([r["inspection_question_answer"] == "unknown" or r["status"] != "completed" for r in arm]),
        timeout_rate=_rate([r["status"] == "timeout" for r in arm]),
        error_rate=_rate([r["status"] == "error" for r in arm]),
        error_or_timeout_rate=_rate([r["status"] in {"error", "timeout"} for r in arm]),
        # Retain this legacy event-frequency field. It does NOT credit a
        # successful or appropriate handoff; strict completion is separate.
        unknown_handoff_rate=_rate([r.get("alert_kind") == "unknown_handoff" for r in arm]),
        completed_unknown_handoff_rate=_rate([r["completed_unknown_handoff"] for r in arm]),
        completed_unknown_handoff_within_budget_rate=_rate([r["completed_unknown_handoff_within_budget"] for r in arm]),
        completed_unknown_handoff_latency=dict(
            eligible_trials=len(handoffs), all_attempted_trials=len(arm),
            sim_s=_mean([r["handoff_sim_s"] for r in handoffs]),
            wall_s=_mean([r["handoff_wall_s"] for r in handoffs]),
            wall_upper_bound_trials=sum(r["handoff_wall_source"] == "end_wall_upper_bound" for r in handoffs)),
        costs={field: _mean([r[field] for r in arm]) for field in COST_FIELDS},
        answer_wall_upper_bound_trials=sum(r["answer_wall_source"] == "end_wall_upper_bound" for r in arm),
    )


def evaluate_gate(records, external_truth, support_annotations, *, expected_trial_ids=None):
    """Return separate development/verification strata; never call this online.

    ``external_truth[trial_id]``: actual_posture, deadline_sim_s (relative to
    incident opening), wall_budget_s, optional evaluation_role and answerable
    (boolean/null). Missing answerability belongs to an explicit unknown group.
    ``support_annotations[trial_id]``: evidence_ids; claim_target_present
    (bool/null from external target-instance visibility); claim_observed_posture
    (standing/lying/unreadable/null from independent RGB review).
    Nested ``person_gate_cost.calls/latency_wall_seconds`` are accepted aliases
    for detector_calls/detector_latency_s from the live execution wrapper.

    Rates use ALL attempted trials. Null/uncertain annotations are explicit in
    both point-estimate availability and lower/upper identification bounds.
    A secondary assertion-conditional metric never replaces the all-trial risk.
    The existing comparison_metrics evaluator remains the pairing/CI facility;
    this supplement intentionally does not invent CIs from frame-level labels.
    Handoff success requires an unknown answer, an unknown_handoff alert AND
    completed execution. Unknown answers alone are not handoffs. A completed
    handoff is correct only in the externally designated unanswerable group and
    within both relative sim and wall deadlines. Missing times remain unknown.
    """
    rows, seen = [], set()
    for record in records:
        trial_id = record.get("trial_id")
        if trial_id in seen:
            raise ValueError("duplicate trial_id")
        if trial_id not in external_truth:
            raise ValueError(f"missing external truth for {trial_id}")
        seen.add(trial_id)
        rows.append(_prepare(record, external_truth[trial_id], support_annotations.get(trial_id)))
    expected = set(expected_trial_ids) if expected_trial_ids is not None else None
    if expected is not None and seen - expected:
        raise ValueError("records contain trials outside the frozen manifest")
    groups = defaultdict(list)
    for row in rows:
        groups[(row["evaluation_role"], row["verification_level"])].append(row)
    strata = []
    for (role, level), group in sorted(groups.items()):
        policies = {}
        for policy in sorted({r["policy"] for r in group}):
            arm = [r for r in group if r["policy"] == policy]
            summary = _summarize_arm(arm)
            summary["by_actual_posture"] = {
                posture: _summarize_arm([r for r in arm if r["actual_posture"] == posture])
                for posture in ("standing", "lying")}
            summary["by_answerability"] = {
                label: _summarize_arm([r for r in arm if r["answerable"] is value])
                for label, value in (("true", True), ("false", False), ("unknown", None))}
            unanswerable = [r for r in arm if r["answerable"] is False]
            summary["by_answerability"]["false"].update(
                correct_unknown_handoff_rate=_rate([
                    r["completed_unknown_handoff_within_budget"] for r in unanswerable]),
                correct_unknown_handoff_within_budget_rate=_rate([
                    r["completed_unknown_handoff_within_budget"] for r in unanswerable]),
                inappropriate_posture_assertion_rate=_rate([r["claim"] for r in unanswerable]))
            policies[policy] = summary
        strata.append(dict(evaluation_role=role, verification_level=level, policies=policies))
    return dict(
        schema="detector_gate_metrics_v1", strata=strata,
        manifest_checked=expected is not None,
        missing_trial_ids=sorted(expected - seen) if expected is not None else None,
        all_manifest_trials_recorded=(seen == expected) if expected is not None else None,
        unused_annotation_ids=sorted(set(support_annotations) - seen),
        notes=["Presence support does not establish posture readability or overall safety.",
               "Identification bounds describe missing labels, not confidence intervals.",
               "Costs include attempted trials; missing measurements are not zero.",
               "Missing answerability is unknown, never inferred as unanswerable.",
               "unknown_handoff_rate is legacy alert frequency, not successful handoff.",
               "Completed handoffs require unknown answer, unknown_handoff alert, and completed execution.",
               "Correct handoff requires an unanswerable case and completion within both clock budgets; missing times remain unknown.",
               "Handoff latency is conditional on completed handoffs; end wall time is marked as an upper bound.",
               "This supplement does not compute paired effects or statistical significance."],
    )
