"""Audit saved component failures independently of frozen outcome evaluation.

Only recorded result.json data is inspected. No model, simulator or evaluator is
called. Raw responses and thinking text are never copied to output; only parsing
flags, safe metadata, lengths and numeric timing are retained.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path


FIELDS = {"person_visible", "posture", "visible_risk_cues", "observation_limitations",
          "needs_more_observation", "evidence_ids"}


def finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def numeric(value):
    return value if finite(value) else None


def error_code(value):
    """Do not copy free-form exceptions, which may embed provider content."""
    if not isinstance(value, str):
        return "unrecorded"
    prefix = value.split(":", 1)[0]
    allowed = {"ok", "timeout", "cancelled", "error", "failed", "arrived", "timed_out"}
    if prefix in allowed:
        return prefix
    if prefix.isidentifier() and (prefix.endswith("Error") or prefix.endswith("Exception")):
        return prefix[:80]
    return "other_error"


def schema_issues(obj, evidence_id):
    if not isinstance(obj, dict):
        return ["final_json_not_object"]
    issues = []
    if set(obj) != FIELDS:
        issues.append("schema_keys_mismatch")
    if obj.get("person_visible") not in ("yes", "no", "uncertain"):
        issues.append("person_visible_enum")
    if obj.get("posture") not in ("standing", "seated", "lying", "unknown"):
        issues.append("posture_enum")
    if type(obj.get("needs_more_observation")) is not bool:
        issues.append("needs_more_observation_type")
    if evidence_id is not None and obj.get("evidence_ids") != [evidence_id]:
        issues.append("evidence_binding")
    elif evidence_id is None:
        issues.append("evidence_binding_unverifiable")
    for key in ("visible_risk_cues", "observation_limitations"):
        values = obj.get(key)
        if not isinstance(values, list) or len(values) > 20 or any(not isinstance(v, str) or len(v) > 500 for v in values):
            issues.append(key + "_type_or_bound")
    if obj.get("person_visible") != "yes" and obj.get("posture") != "unknown":
        issues.append("posture_without_visible_person")
    return issues


def response_metadata(raw, provider_status, evidence_id, *, vision=True):
    result = dict(provider_status_code=error_code(provider_status), response_recorded=raw is not None,
                  raw_response_chars=len(raw) if isinstance(raw, str) else None,
                  outer_json_valid=None, final_content_chars=None, thinking_chars=None,
                  empty_final_content=None, final_json_valid=None, schema_status="not_evaluated",
                  schema_issue_codes=[], done_reason=None, eval_count=None, eval_count_equals_4096=None,
                  length_stop_at_4096=None, transport_status="no_response_recorded")
    if raw is None:
        if provider_status in ("timeout", "cancelled"):
            result["transport_status"] = "provider_" + provider_status
        return result
    result["transport_status"] = "response_received"
    try:
        envelope = json.loads(raw) if isinstance(raw, str) else raw
        result["outer_json_valid"] = True
    except (json.JSONDecodeError, TypeError):
        result["outer_json_valid"] = False
        result["schema_status"] = "invalid_outer_json"
        return result
    if not isinstance(envelope, dict):
        result["schema_status"] = "invalid_outer_envelope"
        return result
    if "error" in envelope:
        result["transport_status"] = "server_error_envelope"
        result["server_error_chars"] = len(envelope["error"]) if isinstance(envelope["error"], str) else None
    reason = envelope.get("done_reason")
    result["done_reason"] = reason if reason in ("length", "stop", "load", "unload") else "other" if reason is not None else None
    for name in ("eval_count", "prompt_eval_count", "total_duration", "eval_duration"):
        result[name] = numeric(envelope.get(name))
    count = result["eval_count"]
    result["eval_count_equals_4096"] = count == 4096 if count is not None else None
    result["length_stop_at_4096"] = reason == "length" and count == 4096 if reason is not None and count is not None else None
    message = envelope.get("message", {})
    if not isinstance(message, dict):
        message = {}
    thinking = message.get("thinking", envelope.get("thinking"))
    result["thinking_chars"] = len(thinking) if isinstance(thinking, str) else None
    content = message.get("content", envelope.get("response"))
    if content is None:
        choices = envelope.get("choices")
        if isinstance(choices, list) and choices and isinstance(choices[0], dict):
            choice_message = choices[0].get("message")
            if isinstance(choice_message, dict):
                content = choice_message.get("content")
    if not isinstance(content, str):
        result["schema_status"] = "missing_or_nonstring_final_content"
        return result
    result["final_content_chars"] = len(content)
    result["empty_final_content"] = not content.strip()
    try:
        final = json.loads(content)
        result["final_json_valid"] = True
    except json.JSONDecodeError:
        result["final_json_valid"] = False
        result["schema_status"] = "invalid_final_json"
        return result
    issues = schema_issues(final, evidence_id) if vision else []
    result["schema_issue_codes"] = issues
    result["schema_status"] = "invalid_schema" if issues else "valid" if vision else "planner_json_only_not_schema_evaluated"
    return result


def freshness(evidence, evaluated_at, ttl, valid, accepted):
    capture = numeric(evidence.get("capture_time"))
    received = numeric(evidence.get("received_time"))
    age = evaluated_at - capture if evaluated_at is not None and capture is not None else None
    chronology = None if capture is None or received is None or evaluated_at is None else capture <= received <= evaluated_at
    if chronology is False:
        status = "invalid_timestamp_order"
    elif age is None or ttl is None:
        status = "unmeasured"
    elif age >= ttl:
        status = "at_or_beyond_context_ttl"
    else:
        status = "within_ttl"
    return dict(status=status, capture_sim_s=capture, received_sim_s=received,
                evaluation_sim_s=evaluated_at, frame_age_at_evaluation_s=age, ttl_sim_s=ttl,
                age_gt_ttl=age > ttl if age is not None and ttl is not None else None,
                age_ge_ttl=age >= ttl if age is not None and ttl is not None else None,
                timestamp_order_valid=chronology, harness_valid=valid, incident_accepted=accepted,
                note="Harness validity and incident acceptance have additional gates; fresh does not imply conclusive or accepted.")


def vision_attempts(report):
    trace = report.get("trace", [])
    records = report.get("evidence_records", [])
    pending, pairs = None, []
    for event in trace:
        if event.get("kind") == "tool_start":
            if pending is not None:
                pairs.append((pending, None))
                pending = None
            if event.get("action", {}).get("tool") == "observe":
                pending = event
        elif event.get("kind") == "tool_result" and event.get("tool") == "observe":
            pairs.append((pending, event))
            pending = None
    if pending is not None:
        pairs.append((pending, None))
    used, attempts = set(), []
    ttl = numeric(report.get("config", {}).get("max_evidence_age_seconds"))
    if ttl is None:
        ttl = numeric((report.get("context_snapshot") or {}).get("payload", {}).get("max_age"))
    for start, end in pairs:
        eid = (end or {}).get("evidence_id")
        index = next((i for i, r in enumerate(records) if i not in used and r.get("evidence", {}).get("id") == eid), None) if eid else None
        record = records[index] if index is not None else {}
        if index is not None:
            used.add(index)
        attempts.append(make_attempt(start, end, record, ttl, len(attempts)))
    for i, record in enumerate(records):
        if i not in used:
            attempts.append(make_attempt(None, None, record, ttl, len(attempts)))
    return attempts


def make_attempt(start, end, record, ttl, index):
    start, end = start or {}, end or {}
    evidence, inference = record.get("evidence", {}), record.get("inference", {})
    eid = evidence.get("id", end.get("evidence_id"))
    meta = response_metadata(inference.get("raw_response"), inference.get("status"), eid)
    return dict(attempt=index + 1, evidence_id=eid, camera=evidence.get("source", start.get("action", {}).get("target", end.get("target"))),
                tool_start_recorded=bool(start), tool_result_recorded=bool(end), inference_recorded=bool(inference),
                tool_status_code=error_code(end.get("status")), latency_wall_s=numeric(inference.get("latency_wall_seconds", end.get("latency_wall_seconds"))),
                response=meta,
                evidence_freshness=freshness(evidence, numeric(end.get("sim_time")), ttl, record.get("valid"), record.get("accepted")))


def safe_motion_reason(reason):
    # Navigation emits simulator/controller exceptions, not model reasoning.
    # Known public reasons remain readable; unknown text is not copied.
    known = {"Spot tilted beyond 45 degrees", "No progress or goal deadline exceeded", "Viewpoint heading timeout",
             "Idle stance drift exceeded 0.5m", "Explicit simulation reset to entrance"}
    return reason if reason in known else "other navigation reason (text withheld)" if reason else None


def audit_trial(path):
    data = path.read_bytes()
    report = json.loads(data)
    attempts = vision_attempts(report)
    trace = report.get("trace", [])
    planner_events = [dict(kind=e.get("kind"), error_code=error_code(e.get("error")),
        error_chars=len(e["error"]) if isinstance(e.get("error"), str) else None,
        sim_time=numeric(e.get("sim_time")), wall_elapsed_s=numeric(e.get("wall_elapsed")))
        for e in trace if e.get("kind") in ("rejected", "planner_error")]
    planner_responses = [response_metadata(r["response"], None, None, vision=False)
                         for r in report.get("planner_records", []) if isinstance(r.get("response"), (dict, str))]
    motion = []
    for record in report.get("motion_records", []):
        nav = record.get("navigation", {})
        motion.append(dict(target=record.get("target"), status=error_code(nav.get("status")),
                           reason=safe_motion_reason(nav.get("reason")),
                           reason_chars=len(nav["reason"]) if isinstance(nav.get("reason"), str) else None))
    motion_tool_results = [dict(target=e.get("target"), status=error_code(e.get("status")),
                                error_code=error_code(e.get("error"))) for e in trace
                           if e.get("kind") == "tool_result" and e.get("tool") == "inspect"]
    counters = dict(vision_attempts=len(attempts), vision_tool_starts=sum(a["tool_start_recorded"] for a in attempts),
        vision_inference_records=sum(a["inference_recorded"] for a in attempts),
        vision_wrapper_call_count=len(report["vision_call_latencies"]) if isinstance(report.get("vision_call_latencies"), list) else None,
        vision_provider_ok=sum(a["response"]["provider_status_code"] == "ok" for a in attempts),
        vision_provider_non_ok=sum(a["inference_recorded"] and a["response"]["provider_status_code"] not in {"ok", "unrecorded"} for a in attempts),
        vision_provider_status_unrecorded=sum(a["response"]["provider_status_code"] == "unrecorded" for a in attempts),
        vision_response_received=sum(a["response"]["response_recorded"] for a in attempts),
        valid_final_json=sum(a["response"]["final_json_valid"] is True for a in attempts),
        invalid_final_json=sum(a["response"]["final_json_valid"] is False for a in attempts),
        valid_vision_schema=sum(a["response"]["schema_status"] == "valid" for a in attempts),
        invalid_vision_schema=sum(a["response"]["schema_status"] == "invalid_schema" for a in attempts),
        final_json_not_evaluated=sum(a["response"]["final_json_valid"] is None for a in attempts),
        empty_final_content=sum(a["response"]["empty_final_content"] is True for a in attempts),
        done_reason_length=sum(a["response"]["done_reason"] == "length" for a in attempts),
        eval_count_4096=sum(a["response"]["eval_count_equals_4096"] is True for a in attempts),
        length_stop_at_4096=sum(a["response"]["length_stop_at_4096"] is True for a in attempts),
        frame_age_gt_ttl=sum(a["evidence_freshness"]["age_gt_ttl"] is True for a in attempts),
        frame_age_ge_ttl=sum(a["evidence_freshness"]["age_ge_ttl"] is True for a in attempts),
        frame_age_unmeasured=sum(a["evidence_freshness"]["frame_age_at_evaluation_s"] is None for a in attempts),
        harness_invalid=sum(a["evidence_freshness"]["harness_valid"] is False for a in attempts),
        planner_rejections=sum(e["kind"] == "rejected" for e in planner_events),
        planner_errors=sum(e["kind"] == "planner_error" for e in planner_events),
        motion_failed_records=sum(m["status"] in {"failed", "timed_out", "cancelled"} for m in motion),
        motion_failed_tool_results=sum(m["status"] in {"failed", "timeout", "timed_out", "cancelled", "error"} for m in motion_tool_results))
    return dict(trial_id=path.parent.name, source_result=str(path.resolve()), source_sha256=hashlib.sha256(data).hexdigest(),
                harness_completed=report.get("completed"), terminal_state=report.get("state"),
                harness_error_code=error_code(report.get("error")), counters=counters,
                vision_attempts=attempts, planner_events=planner_events, planner_response_metadata=planner_responses,
                motion_records=motion, motion_tool_results=motion_tool_results)


def markdown(result):
    title = "SYNTHETIC FIXTURE — NOT EXPERIMENTAL RESULTS" if result["fixture_only"] else "TRACE 구성요소 실패 감사"
    lines = ["# " + title, "", "완료된 실행도 내부 호출 실패를 포함할 수 있습니다. 이 감사는 동결된 trial-level 평가를 수정하지 않고 저장된 호출 기록을 별도로 보여줍니다.", "",
             "**전송 / 최종 JSON·스키마 / 근거 신선도는 서로 다른 상태입니다.** 응답 수신 후 빈 최종 출력이 나올 수 있고, JSON이 맞아도 근거가 만료될 수 있습니다. 사고 과정·응답 본문은 출력하지 않습니다.", "",
             "| trial | harness 완료 / 종료 상태 | 시각 시도 / inference 기록 | 최종 JSON 정상 / 오류 / 미측정 | provider non-ok | length / 4096 / 빈 최종 | age>TTL | planner 거부 / 오류 | 이동 실패 기록 / tool 결과 |",
             "| --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    for t in result["trials"]:
        c = t["counters"]
        lines.append(f"| {t['trial_id']} | {t['harness_completed']} / {t['terminal_state']} | {c['vision_attempts']} / {c['vision_inference_records']} | {c['valid_final_json']} / {c['invalid_final_json']} / {c['final_json_not_evaluated']} | {c['vision_provider_non_ok']} | {c['done_reason_length']} / {c['eval_count_4096']} / {c['empty_final_content']} | {c['frame_age_gt_ttl']} | {c['planner_rejections']} / {c['planner_errors']} | {c['motion_failed_records']} / {c['motion_failed_tool_results']} |")
    for t in result["trials"]:
        notable = [a for a in t["vision_attempts"] if a["response"]["provider_status_code"] != "ok"
                   or a["response"]["schema_status"] != "valid" or a["evidence_freshness"]["age_ge_ttl"] is True]
        bad_motion = [m for m in t["motion_records"] if m["status"] in {"failed", "timed_out", "cancelled"}]
        if notable or bad_motion or t["planner_events"]:
            lines += ["", "## " + t["trial_id"], ""]
        for a in notable:
            r, f = a["response"], a["evidence_freshness"]
            age = f"{f['frame_age_at_evaluation_s']:.2f}s" if f["frame_age_at_evaluation_s"] is not None else "NA"
            ttl = f"{f['ttl_sim_s']}s" if f["ttl_sim_s"] is not None else "NA"
            lines.append(f"- 시각 #{a['attempt']} ({a['camera']}): transport={r['transport_status']}; final JSON={r['final_json_valid']}; schema={r['schema_status']}; done_reason={r['done_reason']}; eval_count={r['eval_count']}; final chars={r['final_content_chars']}; age={age} / TTL={ttl}; freshness={f['status']}; harness_valid={f['harness_valid']}.")
        for m in bad_motion:
            lines.append(f"- 이동 {m['target']}: {m['status']}; {m['reason'] or 'reason unrecorded'}.")
        for p in t["planner_events"]:
            lines.append(f"- 계획 {p['kind']}: {p['error_code']} (오류 문자열 {p['error_chars']}자; 내용 생략).")
    if result["missing_result_trials"]:
        lines += ["", "result.json 없음: " + ", ".join(result["missing_result_trials"]) + ". 실행하지 않았거나 중단된 경우를 성공으로 간주하지 않습니다."]
    lines += ["", "스키마 감사는 저장된 최종 응답의 형식 검사이며 시각 판단 정답률이 아닙니다. age>TTL은 평가 시각−촬영 시각으로 계산합니다. ContextGraph의 정확한 만료 경계(age≥TTL)도 JSON에 별도로 기록합니다. invalid 근거가 곧 전송 실패라는 뜻은 아닙니다.", "",
              "도구 시도 수와 저장된 inference 수, wrapper 호출 수가 다르면 취소·미완료 호출 또는 로그 범위 차이가 있을 수 있습니다. 누락된 응답 상태를 임의로 채우지 않습니다. planner latency·thinking 내용은 분석하지 않으며 종료 이유와 토큰 수만으로 원인을 확정하지 않습니다.", ""]
    return "\n".join(lines)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("run_dir", type=Path)
    p.add_argument("--output-dir", required=True, type=Path)
    p.add_argument("--trial", action="append", help="Restrict to an already completed saved trial ID")
    p.add_argument("--fixture", action="store_true")
    args = p.parse_args()
    folders = sorted((args.run_dir / "trials").iterdir())
    if args.trial:
        folders = [p for p in folders if p.name in set(args.trial)]
        if {p.name for p in folders} != set(args.trial):
            raise ValueError("Requested trial directory is missing")
    folders = [p for p in folders if p.is_dir()]
    trials = [audit_trial(p / "result.json") for p in folders if (p / "result.json").exists()]
    result = dict(schema_version=1, fixture_only=args.fixture, trials=trials,
                  missing_result_trials=[p.name for p in folders if not (p / "result.json").exists()],
                  independent_of_frozen_outcome_evaluator=True, no_model_or_simulator_calls=True,
                  response_text_and_thinking_text_omitted=True)
    # Confirm a live writer did not change any input while the audit was read.
    for t in trials:
        if hashlib.sha256(Path(t["source_result"]).read_bytes()).hexdigest() != t["source_sha256"]:
            raise RuntimeError("Saved result changed during audit: " + t["trial_id"])
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "component_failures.json").write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
    (args.output_dir / "component_failures.md").write_text(markdown(result), encoding="utf-8")
    print(json.dumps(dict(trials=len(trials), missing_results=len(result["missing_result_trials"]), output=str(args.output_dir.resolve()), fixture_only=args.fixture)))


if __name__ == "__main__":
    main()
