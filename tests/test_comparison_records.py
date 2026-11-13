import copy
import unittest

from haiclaw.comparison_metrics import evaluate
from haiclaw.comparison_records import normalize_report


def report(posture="standing", origin=100):
    question = dict(state="resolved", value=posture == "lying", evidence_ids=["e1"])
    presence = dict(state="resolved", value=True, evidence_ids=["e1"])
    state = "danger_confirmed" if posture == "lying" else "escalated_unknown"
    return dict(completed=True, error=None, stop_error=None, state=state,
                inspection_answer=dict(presence=presence, lying=question),
                executed_tools=1, wall_seconds=12,
                config=dict(max_evidence_age_seconds=10, wall_budget_seconds=60),
                trace=[dict(kind="opened", sim_time=origin, deadline=origin+20),
                       dict(kind="tool_start", sim_time=origin+1),
                       dict(kind="inspection_answer", sim_time=origin+5),
                       dict(kind="finished", sim_time=origin+5)],
                incident_events=[dict(state=state, time=origin+5, local_alert=True,
                                      reason="operator inspection answered; overall safety remains unestablished")],
                context_snapshot=dict(payload=dict(time=origin+5, max_age=10, revoked=[],
                    questions=dict(presence=presence, lying=question),
                    evidence={"e1":dict(id="e1", capture_time=origin+3, received_time=origin+4,
                        expires_at=origin+13, quality=1, reason="", interpretation=dict(
                            person_visible="yes", posture=posture, needs_more_observation=False, limitations=[]))})))


def normalize(value, **kw):
    args = dict(trial_id="t", scenario_id="s", repetition_id="r", policy="trace", condition="external_condition")
    args.update(kw)
    return normalize_report(value, **args)


