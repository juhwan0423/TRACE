# TRACE 비교 평가 규칙

`src/haiclaw/comparison_metrics.py`는 외부 정답을 받는 표준 Python 평가기입니다. 정책 실행·모델 호출·시뮬레이터 접근을 하지 않습니다. 기존 성공 사례는 기본적으로 `development`이며, 확인 실험 결과로 재분류하지 않습니다.

## 입력

```python
from haiclaw.comparison_metrics import evaluate

report = evaluate(records, ground_truth_by_trial_id,
                  expected_policies=["fixed_reference", "trace"],
                  bootstrap_samples=2000, seed=20261107)
```

`records`는 정책별 실행 기록 목록입니다. 시도한 실행은 실패·시간 초과도 반드시 한 행으로 남깁니다. 프레임이나 도구 호출마다 행을 만들지 않습니다.

| 필드 | 의미 |
| --- | --- |
| `trial_id` | 전체에서 고유한 실행 식별자 |
| `scenario_id` | 독립적으로 구성한 장면/사건 식별자. 같은 장면의 반복에는 같은 값을 사용 |
| `repetition_id` | 같은 장면의 대응 반복 식별자. 비교 정책끼리 일치 |
| `policy` | 정책명 |
| `inspection_question_answer` | `lying`, `standing`, `unknown`; `unobservable` 입력은 `unknown`으로 정규화 |
| `status` | `completed`, `timeout`, `error` |
| `safety_verdict` | `danger`, `safe`, `unknown`; 생략 시 `unknown` |
| `alert_kind` | `danger`, `unknown_handoff`, `none`; 생략 시 `none` |
| `alert_sim_s` | 사건에 관한 첫 모의 통지의 절대 시뮬레이션 시각. 통지 없으면 `None` |
| `end_sim_s` | 실행 종료의 절대 시뮬레이션 시각; 미기록이면 `None` |
| `tool_calls`, `distance_m` | 실행 전체 도구 호출 수와 이동 거리. 미기록은 `None` |
| `planner_latency_s`, `vision_latency_s` | 각각 실행 전체 계획·시각 추론의 누적 wall-clock 처리시간 |
| `wall_latency_s`, `sim_latency_s` | 실행 전체 실제 경과시간과 시뮬레이션 경과시간. 서로 대체하지 않음 |
| `verification_level` | `fixture`, `isaac_rendered` 등 검증 수준; 생략 시 `unspecified` |

시간·비용은 유한한 비음수 수치만 허용합니다. 누락 비용은 0으로 채우지 않습니다. 한 행의 통지 유형과 시각은 같은 이벤트를 가리켜야 합니다. 후속 통지 갱신을 분석하려면 별도 이벤트 평가가 필요하며, 이 스키마는 첫 통지만 평가합니다.

`ground_truth_by_trial_id`는 정책에 제공하지 않는 별도 평가 정답입니다.

| 필드 | 의미 |
| --- | --- |
| `actual_posture` | 실제 자세 `lying` 또는 `standing` |
| `answerable` | 정해진 조건·예산에서 질문에 답할 수 있는지 외부에서 결정한 bool |
| `expected_answer` | 선택 사항. 답할 수 있으면 실제 자세, 없으면 `unknown`; 모순 입력은 거부 |
| `condition` | 외부 실험 조건명. 실행 기록의 임의 조건명은 사용하지 않음 |
| `dangerous` | 외부 위험 여부 bool. `standing` 정답을 안전 종료 허가로 해석하지 않음 |
| `assertion_supported` | 최종 자세 단정이 확보한 근거로 뒷받침되는지 외부 판정; 미평가면 `None` |
| `safe_closure_supported` | 안전 종료를 지지하는 별도 외부 판정; 미평가면 `None` |
| `incident_start_sim_s`, `deadline_sim_s` | 사건 시작과 대응 기한의 절대 시뮬레이션 시각 |
| `danger_onset_sim_s` | 위험 발생 시각; 정의할 수 없으면 `None` |
| `discernible_observation_sim_s` | 구별 가능한 관측이 처음 존재한 시각; 정의할 수 없으면 `None` |
| `evaluation_role` | `development` 또는 사전에 지정한 `confirmatory`; 생략 시 `development` |

