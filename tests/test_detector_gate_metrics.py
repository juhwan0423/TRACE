import copy
import json
import unittest

from haiclaw.detector_gate_metrics import evaluate_gate


def record(name="trial-1", **overrides):
    row = dict(trial_id=name, policy="gate_on", scenario_id="scene-1", repetition_id="r1",
               inspection_question_answer="lying", status="completed", wall_latency_s=8,
               sim_latency_s=5, distance_m=2, model_calls=3, detector_calls=2,
               detector_latency_s=.2, verification_level="fixture", alert_kind="danger",
               normalization={"answer_evidence_ids": ["frame-1"], "answer_sim_s": 4})
    row.update(overrides)
    return row


def truth(**overrides):
    row = dict(actual_posture="lying", deadline_sim_s=10, wall_budget_s=20)
    row.update(overrides)
    return row


def annotation(**overrides):
    row = dict(evidence_ids=["frame-1"], claim_target_present=True, claim_observed_posture="lying")
    row.update(overrides)
    return row


def arm(rows, annotations=None, truths=None):
    truths = truths if truths is not None else {r["trial_id"]: truth() for r in rows}
    annotations = annotations if annotations is not None else {r["trial_id"]: annotation() for r in rows}
    return evaluate_gate(rows, truths, annotations)["strata"][0]["policies"]["gate_on"]


