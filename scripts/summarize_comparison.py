"""Render existing comparison results; never re-evaluate, fit or call a model.

Usage: python scripts/summarize_comparison.py RUN_DIR --output-dir VIEW_DIR --figure
Only protocol.json, summary.json and records.json are read from RUN_DIR.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import json
import math
from pathlib import Path


def digest(data):
    return hashlib.sha256(data).hexdigest()


def cell(value):
    return str(value).replace("|", "\\|").replace("\n", " ")


def table(headers, rows):
    lines = ["| " + " | ".join(map(cell, headers)) + " |",
             "| " + " | ".join("---" for _ in headers) + " |"]
    lines.extend("| " + " | ".join(map(cell, row)) + " |" for row in rows)
    return "\n".join(lines)


def number(value, digits=2):
    if value is None:
        return "NA"
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError("Nonfinite/non-numeric value in saved summary")
    return f"{value:.{digits}f}"


def rate(metric):
    n = metric.get("denominator", 0)
    value = metric.get("value")
    return f"{metric.get('numerator', 0)}/{n}" + (f" ({value * 100:.1f}%)" if value is not None else " (NA)")


def cost(metric, total):
    return f"{number(metric.get('value'))} [n={metric.get('denominator', 0)}/{total}]"


def get_metric(policy, name):
    return policy.get("metrics", {}).get(name, {"value": None, "denominator": 0})


def support_rate_display(policy):
    """Keep the saved value visible without presenting unannotated support as zero."""
    saved = rate(get_metric(policy, "unsupported_posture_assertion_rate"))
    missing = policy.get("assertions_with_unknown_support", 0)
    if missing:
        return f"**주석 미완료({missing}건)**; 저장값 {saved} — 미지원 0건의 증거 아님"
    return saved


def load_inputs(directory):
    inputs, hashes = {}, {}
    for name in ("protocol.json", "summary.json", "records.json"):
        data = (directory / name).read_bytes()
        inputs[name] = json.loads(data)
        hashes[name] = digest(data)
    protocol, summary, records = (inputs[n] for n in ("protocol.json", "summary.json", "records.json"))
    if not isinstance(records, list) or summary.get("records") != len(records):
        raise ValueError("records.json and summary.json recorded-trial counts disagree")
    ids = [r["trial_id"] for r in records]
    if len(set(ids)) != len(ids):
        raise ValueError("Duplicate recorded trial IDs")
    schedule = protocol.get("schedule", [])
    planned = {row["trial_id"]: row for row in schedule}
    if len(planned) != len(schedule):
        raise ValueError("Duplicate planned trial IDs")
    for r in records:
        if r["trial_id"] not in planned:
            raise ValueError("Recorded trial absent from protocol schedule: " + r["trial_id"])
        for key in ("scenario_id", "scene_id", "repetition_id", "policy"):
            if key in planned[r["trial_id"]] and r.get(key) != planned[r["trial_id"]][key]:
                raise ValueError("Recorded schedule identity differs: " + r["trial_id"] + "/" + key)
    if "planned_trials" in summary and summary["planned_trials"] != len(schedule):
        raise ValueError("Saved summary and protocol planned counts disagree")
    if sum(p["trials"] for s in summary.get("strata", []) for p in s["policies"].values()) != len(records):
        raise ValueError("Summary stratum counts do not cover the recorded trials")
    actual_missing = set(planned) - set(ids)
    if "missing_planned_trials" in summary:
        declared_missing = {r["trial_id"] for r in summary["missing_planned_trials"]}
        if declared_missing != actual_missing:
            raise ValueError("Saved missing-planned markers disagree with files")
    return protocol, summary, records, hashes


def scope(protocol):
    manifest = protocol["manifest"]
    scenes = manifest.get("scenarios", [])
    clusters = {s.get("independent_group_id", s["scenario_id"]) for s in scenes}
    return manifest, len(clusters), len(scenes)


def stratum_rows(records, stratum, protocol):
    role = protocol["manifest"].get("evaluation_role", "development")
    if stratum["evaluation_role"] != role:
        raise ValueError("Summary evaluation role differs from the frozen protocol")
    return [r for r in records if r.get("verification_level", "unspecified") == stratum["verification_level"]]


def markdown(protocol, summary, records, hashes, *, fixture=False):
    manifest, clusters, scenes = scope(protocol)
    role = manifest.get("evaluation_role", "development")
    title = "SYNTHETIC FIXTURE — NOT EXPERIMENTAL RESULTS" if fixture else "TRACE 정책 비교 결과"
    lines = [f"# {title}", "", f"**평가 구분: {role}.** " +
             ("개발 실험이며 확인 실험의 성능 증거로 사용하지 않습니다." if role == "development" else
              "사전에 지정한 확인 실험 구분입니다. 이 표 자체가 통계적 유의성이나 우월성을 뜻하지 않습니다."), "",
             f"범위: **단일 연구실 환경의 {clusters}개 배치 cluster**, {scenes}개 자세/관측 조건 변형. "
             "같은 배치의 자세 변형·반복·프레임을 새로운 독립 환경으로 세지 않습니다. "
             "배치 간 재표집 결과를 여러 연구실로의 일반화 근거로 해석하지 않습니다.", "",
             "정적 자세를 배치한 검사 과제입니다. `lying`은 보이는 자세이며 실제 낙상·부상 진단이 아닙니다. "
             "`standing` 정답은 안전 확인이 아닙니다.", "",
             "**정답 라벨 일치와 화면 근거 지원은 별개입니다.** 아래의 판독 가능 조건 지표는 저장된 자세 답과 외부 라벨의 일치이며, "
             "RGB가 그 단정을 뒷받침하는지를 요구한 지표가 아닙니다. "
             "[별도의 사후 모델 보조 시각 감사](../visual_audit/visual_audit_final.md)를 함께 읽어야 합니다. "
             "이 포매터는 그 주석을 주 평가에 합치거나 저장된 수치를 바꾸지 않습니다.", "",
             f"계획 {len(protocol.get('schedule', []))}건 / 기록 {len(records)}건. "
             f"schedule_complete={summary.get('schedule_complete', 'unreported')}; "
             f"comparison_complete={summary.get('comparison_complete', 'unreported')}.", ""]
    missing = summary.get("missing_planned_trials", [])
    flags = summary.get("integrity_blocked_trials", [])
    if missing or flags:
        lines += ["**완료/무결성 주의:** 누락 또는 무결성 차단이 있습니다. 완료된 사례만으로 전체 계획의 성공률을 주장하지 않습니다.", ""]
    for label, entries in (("누락된 계획 실행", missing), ("무결성/정리 실패 표시", flags)):
        if entries:
            lines += [f"## {label}", "", table(["trial", "배치", "policy", "표시"],
                [[e.get("trial_id"), e.get("scenario_id"), e.get("policy"), ", ".join(e.get("markers", [])) or "MISSING"] for e in entries]), ""]
    for stratum in summary.get("strata", []):
        srows = stratum_rows(records, stratum, protocol)
        lines += [f"## {stratum['evaluation_role']} / {stratum['verification_level']}", ""]
        resolution, decisions, costs = [], [], []
        for policy, data in sorted(stratum["policies"].items()):
            rows = [r for r in srows if r["policy"] == policy]
            if len(rows) != data["trials"]:
                raise ValueError("Policy record count disagrees with summary: " + policy)
            status = Counter(r.get("status", "missing") for r in rows)
            m = data["metrics"]
            resolution.append([policy, data["trials"], rate(get_metric(data, "answerable_resolution_rate")),
                rate(get_metric(data, "expected_response_correct_rate")), rate(get_metric(data, "unresolved_rate")),
                f"{status['completed']} / {status['timeout']} / {status['error']}"])
            decisions.append([policy, sum(r.get("inspection_question_answer") == "standing" for r in rows),
                sum(r.get("inspection_question_answer") == "lying" for r in rows),
                sum(r.get("inspection_question_answer") == "unknown" for r in rows),
                sum(r.get("alert_kind") == "danger" for r in rows),
                sum(r.get("alert_kind") == "unknown_handoff" for r in rows),
                sum(r.get("safety_verdict") == "safe" for r in rows)])
            costs.append([policy] + [cost(get_metric(data, name), data["trials"]) for name in (
                "wall_latency_s", "sim_latency_s", "planner_latency_s", "vision_latency_s", "distance_m", "tool_calls")])
        lines += [table(["정책", "기록 n", "판독 가능 조건의 정답 라벨 일치", "예상 응답 정답", "미해결", "완료 / timeout / error"], resolution), "",
                  "정답 라벨 일치 지표의 분모에는 해당 조건의 unknown·시간 초과·오류를 포함합니다. 답할 수 없는 조건의 완료된 unknown은 예상 응답으로 맞을 수 있지만 여전히 미해결입니다. 화면 근거 지원은 별도입니다. NA는 분모가 없거나 미측정이라는 뜻입니다.", "",
                  table(["정책", "standing 답", "lying 답", "unknown 답", "위험 통지", "미확인 인계", "safe 판정"], decisions), "",
                  "자세 답·안전 판정·통지 유형은 서로 다른 축이며 합쳐서 성공 건수로 세지 않습니다.", "",
                  table(["정책", "wall s", "sim s", "계획 s", "시각 추론 s", "이동 m", "도구 호출"], costs), "",
                  "비용은 저장된 평균과 측정 분모입니다. 미측정값을 0으로 채우지 않았습니다. 정책별 평균은 실행 가중치이며 아래 짝 차이는 배치별 동일 가중치입니다.", ""]
        risk_rows = []
        for policy, data in sorted(stratum["policies"].items()):
            risk_rows.append([policy] + [support_rate_display(data) if name == "unsupported_posture_assertion_rate" else rate(get_metric(data, name)) for name in (
                "false_assertion_unanswerable_rate", "incorrect_posture_assertion_rate",
                "unsupported_posture_assertion_rate", "dangerous_case_miss_rate",
                "dangerous_case_unconfirmed_rate", "dangerous_case_wrong_safe_closure_rate", "false_alert_rate")])
        missing_support = sum(p.get("assertions_with_unknown_support", 0) for p in stratum["policies"].values())
        if missing_support:
            lines += [f"**근거 지원 주석 미완료: 동결된 주 평가에 자세 단정 {missing_support}건의 지원 여부가 없습니다.** "
                      "따라서 아래 저장된 `근거 없는 단정`의 0/x는 관측된 미지원 단정이 0건이라는 결과가 아닙니다. "
                      "미주석 단정이 제외된 불완전한 수치이며, 보조 시각 감사와 구분합니다.", ""]
        lines += [table(["정책", "관측 불가에서 단정", "틀린 자세 단정", "근거 없는 단정 (주석 범위 확인)", "위험 미통지", "위험 미확인", "위험→safe", "비위험 통지"], risk_rows), "",
                  "근거 유무는 별도 외부 주석이 필요합니다. 정답만으로 근거가 있다고 간주하지 않습니다. 미확인 인계는 기한 내 통지로 셀 수 있지만 위험 확인은 아닙니다.", ""]
        for policy, data in sorted(stratum["policies"].items()):
            if data.get("assertions_with_unknown_support", 0):
                lines.append(f"- {policy}: 근거 유무 미평가 단정 {data['assertions_with_unknown_support']}건; 근거 없는 단정률의 해당 분모에서 제외됨.")
        latency_rows = []
        for policy, data in sorted(stratum["policies"].items()):
            latency_rows.append([policy] + [cost(get_metric(data, name), data["trials"]) for name in (
                "danger_alert_latency_from_onset_s", "danger_alert_latency_from_discernible_s",
                "danger_alert_latency_capped_at_deadline_s")])
        lines += ["", table(["정책", "위험 통지: 검사 시작 기준 s", "위험 통지: 구별 가능 관측 기준 s", "기한으로 제한한 위험 응답 비용 s"], latency_rows), "",
                  "위험 통지 지연에는 미확인 인계를 포함하지 않습니다. 통지 없는 사례는 관측 지연 평균에서 빠지므로 위험 미통지·미확인율도 함께 읽습니다. 기한 비용은 관측 지연이나 생존분석 추정치가 아닙니다."]
        lines += ["", "### 조건별 정답 라벨 일치", ""]
        conditions = []
        for condition, data in sorted(stratum.get("by_condition", {}).items()):
            for policy, p in sorted(data["policies"].items()):
                conditions.append([condition, policy, p["trials"], rate(get_metric(p, "answerable_resolution_rate")),
                                   rate(get_metric(p, "false_assertion_unanswerable_rate")), rate(get_metric(p, "unresolved_rate"))])
        lines += [table(["조건", "정책", "n", "판독 가능 조건의 정답 라벨 일치", "관측 불가 단정", "미해결"], conditions), "",
                  "### 저장된 짝 차이", "",
                  "B−A 차이와 구간을 summary.json에서 그대로 옮겼습니다. 비율 차이는 percentage points입니다. 독립 배치가 적으므로 기술적 요약이며 유의성 검정·우월성 주장을 하지 않습니다.", ""]
        contrasts = []
        for pair in stratum.get("paired", []):
            for name in ("answerable_resolution_rate", "unresolved_rate", "dangerous_case_miss_rate", "wall_latency_s", "distance_m"):
                m = pair.get("metrics", {}).get(name, {})
                scale = 100 if name.endswith("_rate") else 1
                value = m.get("difference_b_minus_a")
                interval = m.get("bootstrap_95_interval")
                contrasts.append([f"{pair['policy_b']} − {pair['policy_a']}", name,
                    number(value * scale if value is not None else None),
                    "[" + ", ".join(number(x * scale) for x in interval) + "]" if interval is not None else "NA",
                    m.get("independent_scenarios", 0), m.get("paired_trials", 0)])
            for side in ("missing_policy_a", "missing_policy_b"):
                if pair.get(side):
                    lines += [f"**짝 누락:** {pair['policy_a']} / {pair['policy_b']} — {side}: " +
                              ", ".join(f"{x['scenario_id']}:{x['repetition_id']}" for x in pair[side]), ""]
        lines += [table(["비교", "지표", "B−A", "저장된 95% bootstrap", "배치 n", "짝 n"], contrasts), ""]
    lines += ["## 사례별 대응 기록", "",
              "아래는 정답 재평가가 아닌 원기록 표시입니다. 각 칸은 `질문 답; 실행 상태; 통지 유형; wall 초; 이동 m`입니다. 누락·실패도 보존합니다.", ""]
    policies = manifest.get("policies", [])
    scenes_by_id = {s["scenario_id"]: s for s in manifest.get("scenarios", [])}
    by_id = {r["trial_id"]: r for r in records}
    flagged_ids = {r["trial_id"] for r in flags}
    grouped = defaultdict(dict)
    for e in protocol.get("schedule", []):
        key = (e["scenario_id"], e.get("scene_id", e["scenario_id"]), e["repetition_id"])
        grouped[key][e["policy"]] = e
    paired_rows = []
    for (cluster, scene_id, repeat), entries in sorted(grouped.items()):
        scene = scenes_by_id.get(scene_id, {})
        row = [f"{cluster} / {scene_id} / {repeat}", scene.get("actual_posture", "unreported"),
               "답할 수 있음" if scene.get("answerable") is True else "답할 수 없음" if scene.get("answerable") is False else "unreported"]
        for policy in policies:
            e = entries.get(policy)
            r = by_id.get(e["trial_id"]) if e else None
            if r is None:
                row.append("**MISSING**")
            else:
                prefix = "**" + r["status"].upper() + "** " if r.get("status") != "completed" else ""
                if r["trial_id"] in flagged_ids:
                    prefix = "**FLAGGED** " + prefix
                row.append(prefix + "; ".join([r.get("inspection_question_answer", "unknown"), r.get("status", "unreported"),
                    r.get("alert_kind", "none"), number(r.get("wall_latency_s")), number(r.get("distance_m"))]))
        paired_rows.append(row)
    lines += [table(["배치 / 사례 / 반복", "외부 실제 자세", "외부 관측 가능성"] + policies, paired_rows), "",
              "## 재현 출처", "", "모델 호출·재학습·재평가·bootstrap 재실행 없이 세 입력 파일의 저장된 값만 표시했습니다. "
              "이 스크립트는 source snapshot이나 실행 무결성을 새로 인증하지 않으며 저장된 차단 표시를 전달합니다.", ""]
    lines += [f"- `{name}` SHA-256: `{sha}`" for name, sha in hashes.items()]
    return "\n".join(lines) + "\n"


def figure(protocol, summary, output, *, fixture=False):
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return dict(created=False, reason="matplotlib is not installed; no installation attempted")
    strata = summary.get("strata", [])
    if not strata:
        return dict(created=False, reason="no recorded strata to plot")
    manifest, clusters, _ = scope(protocol)
    panels = [("answerable_resolution_rate", "Correct posture label\n(answerable cases, %)", True),
              ("unresolved_rate", "Inspection unresolved (%)", True),
              ("wall_latency_s", "Mean wall time (s)", False),
              ("distance_m", "Mean traveled distance (m)", False)]
    fig, axes = plt.subplots(len(strata), 4, figsize=(14, 4 * len(strata) + 1.8), squeeze=False)
    colors = ["#4878a8", "#d68b45", "#649c75", "#8d75ad"]
    for i, s in enumerate(strata):
        policies = sorted(s["policies"])
        for j, (name, label, percent) in enumerate(panels):
            ax = axes[i][j]
            vals = [get_metric(s["policies"][p], name) for p in policies]
            numbers = [m.get("value") * (100 if percent else 1) if m.get("value") is not None else None for m in vals]
            upper = 110 if percent else max([v for v in numbers if v is not None] + [1]) * 1.25
            for k, (m, value) in enumerate(zip(vals, numbers)):
                if value is not None:
                    ax.bar(k, value, color=colors[k % len(colors)], width=.65)
                    txt = f"{m.get('numerator', 0)}/{m.get('denominator', 0)}" if percent else f"{value:.1f}\nn={m.get('denominator', 0)}"
                    ax.text(k, value + upper * .025, txt, ha="center", va="bottom", fontsize=9)
                else:
                    ax.text(k, upper * .05, "NA\nn=0", ha="center", fontsize=9)
            ax.set_ylim(0, upper)
            ax.set_xticks(range(len(policies)), [p.replace("_", "\n") for p in policies])
            ax.set_title(label, fontsize=11)
            ax.spines[["top", "right"]].set_visible(False)
            if j == 0:
                ax.set_ylabel(s["evaluation_role"] + "\n" + s["verification_level"])
    title = "SYNTHETIC FIXTURE — NOT EXPERIMENTAL RESULTS" if fixture else "TRACE policy comparison — " + manifest.get("evaluation_role", "development")
    if not summary.get("comparison_complete", False):
        title += "\nINCOMPLETE OR FLAGGED — see report before interpreting"
    fig.suptitle(title, fontsize=14)
    status = f"Recorded {summary.get('records', 0)}/{summary.get('planned_trials', len(protocol.get('schedule', [])))}; comparison_complete={summary.get('comparison_complete', False)}"
    status_counts = defaultdict(lambda: [0, 0])
    for stratum in strata:
        for policy, p in stratum["policies"].items():
            status_counts[policy][0] += get_metric(p, "timeout_rate").get("numerator", 0)
            status_counts[policy][1] += get_metric(p, "error_rate").get("numerator", 0)
    failures = "; ".join(f"{p}: timeout={v[0]}, error={v[1]}" for p, v in sorted(status_counts.items()))
    missing_support = sum(p.get("assertions_with_unknown_support", 0) for s in strata for p in s["policies"].values())
    support_note = (f"Frozen summary support annotation incomplete: {missing_support} posture assertions unannotated; a saved zero is not evidence of no unsupported assertions."
                    if missing_support else "Support annotation coverage must be read separately from label agreement.")
    fig.text(.02, .025, f"{clusters} placement clusters, one lab. {status}.\n"
             f"{failures}.\nSaved summaries only; no significance/superiority claim. Standing is not a safe verdict. Missing measurements stay NA.", fontsize=9)
    fig.text(.02, .135, "Correct posture label does not establish RGB evidence support; see the separate posthoc visual audit.\n" + support_note, fontsize=8.4)
    fig.tight_layout(rect=(0, .24, 1, .89))
    path = output / "comparison_figure.png"
    fig.savefig(path, dpi=180)
    plt.close(fig)
    return dict(created=True, path=str(path))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--figure", action="store_true", help="Create a static PNG only if matplotlib is installed")
    parser.add_argument("--fixture", action="store_true", help="Watermark synthetic validation inputs as non-experimental")
    args = parser.parse_args()
    run_dir, output = args.run_dir.resolve(), args.output_dir.resolve()
    protocol, summary, records, hashes = load_inputs(run_dir)
    fixture = args.fixture or bool(protocol.get("fixture_only") or protocol.get("manifest", {}).get("fixture_only"))
    text = markdown(protocol, summary, records, hashes, fixture=fixture)
    output.mkdir(parents=True, exist_ok=True)
    report_path = output / "comparison_report.md"
    report_path.write_text(text, encoding="utf-8")
    plot = figure(protocol, summary, output, fixture=fixture) if args.figure else dict(created=False, reason="not requested")
    for name, expected in hashes.items():
        if digest((run_dir / name).read_bytes()) != expected:
            raise RuntimeError("Input changed during report rendering; rerun on a stable summary")
    provenance = dict(input_directory=str(run_dir), source_sha256=hashes, fixture_only=fixture,
                      no_re_evaluation=True, no_model_calls=True, figure=plot)
    (output / "render_manifest.json").write_text(json.dumps(provenance, indent=2) + "\n")
    print(json.dumps(dict(report=str(report_path), figure=plot, fixture_only=fixture)))


if __name__ == "__main__":
    main()
