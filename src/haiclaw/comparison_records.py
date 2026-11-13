"""Normalize Harness.report without looking at a scenario's ground truth.

Times are relative to the recorded incident opening. Wrapper measurements are
authoritative for elapsed model calls (including cancellation) and traveled
distance. Missing measurements remain missing; motion success is not distance.
"""
from __future__ import annotations

import math
from .observation_rules import RULE_VERSION, posture_limitations_block


def _finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _measurement(value, name):
    if value is None:
        return None
    if not _finite(value) or value < 0:
        raise ValueError(f"{name} must be finite and nonnegative")
    return float(value)


def _supporting_posture(evidence_id, report, payload, *, now, opened, max_age):
    if not _finite(now) or evidence_id in payload.get("revoked", []):
        return None
    entries = payload.get("evidence", {})
    entry = entries.get(evidence_id) if isinstance(entries, dict) else None
    if entry is None:
        for record in report.get("evidence_records", []):
            e = record.get("evidence", {})
            inference = record.get("inference", {})
            if e.get("id") == evidence_id and record.get("valid") is True and inference.get("status") == "ok":
                entry = dict(e, interpretation=inference.get("interpretation", {}))
                break
    if not entry:
        return None
    capture = entry.get("capture_time")
    received = entry.get("received_time")
    if not _finite(capture) or not _finite(received) or not capture <= received <= now:
        return None
    if _finite(opened) and capture < opened:
        return None
    expires = entry.get("expires_at")
    if not _finite(expires):
        if not _finite(max_age):
            return None
        expires = capture + max_age
    quality = entry.get("quality")
    if now >= expires or entry.get("reason") or not _finite(quality) or quality < .7:
        return None
    interpretation = entry.get("interpretation", {})
    limitations = interpretation.get("limitations", interpretation.get("observation_limitations", []))
    blocked = (posture_limitations_block(limitations) if payload.get('rule_version') == RULE_VERSION
               else bool(limitations))
    if (interpretation.get("person_visible") != "yes"
            or interpretation.get("needs_more_observation") is not False
            or blocked):
        return None
    return interpretation.get("posture")


def _inspection_answer(report, trace, opened):
    payload = (report.get("context_snapshot") or {}).get("payload", {})
    explicit = report.get("inspection_answer")
    questions = explicit if isinstance(explicit, dict) else payload.get("questions", {})
    source = "inspection_answer" if isinstance(explicit, dict) else "context_snapshot"
    presence, lying = questions.get("presence", {}), questions.get("lying", {})
    refs = list(lying.get("evidence_ids", []))
    answer_events = [e for e in trace if e.get("kind") == "inspection_answer" and _finite(e.get("sim_time"))]
    now = answer_events[-1]["sim_time"] if explicit and answer_events else payload.get("time")
    if not _finite(now):
        times = [e["sim_time"] for e in trace if _finite(e.get("sim_time"))]
        now = max(times) if times else None
    if (presence.get("state") != "resolved" or presence.get("value") is not True
            or lying.get("state") != "resolved" or not isinstance(lying.get("value"), bool)):
        return "unknown", source, refs, now, "question unresolved, conflicted or subject not established"
    if lying["value"] is True:
        # Preserve the host's explicit positive posture claim; its support and
        # correctness are assessed separately against external annotations.
        return "lying", source, refs, now, None
    max_age = payload.get("max_age", report.get("config", {}).get("max_evidence_age_seconds"))
    postures = [_supporting_posture(eid, report, payload, now=now, opened=opened, max_age=max_age) for eid in refs]
    if postures and all(posture == "standing" for posture in postures):
        return "standing", source, refs, now, None
    return "unknown", source, refs, now, "lying=false is not specifically standing; missing, stale or other posture support"