class DetectorGateMetricsTests(unittest.TestCase):
    def test_supported_correct_resolution(self):
        report = arm([record()])
        self.assertEqual(report["grounded_correct_within_budget_rate"]["value"], 1)
        self.assertEqual(report["presence_unsupported_assertion_risk"]["value"], 0)

    def test_segmentation_presence_never_proves_posture(self):
        report = arm([record()], {"trial-1": annotation(claim_observed_posture=None)})
        self.assertEqual(report["presence_unsupported_assertion_risk"]["value"], 0)
        metric = report["grounded_correct_within_budget_rate"]
        self.assertIsNone(metric["value"])
        self.assertEqual(metric["identification_bounds"], [0, 1])

    def test_unreadable_is_annotated_failure_not_missing(self):
        report = arm([record()], {"trial-1": annotation(claim_observed_posture="unreadable")})
        self.assertEqual(report["grounded_correct_within_budget_rate"]["value"], 0)
        self.assertEqual(report["grounded_correct_within_budget_rate"]["unknown"], 0)

    def test_lucky_correct_absent_assertion_is_not_grounded(self):
        report = arm([record()], {"trial-1": annotation(claim_target_present=False, claim_observed_posture="unreadable")})
        self.assertEqual(report["grounded_correct_within_budget_rate"]["value"], 0)
        self.assertEqual(report["presence_unsupported_assertion_risk"]["value"], 1)

    def test_handoff_timeout_and_error_stay_in_denominator(self):
        rows = [record("good"), record("handoff", inspection_question_answer="unknown", alert_kind="unknown_handoff"),
                record("timeout", status="timeout"), record("error", status="error")]
        report = arm(rows)
        self.assertEqual(report["grounded_correct_within_budget_rate"]["denominator"], 4)
        self.assertEqual(report["grounded_correct_within_budget_rate"]["value"], .25)
        self.assertEqual(report["unresolved_rate"]["value"], .75)
        self.assertEqual(report["unknown_handoff_rate"]["value"], .25)

    def test_missing_annotation_has_bounds_over_all_trials(self):
        rows = [record("known"), record("missing"), record("handoff", inspection_question_answer="unknown")]
        labels = {"known": annotation(claim_target_present=False, claim_observed_posture="unreadable")}
        report = arm(rows, labels)
        metric = report["presence_unsupported_assertion_risk"]
        self.assertIsNone(metric["value"])
        self.assertEqual(metric["denominator"], 3)
        self.assertEqual(metric["identification_bounds"], [1 / 3, 2 / 3])
        self.assertEqual(report["presence_unsupported_given_assertion"]["denominator"], 2)

    def test_no_assertion_is_known_zero_even_without_annotation(self):
        report = arm([record(inspection_question_answer="unknown")], {})
        self.assertEqual(report["presence_unsupported_assertion_risk"]["value"], 0)
        self.assertEqual(report["grounded_correct_within_budget_rate"]["value"], 0)
        self.assertIsNone(report["presence_unsupported_given_assertion"]["value"])

    def test_sim_and_wall_deadlines_both_apply(self):
        rows = [record("late_sim", normalization={"answer_evidence_ids": ["frame-1"], "answer_sim_s": 11}),
                record("late_wall", wall_latency_s=21)]
        self.assertEqual(arm(rows)["grounded_correct_within_budget_rate"]["value"], 0)

    def test_answer_wall_time_can_be_before_cleanup_and_missing_time_is_unknown(self):
        early = record("early", wall_latency_s=21, answer_wall_s=8)
        self.assertEqual(arm([early])["grounded_correct_within_budget_rate"]["value"], 1)
        missing = record("missing", normalization={"answer_evidence_ids": ["frame-1"]})
        self.assertIsNone(arm([missing])["grounded_correct_within_budget_rate"]["value"])

    def test_no_cited_frame_is_unsupported_not_unannotated(self):
        row = record(normalization={"answer_evidence_ids": [], "answer_sim_s": 3})
        report = arm([row], {})
        self.assertEqual(report["presence_unsupported_assertion_risk"]["value"], 1)
        self.assertEqual(report["grounded_correct_within_budget_rate"]["value"], 0)

    def test_wrong_label_cannot_be_rescued_by_support(self):
        report = arm([record(inspection_question_answer="standing")],
                     {"trial-1": annotation(claim_observed_posture="standing")})
        self.assertEqual(report["grounded_correct_within_budget_rate"]["value"], 0)

    def test_rejects_mismatched_frames_conflicting_labels_and_invalid_costs(self):
        with self.assertRaisesRegex(ValueError, "exactly match"):
            arm([record()], {"trial-1": annotation(evidence_ids=["another-frame"])})
        with self.assertRaisesRegex(ValueError, "conflicts"):
            arm([record()], {"trial-1": annotation(claim_target_present=False)})
        with self.assertRaisesRegex(ValueError, "finite"):
            arm([record(distance_m=float("nan"))])
        with self.assertRaisesRegex(ValueError, "integer count"):
            arm([record(model_calls=1.5)])

    def test_cost_means_include_failures_and_report_missing(self):
        rows = [record("good", wall_latency_s=10), record("fail", status="error", wall_latency_s=30, distance_m=None)]
        costs = arm(rows)["costs"]
        self.assertEqual(costs["wall_latency_s"]["value"], 20)
        self.assertEqual(costs["distance_m"]["measured_trials"], 1)
        self.assertEqual(costs["distance_m"]["missing_trials"], 1)
        self.assertIsNone(costs["tool_calls"]["value"])

    def test_nested_wrapper_detector_cost_is_preserved_without_filling_missing_zero(self):
        row = record(detector_calls=None, detector_latency_s=None,
                     person_gate_cost={"enabled": True, "calls": 4, "latency_wall_seconds": .7})
        costs = arm([row])["costs"]
        self.assertEqual(costs["detector_calls"]["value"], 4)
        self.assertEqual(costs["detector_latency_s"]["value"], .7)
        with self.assertRaisesRegex(ValueError, "disagrees"):
            arm([record(person_gate_cost={"calls": 99})])

    def test_development_and_confirmatory_are_separate_and_missing_manifest_reported(self):
        rows = [record("dev"), record("heldout")]
        truths = {"dev": truth(), "heldout": truth(evaluation_role="confirmatory")}
        report = evaluate_gate(rows, truths, {}, expected_trial_ids=["dev", "heldout", "unattempted"])
        self.assertEqual(len(report["strata"]), 2)
        self.assertEqual(report["missing_trial_ids"], ["unattempted"])
        self.assertFalse(report["all_manifest_trials_recorded"])

    def test_inputs_not_mutated_and_report_json_serializable(self):
        rows, truths, labels = [record()], {"trial-1": truth()}, {"trial-1": annotation()}
        before = copy.deepcopy((rows, truths, labels))
        result = evaluate_gate(rows, truths, labels)
        self.assertEqual((rows, truths, labels), before)
        json.dumps(result, allow_nan=False)

    def test_posture_subgroups_keep_attempt_denominators_costs_and_missing_annotations(self):
        rows = [record("lying_good"), record("lying_unreviewed", wall_latency_s=12),
                record("standing", inspection_question_answer="standing", wall_latency_s=4)]
        truths = {"lying_good": truth(), "lying_unreviewed": truth(),
                  "standing": truth(actual_posture="standing")}
        labels = {"lying_good": annotation(),
                  "standing": annotation(claim_observed_posture="standing")}
        report = arm(rows, labels, truths)
        lying = report["by_actual_posture"]["lying"]
        self.assertEqual(lying["trials"], 2)
        self.assertEqual(lying["grounded_correct_within_budget_rate"]["denominator"], 2)
        self.assertEqual(lying["grounded_correct_within_budget_rate"]["identification_bounds"], [.5, 1])
        self.assertIsNone(lying["grounded_correct_within_budget_rate"]["value"])
        self.assertEqual(lying["costs"]["wall_latency_s"]["value"], 10)
        self.assertEqual(report["by_actual_posture"]["standing"]["grounded_correct_within_budget_rate"]["value"], 1)

    def test_missing_answerability_is_separate_from_unanswerable(self):
        rows = [record("legacy"), record("explicit_unknown"), record("answerable"), record("unanswerable")]
        truths = {"legacy": truth(), "explicit_unknown": truth(answerable=None),
                  "answerable": truth(answerable=True), "unanswerable": truth(answerable=False)}
        groups = arm(rows, truths=truths)["by_answerability"]
        self.assertEqual({key: value["trials"] for key, value in groups.items()},
                         {"true": 1, "false": 1, "unknown": 2})
        self.assertEqual(groups["false"]["inappropriate_posture_assertion_rate"]["denominator"], 1)

    def test_abstain_everywhere_is_not_perfect_resolution(self):
        rows = [record(name, inspection_question_answer="unknown", alert_kind="unknown_handoff",
                       alert_sim_s=7, alert_wall_s=8) for name in ("visible", "unanswerable")]
        truths = {"visible": truth(answerable=True), "unanswerable": truth(answerable=False)}
        report = arm(rows, {}, truths)
        self.assertEqual(report["presence_unsupported_assertion_risk"]["value"], 0)
        self.assertEqual(report["by_answerability"]["true"]["grounded_correct_within_budget_rate"]["value"], 0)
        self.assertEqual(report["by_answerability"]["false"]["correct_unknown_handoff_rate"]["value"], 1)
        self.assertEqual(report["by_answerability"]["true"]["unresolved_rate"]["value"], 1)

    def test_error_timeout_and_late_handoffs_are_not_correct(self):
        rows = [record("good", inspection_question_answer="unknown", alert_kind="unknown_handoff",
                       alert_sim_s=7, alert_wall_s=8),
                record("timeout", inspection_question_answer="unknown", alert_kind="unknown_handoff",
                       status="timeout", alert_sim_s=7, alert_wall_s=8),
                record("error", inspection_question_answer="unknown", alert_kind="unknown_handoff",
                       status="error", alert_sim_s=7, alert_wall_s=8),
                record("late_sim", inspection_question_answer="unknown", alert_kind="unknown_handoff",
                       alert_sim_s=11, alert_wall_s=8),
                record("late_wall", inspection_question_answer="unknown", alert_kind="unknown_handoff",
                       alert_sim_s=7, alert_wall_s=21)]
        truths = {row["trial_id"]: truth(answerable=False) for row in rows}
        group = arm(rows, {}, truths)["by_answerability"]["false"]
        self.assertEqual(group["correct_unknown_handoff_rate"]["value"], .2)
        self.assertEqual(group["correct_unknown_handoff_rate"]["denominator"], 5)
        self.assertEqual(group["completed_unknown_handoff_rate"]["value"], .6)
        self.assertEqual(group["error_or_timeout_rate"]["value"], .4)
        # Legacy event frequency is retained but never treated as correctness.
        self.assertEqual(group["unknown_handoff_rate"]["value"], 1)

    def test_unknown_answer_without_handoff_and_asserted_label_are_not_handoffs(self):
        rows = [record("abstain", inspection_question_answer="unknown", alert_kind="none"),
                record("claims", inspection_question_answer="lying", alert_kind="unknown_handoff", alert_sim_s=5)]
        truths = {row["trial_id"]: truth(answerable=False) for row in rows}
        group = arm(rows, {}, truths)["by_answerability"]["false"]
        self.assertEqual(group["completed_unknown_handoff_rate"]["value"], 0)
        self.assertEqual(group["correct_unknown_handoff_rate"]["value"], 0)
        self.assertEqual(group["inappropriate_posture_assertion_rate"]["value"], .5)

    def test_missing_handoff_times_are_unknown_not_success(self):
        for overrides in (dict(alert_sim_s=None), dict(alert_sim_s=5, wall_latency_s=None)):
            with self.subTest(overrides=overrides):
                row = record(inspection_question_answer="unknown", alert_kind="unknown_handoff", **overrides)
                group = arm([row], {}, {"trial-1": truth(answerable=False)})["by_answerability"]["false"]
                self.assertEqual(group["completed_unknown_handoff_rate"]["value"], 1)
                self.assertIsNone(group["correct_unknown_handoff_rate"]["value"])
                self.assertEqual(group["correct_unknown_handoff_rate"]["identification_bounds"], [0, 1])

    def test_handoff_latency_uses_alert_timestamp_and_marks_wall_upper_bound(self):
        rows = [record("explicit", inspection_question_answer="unknown", alert_kind="unknown_handoff",
                       alert_sim_s=3, alert_wall_s=4, wall_latency_s=15),
                record("fallback", inspection_question_answer="unknown", alert_kind="unknown_handoff",
                       alert_sim_s=5, wall_latency_s=10),
                record("failed", inspection_question_answer="unknown", alert_kind="unknown_handoff",
                       status="error", alert_sim_s=8, alert_wall_s=18)]
        latency = arm(rows, {})["completed_unknown_handoff_latency"]
        self.assertEqual(latency["eligible_trials"], 2)
        self.assertEqual(latency["all_attempted_trials"], 3)
        self.assertEqual(latency["sim_s"]["value"], 4)
        self.assertEqual(latency["wall_s"]["value"], 7)
        self.assertEqual(latency["wall_upper_bound_trials"], 1)

    def test_subgroup_with_no_trials_is_null_not_zero(self):
        group = arm([record()])["by_answerability"]["false"]
        self.assertEqual(group["trials"], 0)
        self.assertIsNone(group["correct_unknown_handoff_rate"]["value"])
        self.assertIsNone(group["inappropriate_posture_assertion_rate"]["value"])
        self.assertIsNone(group["costs"]["wall_latency_s"]["value"])

    def test_invalid_answerability_and_alert_times_are_rejected(self):
        for value in (0, 1, "false", [], {}):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "answerable"):
                arm([record()], truths={"trial-1": truth(answerable=value)})
        for field, value in (("alert_sim_s", -1), ("alert_wall_s", float("nan"))):
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, "finite"):
                arm([record(**{field: value})])


if __name__ == "__main__":
    unittest.main()