class ComparisonRecordTests(unittest.TestCase):
    def test_standing_question_is_not_safe_and_times_are_relative(self):
        r = normalize(report(), timings=dict(planner_latency_s=2, vision_latency_s=3,
                                             wall_latency_s=15, distance_m=4.2))
        self.assertEqual(r["inspection_question_answer"], "standing")
        self.assertEqual(r["safety_verdict"], "unknown")
        self.assertEqual(r["alert_kind"], "unknown_handoff")
        self.assertEqual(r["alert_sim_s"], 5)
        self.assertEqual(r["end_sim_s"], 5)
        self.assertEqual(r["sim_latency_s"], 5)
        self.assertEqual(r["wall_latency_s"], 15)
        self.assertEqual(r["normalization"]["relative_deadline_sim_s"], 20)
        self.assertEqual(r["planner_latency_s"], 2)
        self.assertEqual(r["vision_latency_s"], 3)
        self.assertEqual(r["distance_m"], 4.2)

    def test_binary_not_lying_does_not_turn_seated_into_standing(self):
        r = normalize(report("seated"))
        self.assertEqual(r["inspection_question_answer"], "unknown")
        self.assertIn("lying=false", r["normalization"]["warnings"][0])

    def test_standing_requires_fresh_specific_support(self):
        for mutation in ("missing", "expired", "revoked", "limited", "low_quality", "nan_quality"):
            with self.subTest(mutation=mutation):
                raw = report()
                p = raw["context_snapshot"]["payload"]
                e = p["evidence"]["e1"]
                if mutation == "missing": p["evidence"] = {}
                if mutation == "expired": e["expires_at"] = 105
                if mutation == "revoked": p["revoked"] = ["e1"]
                if mutation == "limited": e["interpretation"]["limitations"] = ["occlusion"]
                if mutation == "low_quality": e["quality"] = .2
                if mutation == "nan_quality": e["quality"] = float("nan")
                self.assertEqual(normalize(raw)["inspection_question_answer"], "unknown")

    def test_context_snapshot_can_answer_when_finish_flag_not_enabled(self):
        raw = report("lying")
        raw["inspection_answer"] = None
        r = normalize(raw)
        self.assertEqual(r["inspection_question_answer"], "lying")
        self.assertEqual(r["safety_verdict"], "danger")
        self.assertEqual(r["normalization"]["answer_source"], "context_snapshot")

    def test_evidence_record_fallback_retains_standing_specificity(self):
        raw = report()
        e = raw["context_snapshot"]["payload"]["evidence"].pop("e1")
        interpretation = e.pop("interpretation")
        interpretation["observation_limitations"] = interpretation.pop("limitations")
        raw["evidence_records"] = [dict(evidence=e, valid=True,
            inference=dict(status="ok", interpretation=interpretation))]
        self.assertEqual(normalize(raw)["inspection_question_answer"], "standing")

    def test_conflicted_question_remains_unknown(self):
        raw = report()
        raw["inspection_answer"]["lying"]["state"] = "conflicted"
        self.assertEqual(normalize(raw)["inspection_question_answer"], "unknown")

    def test_same_time_alert_update_becomes_danger_without_second_alert(self):
        raw = report("lying")
        raw["incident_events"] = [dict(time=120, state="escalated_unknown", local_alert=True,
                                      reason="deadline without confirmation"),
                                  dict(time=120, state="danger_confirmed", local_alert=False,
                                       alert_update=True, reason="fresh lying")]
        raw["trace"][-1]["sim_time"] = 120
        r = normalize(raw)
        self.assertEqual(r["alert_kind"], "danger")
        self.assertEqual(r["alert_sim_s"], 20)
        self.assertEqual(r["status"], "completed")

    def test_global_timeout_and_step_limit_have_different_statuses(self):
        raw = report()
        raw["inspection_answer"] = None
        raw["context_snapshot"] = None
        raw["incident_events"][0]["reason"] = "step budget exhausted"
        r = normalize(raw)
        self.assertEqual(r["status"], "completed")
        self.assertTrue(r["normalization"]["resource_exhausted"])
        raw["incident_events"][0].update(time=120, reason="deadline without confirmation")
        raw["trace"][-1]["sim_time"] = 120
        self.assertEqual(normalize(raw)["status"], "timeout")
        raw["trace"][-1]["sim_time"] = 105
        raw["incident_events"][0].update(time=105, reason="wall budget exhausted")
        self.assertEqual(normalize(raw)["status"], "timeout")

    def test_terminal_failures_are_not_successful_abstentions(self):
        for reason in ("invalid planner output limit", "tool failure limit", "operation/wall deadline"):
            raw = report()
            raw["incident_events"][0]["reason"] = reason
            self.assertEqual(normalize(raw)["status"], "error")
        raw = report()
        raw["incident_events"][0]["reason"] = "operation/wall deadline"
        self.assertEqual(normalize(raw, timings=dict(wall_latency_s=60))["status"], "timeout")

    def test_local_tool_error_recovered_by_success_does_not_fail_whole_trial(self):
        raw = report("lying")
        raw["trace"].insert(2, dict(kind="tool_result", sim_time=102, status="timeout"))
        self.assertEqual(normalize(raw)["status"], "completed")

    def test_wrapper_timeout_before_opening_keeps_failure_row(self):
        r = normalize(dict(completed=False, error="preflight", wall_seconds=3), status="timeout")
        self.assertEqual(r["status"], "timeout")
        self.assertEqual(r["inspection_question_answer"], "unknown")
        self.assertIsNone(r["end_sim_s"])
        self.assertIsNone(r["tool_calls"])
        self.assertIsNone(r["distance_m"])

    def test_missing_measurements_are_not_inferred_from_arrival_or_provider_duration(self):
        raw = report()
        raw["motion_records"] = [dict(navigation=dict(status="arrived"))]
        raw["planner_records"] = [dict(response=dict(total_duration=99999999))]
        r = normalize(raw)
        self.assertIsNone(r["distance_m"])
        self.assertIsNone(r["planner_latency_s"])
        self.assertIsNone(r["vision_latency_s"])
        self.assertEqual(r["wall_latency_s"], 12)

    def test_different_global_sim_clocks_produce_paired_relative_records(self):
        rows = [normalize(report("lying", 100), trial_id="a", policy="a"),
                normalize(report("lying", 900), trial_id="b", policy="b")]
        gt = {r["trial_id"]: dict(condition="lying", actual_posture="lying", answerable=True,
            dangerous=True, incident_start_sim_s=0, deadline_sim_s=20, danger_onset_sim_s=0)
              for r in rows}
        result = evaluate(rows, gt, bootstrap_samples=0)
        paired = result["strata"][0]["paired"][0]
        self.assertTrue(paired["all_trials_paired"])
        self.assertEqual(paired["metrics"]["danger_alert_latency_from_onset_s"]["difference_b_minus_a"], 0)

    def test_inputs_are_not_mutated_and_invalid_clocks_rejected(self):
        raw = report()
        before = copy.deepcopy(raw)
        normalize(raw)
        self.assertEqual(raw, before)
        raw["trace"][-1]["sim_time"] = 99
        with self.assertRaisesRegex(ValueError, "nonmonotonic"):
            normalize(raw)
        with self.assertRaisesRegex(ValueError, "nonnegative"):
            normalize(report(), timings=dict(distance_m=-1))


if __name__ == "__main__":
    unittest.main()