def normalize_report(report, *, trial_id, scenario_id, repetition_id, policy,
                     condition, timings=None, verification_level="unspecified",
                     status=None):
    """Convert one attempted Harness run into an evaluation record.

    ``timings`` accepts planner_latency_s, vision_latency_s, wall_latency_s,
    distance_m. Those quantities must be measured by the execution wrapper.
    ``status`` may explicitly mark a wrapper timeout/error (e.g. before the
    harness opened an incident). External truth is deliberately not accepted.
    """
    for name, value in (("trial_id", trial_id), ("scenario_id", scenario_id),
                        ("repetition_id", repetition_id), ("policy", policy),
                        ("condition", condition), ("verification_level", verification_level)):
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{name} must be a nonempty string")
    timings = dict(timings or {})
    allowed = {"planner_latency_s", "vision_latency_s", "wall_latency_s", "distance_m"}
    if set(timings) - allowed:
        raise ValueError("unknown wrapper timing fields: " + str(sorted(set(timings) - allowed)))
    trace = report.get("trace", [])
    opened_events = [e for e in trace if e.get("kind") == "opened"]
    if len(opened_events) > 1:
        raise ValueError("one normalized trial cannot contain multiple incident openings")
    opening = opened_events[0] if opened_events else {}
    origin = opening.get("sim_time")
    if origin is not None and not _finite(origin):
        raise ValueError("invalid opening simulation clock")
    deadline = opening.get("deadline")
    warnings = []
    if origin is None:
        warnings.append("incident opening absent; relative simulation times unavailable")
    def relative(value):
        if value is None or origin is None:
            return None
        if not _finite(value) or value < origin:
            raise ValueError("event timestamp precedes incident opening or is invalid")
        return float(value - origin)
    times = [e["sim_time"] for e in trace if _finite(e.get("sim_time"))]
    if times and any(b < a for a, b in zip(times, times[1:])):
        raise ValueError("nonmonotonic simulation timestamps in trial trace")
    end = max(times) if times else None
    events = report.get("incident_events", [])
    notifications = [e for e in events if e.get("local_alert") is True]
    if notifications and origin is None:
        raise ValueError("cannot normalize an alert without incident opening time")
    alert = min(notifications, key=lambda e: e["time"]) if notifications else None
    if alert:
        alert = dict(alert)
        for event in events:
            if event.get("alert_update") is True and event.get("time") == alert["time"]:
                alert["state"] = event.get("state")
    alert_kind = "none"
    if alert:
        alert_kind = {"danger_confirmed": "danger", "escalated_unknown": "unknown_handoff"}.get(alert.get("state"))
        if alert_kind is None:
            raise ValueError("local alert has an unsupported incident state")
    state = report.get("state")
    verdict = {"danger_confirmed": "danger", "resolved_safe": "safe"}.get(state, "unknown")
    terminal = [e for e in events if e.get("state") in {"danger_confirmed", "resolved_safe", "escalated_unknown"}]
    reason = str(terminal[-1].get("reason", "")) if terminal else ""
    reason_lower = reason.lower()
    resource_exhausted = any(x in reason_lower for x in ("budget", "deadline", "limit"))
    wall = _measurement(timings.get("wall_latency_s", report.get("wall_seconds")), "wall_latency_s")
    wall_budget = report.get("config", {}).get("wall_budget_seconds")
    sim_deadline = (verdict == "unknown" and _finite(deadline) and _finite(end) and end >= deadline)
    wall_deadline = (verdict == "unknown" and ("wall budget exhausted" in reason_lower
                     or _finite(wall_budget) and wall is not None and wall >= wall_budget))
    terminal_failure = any(x in reason_lower for x in (
        "invalid planner output limit", "tool failure limit", "execution aborted",
        "execution cancelled", "operation/wall deadline"))
    if status is None:
        if report.get("error") or report.get("stop_error"):
            status = "error"
        elif sim_deadline or wall_deadline:
            status = "timeout"
        elif terminal_failure:
            status = "error"
        elif report.get("completed") is True:
            status = "completed"
        else:
            status = "error"
    if status not in {"completed", "timeout", "error"}:
        raise ValueError("status must be completed, timeout or error")
    answer, source, refs, answer_time, note = _inspection_answer(report, trace, origin)
    if note:
        warnings.append(note)
    tool_count = report.get("executed_tools")
    starts = sum(e.get("kind") == "tool_start" for e in trace)
    if tool_count is not None and (isinstance(tool_count, bool) or not isinstance(tool_count, int) or tool_count < 0):
        raise ValueError("executed_tools must be a nonnegative integer")
    if tool_count is not None and tool_count != starts:
        warnings.append("executed_tools differs from available trace tool_start count")
    if tool_count is None:
        tool_count = starts if "trace" in report else None
    return dict(trial_id=trial_id, scenario_id=scenario_id, repetition_id=repetition_id,
                policy=policy, condition=condition, verification_level=verification_level,
                inspection_question_answer=answer, safety_verdict=verdict, status=status,
                alert_kind=alert_kind, alert_sim_s=relative(alert["time"]) if alert else None,
                end_sim_s=relative(end), tool_calls=tool_count,
                distance_m=_measurement(timings.get("distance_m"), "distance_m"),
                planner_latency_s=_measurement(timings.get("planner_latency_s"), "planner_latency_s"),
                vision_latency_s=_measurement(timings.get("vision_latency_s"), "vision_latency_s"),
                wall_latency_s=wall, sim_latency_s=relative(end),
                normalization=dict(sim_clock_origin_s=origin, relative_deadline_sim_s=relative(deadline),
                    answer_source=source, answer_evidence_ids=refs, answer_sim_s=relative(answer_time),
                    terminal_reason=reason, resource_exhausted=resource_exhausted,
                    sim_deadline_reached=sim_deadline, wall_deadline_reached=wall_deadline,
                    timing_source="wrapper; wall falls back to Harness.report wall_seconds", warnings=warnings,
                    no_ground_truth_used=True, standing_does_not_imply_safe=True))
