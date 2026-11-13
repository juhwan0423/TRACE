import copy
import json
import unittest

from tracebot.comparison_metrics import evaluate


def trial(name, *, policy="trace", scenario="scene-1", repetition="r1", **changes):
    row = dict(trial_id=name, scenario_id=scenario, repetition_id=repetition,
               policy=policy, inspection_question_answer="lying", status="completed",
               safety_verdict="danger", alert_kind="danger", alert_sim_s=4,
               end_sim_s=5, tool_calls=2, distance_m=1.5, planner_latency_s=.2,
               vision_latency_s=.4, wall_latency_s=8, sim_latency_s=5,
               verification_level="fixture")
    row.update(changes)
    return row


def truth(**changes):
    row = dict(condition="lying_visible", actual_posture="lying", answerable=True,
               dangerous=True, assertion_supported=True, safe_closure_supported=False,
               incident_start_sim_s=0, danger_onset_sim_s=1,
               discernible_observation_sim_s=2, deadline_sim_s=10)
    row.update(changes)
    return row


def summary(rows, truths, policy="trace"):
    return evaluate(rows, truths, bootstrap_samples=20)["strata"][0]["policies"][policy]


class ComparisonMetricsTests(unittest.TestCase):
    def test_unknown_timeout_and_error_stay_in_answerable_denominator(self):
        rows = [trial("good", repetition="r1"),
                trial("unknown", repetition="r2", inspection_question_answer="unknown"),
                trial("timeout", repetition="r3", status="timeout"),
                trial("error", repetition="r4", status="error")]
        s = summary(rows, {r["trial_id"]: truth() for r in rows})
        m = s["metrics"]
        self.assertEqual(m["answerable_resolution_rate"]["denominator"], 4)
        self.assertEqual(m["answerable_resolution_rate"]["value"], .25)
        self.assertEqual(m["unresolved_rate"]["value"], .75)
        self.assertEqual(m["timeout_rate"]["value"], .25)
        self.assertEqual(m["error_rate"]["value"], .25)

    def test_unanswerable_unknown_can_be_expected_correct_but_unresolved(self):
        rows = [trial("u", inspection_question_answer="unknown", alert_kind="unknown_handoff", safety_verdict="unknown", alert_sim_s=10, end_sim_s=10),
                trial("f", repetition="r2", inspection_question_answer="unknown", status="timeout", alert_kind="none", alert_sim_s=None)]
        s = summary(rows, {r["trial_id"]: truth(answerable=False) for r in rows})
        m = s["metrics"]
        self.assertEqual(m["expected_response_correct_rate"]["value"], .5)
        self.assertEqual(m["unresolved_rate"]["value"], 1)
        self.assertIsNone(m["answerable_resolution_rate"]["value"])
        self.assertEqual(m["dangerous_case_miss_rate"]["value"], .5)
        self.assertEqual(m["dangerous_case_unconfirmed_rate"]["value"], 1)

    def test_standing_answer_does_not_imply_safe(self):
        r = trial("standing", inspection_question_answer="standing", safety_verdict="safe", alert_kind="none", alert_sim_s=None)
        t = truth(actual_posture="standing", dangerous=False, safe_closure_supported=False)
        s = summary([r], {"standing": t})["metrics"]
        self.assertEqual(s["answerable_resolution_rate"]["value"], 1)
        self.assertEqual(s["unsupported_safe_closure_rate"]["value"], 1)
        self.assertEqual(s["false_alert_rate"]["value"], 0)

    def test_false_assertion_incorrect_and_unsupported_are_separate(self):
        rows = [trial("lucky", inspection_question_answer="lying"),
                trial("wrong", repetition="r2", inspection_question_answer="standing"),
                trial("unknown_support", repetition="r3")]
        gt = {"lucky": truth(answerable=False, assertion_supported=False),
              "wrong": truth(assertion_supported=False),
              "unknown_support": truth(assertion_supported=None)}
        s = summary(rows, gt)
        m = s["metrics"]
        self.assertEqual(m["false_assertion_unanswerable_rate"]["value"], 1)
        self.assertEqual(m["false_assertion_unanswerable_rate"]["denominator"], 1)
        self.assertAlmostEqual(m["incorrect_posture_assertion_rate"]["value"], 1 / 3)
        self.assertEqual(m["unsupported_posture_assertion_rate"]["denominator"], 2)
        self.assertEqual(m["unsupported_posture_assertion_rate"]["value"], 1)
        self.assertEqual(s["assertions_with_unknown_support"], 1)

    def test_no_assertions_are_not_unsupported_without_annotation(self):
        row = trial("u", inspection_question_answer="unknown")
        s = summary([row], {"u": truth(assertion_supported=None)})
        self.assertEqual(s["metrics"]["unsupported_posture_assertion_rate"]["value"], 0)

    def test_alert_latencies_do_not_drop_misses_from_deadline_capped_cost(self):
        rows = [trial("ok"), trial("miss", repetition="r2", alert_kind="none", alert_sim_s=None, end_sim_s=10),
                trial("late", repetition="r3", alert_sim_s=12, end_sim_s=13)]
        m = summary(rows, {r["trial_id"]: truth() for r in rows})["metrics"]
        self.assertAlmostEqual(m["dangerous_case_miss_rate"]["value"], 2 / 3)
        self.assertEqual(m["danger_alert_latency_from_onset_s"]["denominator"], 2)
        self.assertEqual(m["danger_alert_latency_from_onset_s"]["value"], 7)
        self.assertEqual(m["danger_alert_latency_capped_at_deadline_s"]["denominator"], 3)
        self.assertEqual(m["danger_alert_latency_capped_at_deadline_s"]["value"], 7)
        self.assertAlmostEqual(m["deadline_overrun_rate"]["value"], 1 / 3)

    def test_unknown_handoff_is_not_a_danger_alert_latency(self):
        row = trial("handoff", alert_kind="unknown_handoff", safety_verdict="unknown")
        m = summary([row], {"handoff": truth()})["metrics"]
        self.assertEqual(m["dangerous_case_miss_rate"]["value"], 0)
        self.assertEqual(m["dangerous_case_unconfirmed_rate"]["value"], 1)
        self.assertIsNone(m["danger_alert_latency_from_onset_s"]["value"])
        self.assertIsNone(m["danger_alert_latency_from_discernible_s"]["value"])
        self.assertEqual(m["danger_alert_latency_capped_at_deadline_s"]["value"], 9)

    def test_missing_latency_is_not_assumed_zero(self):
        row = trial("missing", planner_latency_s=None, distance_m=None)
        m = summary([row], {"missing": truth(danger_onset_sim_s=None, discernible_observation_sim_s=None)})["metrics"]
        for key in ("planner_latency_s", "distance_m", "danger_alert_latency_from_onset_s"):
            self.assertIsNone(m[key]["value"])
            self.assertEqual(m[key]["denominator"], 0)
        self.assertEqual(m["wall_latency_s"]["value"], 8)
        self.assertEqual(m["sim_latency_s"]["value"], 5)

    def test_condition_is_external_and_per_condition_results_not_pooled(self):
        a = trial("a", condition="fabricated")
        b = trial("b", repetition="r2", inspection_question_answer="unknown")
        report = evaluate([a, b], {"a": truth(condition="visible"), "b": truth(condition="blocked", answerable=False)})
        cond = report["strata"][0]["by_condition"]
        self.assertEqual(set(cond), {"visible", "blocked"})
        self.assertEqual(cond["visible"]["policies"]["trace"]["metrics"]["answerable_resolution_rate"]["value"], 1)
        self.assertIsNone(cond["blocked"]["policies"]["trace"]["metrics"]["answerable_resolution_rate"]["value"])

    def test_histories_default_development_and_verification_levels_are_separate(self):
        rows = [trial("historical"), trial("test", evaluation_role="confirmatory", repetition="r2"),
                trial("rendered", repetition="r3", verification_level="isaac_rendered")]
        gt = {"historical": truth(), "test": truth(evaluation_role="confirmatory"), "rendered": truth()}
        result = evaluate(rows, gt)
        self.assertEqual(len(result["strata"]), 3)
        self.assertEqual({(s["evaluation_role"], s["verification_level"]) for s in result["strata"]},
                         {("development", "fixture"), ("confirmatory", "fixture"), ("development", "isaac_rendered")})

    def test_missing_pairs_are_reported_and_policy_failures_retained(self):
        rows = [trial("a1", policy="a"), trial("b1", policy="b", status="timeout"),
                trial("a2", policy="a", scenario="scene-2")]
        result = evaluate(rows, {r["trial_id"]: truth() for r in rows}, bootstrap_samples=50)
        s = result["strata"][0]
        self.assertEqual(s["policies"]["a"]["trials"], 2)
        self.assertEqual(s["policies"]["b"]["trials"], 1)
        paired = s["paired"][0]
        self.assertFalse(paired["all_trials_paired"])
        self.assertEqual(paired["matched_trial_pairs"], 1)
        self.assertEqual(paired["missing_policy_b"][0]["scenario_id"], "scene-2")
        metric = paired["metrics"]["answerable_resolution_rate"]
        self.assertEqual(metric["difference_b_minus_a"], -1)
        self.assertIsNone(metric["bootstrap_95_interval"])

    def test_fully_absent_expected_policy_is_explicitly_missing(self):
        row = trial("a", policy="a")
        report = evaluate([row], {"a": truth()}, expected_policies=["a", "b"])
        self.assertFalse(report["comparison_complete"])
        s = report["strata"][0]
        self.assertEqual(s["policies"]["b"]["trials"], 0)
        self.assertEqual(len(s["paired"][0]["missing_policy_b"]), 1)
        self.assertEqual(s["paired"][0]["matched_trial_pairs"], 0)

    def test_repetitions_do_not_receive_independent_scenario_weight(self):
        rows, gt = [], {}
        # Ten repetitions favor b in scene1; one favors a in scene2.
        # Scenario-weighted difference must be zero, not9/11.
        for scene, repetitions in (("scene1", 10), ("scene2", 1)):
            for i in range(repetitions):
                for policy in ("a", "b"):
                    name = f"{scene}-{i}-{policy}"
                    correct = (scene == "scene1") == (policy == "b")
                    rows.append(trial(name, policy=policy, scenario=scene, repetition=str(i),
                                      inspection_question_answer="lying" if correct else "unknown"))
                    gt[name] = truth()
        one = evaluate(rows, gt, bootstrap_samples=200, seed=4)
        two = evaluate(list(reversed(rows)), gt, bootstrap_samples=200, seed=4)
        m = one["strata"][0]["paired"][0]["metrics"]["answerable_resolution_rate"]
        self.assertEqual(m["difference_b_minus_a"], 0)
        self.assertEqual(m["independent_scenarios"], 2)
        self.assertEqual(m["paired_trials"], 11)
        self.assertEqual(m["bootstrap_95_interval"], [-1, 1])
        self.assertEqual(one["strata"][0]["paired"], two["strata"][0]["paired"])

    def test_many_repetitions_in_one_scene_do_not_create_interval(self):
        rows = [trial(f"{p}{i}", policy=p, repetition=str(i)) for p in ("a", "b") for i in range(20)]
        report = evaluate(rows, {r["trial_id"]: truth() for r in rows})
        m = report["strata"][0]["paired"][0]["metrics"]["answerable_resolution_rate"]
        self.assertEqual(m["independent_scenarios"], 1)
        self.assertIsNone(m["bootstrap_95_interval"])

    def test_rejects_mismatched_pair_truth(self):
        rows = [trial("a", policy="a"), trial("b", policy="b")]
        with self.assertRaisesRegex(ValueError, "paired external truth differs"):
            evaluate(rows, {"a": truth(), "b": truth(answerable=False)})

    def test_rejects_missing_truth_duplicate_trials_and_nonfinite_costs(self):
        row = trial("x")
        with self.assertRaisesRegex(ValueError, "missing external"):
            evaluate([row], {})
        with self.assertRaisesRegex(ValueError, "duplicate trial_id"):
            evaluate([row, row], {"x": truth()})
        with self.assertRaisesRegex(ValueError, "finite"):
            evaluate([trial("x", wall_latency_s=float("nan"))], {"x": truth()})
        with self.assertRaisesRegex(ValueError, "must agree"):
            evaluate([trial("x", alert_sim_s=None)], {"x": truth()})
        with self.assertRaisesRegex(ValueError, "integer count"):
            evaluate([trial("x", tool_calls=1.5)], {"x": truth()})

    def test_does_not_mutate_inputs_and_output_is_strict_json(self):
        rows = [trial("x")]
        gt = {"x": truth(), "unused": truth()}
        before = copy.deepcopy((rows, gt))
        result = evaluate(rows, gt, bootstrap_samples=0)
        self.assertEqual((rows, gt), before)
        self.assertEqual(result["unused_ground_truth_ids"], ["unused"])
        json.dumps(result, allow_nan=False)

    def test_legacy_unobservable_maps_to_unknown_without_physical_inference(self):
        row = trial("x", inspection_question_answer="unobservable")
        t = truth(answerable=False)
        del t["actual_posture"]
        t["posture_label"] = "unobservable"
        m = summary([row], {"x": t})["metrics"]
        self.assertEqual(m["expected_response_correct_rate"]["value"], 1)
        self.assertEqual(m["unresolved_rate"]["value"], 1)
        self.assertIsNone(m["incorrect_posture_assertion_rate"]["value"])


if __name__ == "__main__":
    unittest.main()