기존 `posture_label=unobservable` 입력은 실제 자세를 추정하지 않고 `answerable=False`로 변환할 수 있지만, 새 실행은 실제 자세와 관측 조건을 분리합니다. `assertion_supported`를 정답 여부만으로 채우면 안 됩니다. 우연히 정답을 맞힌 근거 없는 단정이 가능하기 때문입니다.

## 지표와 분모

- **답할 수 있는 사례의 해결률**: `completed`이면서 자세 정답인 수 / 모든 `answerable` 실행. `unknown`, 시간 초과, 오류를 분모에서 빼지 않습니다.
- **예상 응답 정답률**: 모든 실행 대상. 답할 수 없는 조건에서 완료된 `unknown`은 적절한 응답일 수 있습니다. 시간 초과·오류는 올바른 완료 응답으로 세지 않습니다. 이 지표만으로 정책을 순위 매기지 않습니다.
- **관측 불가능 조건에서의 단정률**: `lying` 또는 `standing` 단정 수 / 모든 `answerable=False` 실행. 실제 자세를 우연히 맞혀도 단정입니다.
- **틀린 자세 단정률**: 실제 자세와 다른 단정 수 / 실제 자세 정답이 있는 모든 실행.
- **근거 없는 자세 단정률**: `assertion_supported=False`인 단정 수 / 단정 없음 또는 근거 판정이 있는 실행. 근거 판정이 없는 단정은 제외 수와 `assertions_with_unknown_support`에 드러납니다. 결측을 근거 있음으로 바꾸지 않습니다.
- **미해결률**: 질문 답이 `unknown`이거나 실행 실패인 비율. 적절한 보류도 미해결입니다. 안전 판단의 `unknown` 비율은 별도 `safety_unresolved_rate`입니다.
- **위험 사례 미통지율**: 위험 발생 후 기한까지 통지하지 않은 수 / 모든 위험 실행. 기한의 미확인 인계도 통지로 세지만, 위험 확인으로 세지 않습니다. `dangerous_case_unconfirmed_rate`를 별도 보고합니다.
- **잘못된 안전 종료**: 위험 실행에서 `safe`를 낸 비율. 비위험 사례에서도 근거 없는 안전 종료는 별도 `unsupported_safe_closure_rate`로 계산합니다.
- **불필요 통지율**: 통지한 수 / 외부 비위험 실행. 위험 통지와 미확인 인계의 세부 지표도 분리합니다.
- **처리 비용**: 호출 수·거리·각 지연의 평균, 최소·최대와 실제 측정된 분모. 누락은 누락으로 남깁니다.

`danger_alert_latency_*`는 위험 발생 또는 구별 가능한 관측부터 **위험으로 분류된 통지**까지입니다. `unknown_handoff`는 이 위험 통지 지연에 포함하지 않습니다. 지연 평균은 위험 통지가 있는 사례만 포함하므로 반드시 미통지율·위험 미확인율과 함께 읽어야 합니다. 구별 가능한 관측보다 앞서 통지했다면 그 지연은 음수일 수 있으며, 숨겨서 0으로 바꾸지 않습니다.

위험 통지 없음·늦은 위험 통지를 기한까지의 비용으로 포함하는 `danger_alert_latency_capped_at_deadline_s`도 제공합니다. 미확인 인계만 한 경우에도 전체 기한 비용을 부여합니다. 이는 관측된 지연이나 생존분석 추정치가 아닌 **기한으로 제한한 위험 응답 비용**입니다. 위험 발생 시각이 없으면 이 비용을 만들지 않습니다.

각 지표에는 `value`, `denominator`, `missing_or_ineligible`가 있고 비율에는 `numerator`도 있습니다. 조건별 결과와 검증 수준·개발/확인 구분을 유지합니다. 출력에 `None`이 있으면 측정 근거가 없다는 뜻이며 0점 또는 완벽한 성능이 아닙니다.

## Harness 기록 정규화

```python
from haiclaw.comparison_records import normalize_report

record = normalize_report(
    harness_report, trial_id="trial-01", scenario_id="scene-01",
    repetition_id="repeat-01", policy="trace", condition="lying_occluded",
    verification_level="live_isaac_qwen",
    timings={"planner_latency_s": measured_planner_seconds,
             "vision_latency_s": measured_vision_seconds,
             "wall_latency_s": measured_total_seconds,
             "distance_m": sampled_xy_path_length})
```

`trace`의 `opened.sim_time`을 0으로 삼아 종료·통지·기한 시각을 변환합니다. 따라서 연속 실행에서 전역 시뮬레이션 시간이 달라도 같은 상대 기한으로 비교할 수 있습니다. 실행 전에 실패해 opening이 없다면 시뮬레이션 시각은 `None`으로 남고 실패 행은 보존됩니다. 외부 wrapper에서 확인한 실패는 선택 인자 `status="timeout"` 또는 `"error"`로 전달할 수 있습니다.

질문 답은 `inspection_answer`, 없으면 마지막 `context_snapshot`에서 읽습니다. `lying=false`는 앉음도 포함할 수 있으므로, 해당 근거가 유효하고 구체적으로 `standing`을 기록한 경우에만 `standing`으로 출력합니다. 근거가 만료·폐기·가림·누락됐거나 앉은 자세라면 `unknown`입니다. 자세 질문의 답을 안전 판정으로 승격하지 않습니다. 근거의 실제 정답 여부는 이 정규화기가 알지 못하며 외부 평가에서 다룹니다.

실제 전역 wall/sim 기한 종료는 `timeout`, 종결된 도구·계획 실패는 `error`입니다. 도중 실패 후 회복한 실행은 그 실패만으로 전체 오류로 바꾸지 않습니다. 단계 수 제한으로 정상 인계한 경우는 `completed`+`unknown`이지만 `normalization.resource_exhausted=True`를 남깁니다. 누적 추론 지연은 취소된 호출도 `finally`에서 측정한 wrapper 값이 필요합니다. 도착 성공, 계획한 경로 길이, 서버 응답 내부 duration으로 실제 이동 거리나 클라이언트 지연을 대신하지 않습니다.

현재 정규화는 첫 모의 통지를 평가합니다. 같은 시각의 `UNKNOWN→DANGER` 갱신은 같은 통지를 위험으로 정정합니다. 더 늦은 별도 위험 통지의 지연까지 분석하려면 후속 이벤트 스키마가 필요합니다. `comparison_complete`는 제공된 행들의 짝 완전성만 확인하므로, manifest의 두 정책 실행이 통째로 누락된 사례는 runner가 별도로 확인해야 합니다.

## 짝 비교와 불확실성

같은 `scenario_id`와 `repetition_id`의 두 정책 실행만 짝을 만듭니다. 대응 실제 자세·가능 여부·위험·기한·조건이 다르면 거부합니다. 누락 실행은 `missing_policy_a/b`에 기록하고 정책별 요약에는 존재하는 모든 실행을 유지합니다. `expected_policies`를 지정하면 한 정책 전체가 빠진 경우도 표시합니다. 누락이 있거나 비교 정책이 하나뿐이면 `comparison_complete=False`입니다.

먼저 각 독립 장면 안에서 반복별 B−A 차이를 평균하고, 그 장면 평균들에 같은 가중치를 부여합니다. 장면을 재표집하는 paired bootstrap의 2.5/97.5 백분위수를 보고합니다. **반복·프레임을 독립 표본으로 재표집하지 않습니다.** 장면이 하나뿐이면 점 차이는 보여도 신뢰구간은 제공하지 않습니다. 장면이 적을 때의 구간도 안정적인 모집단 보장을 의미하지 않습니다. 지표 여러 개의 구간에는 다중 비교 보정을 적용하지 않았습니다.

## 검증 기록

작업 지침 `AGENTS.md`, `implementation_guide.md` 및 설치된 Isaac agent guide/라우팅 색인을 읽었습니다. 이번 작업은 SDK에 의존하지 않는 평가기이므로 Isaac 실행 스킬을 적용하거나 GPU·렌더·ROS·모델을 호출하지 않았습니다.

실행 명령:

```bash
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -p 'test_comparison*.py' -v
```

평가기 18개와 정규화 14개 단위 fixture가 통과했습니다. 마지막 실행은 다른 모듈의 정책 fixture 13개와 runner fixture 5개도 포함해 총 50개가 통과했습니다. 시간 초과 분모, 관측 불가 보류, 안전과 자세 분리, 외부 근거 판정 누락, 늦은/없는 위험 통지, 조건 분리, 누락 짝, 반복의 가중치, 단일 장면 CI 억제, 상대 시각, 앉음/서 있음 구분, 실패 보존을 확인합니다. 이 테스트 통과는 실제 로봇·Isaac 렌더·VLM 성능 검증을 뜻하지 않습니다. 기존 실험 결과 파일과 구현 가이드는 변경하지 않았습니다.
