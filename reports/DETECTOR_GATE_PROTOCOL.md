# Independent RGB detector gate: two-arm evaluation protocol

작성일: 2026-11-08 (Asia/Seoul). 이 문서는 새 실행 **전** 평가 설계다. 실제 실행 manifest, 모델·검출기 digest, 임계값, 설정·코드 hash를 고정하기 전에는 사전 등록된 확정 실험으로 부르지 않는다. 기존 2026-11-07 개발 비교와 5장 사후 검토 프레임은 개발 자료이며 새 확인 결과에 합치지 않는다.

## 1. 검증 범위와 두 조건

질문: 같은 관측·이동 에이전트에 독립적인 RGB 사람 검출 veto를 추가하면, 실제 대상이 없는 근거를 인용한 자세 확정을 줄이면서 기한 내 근거 있는 자세 정답을 유지하거나 늘리는가? 감소량과 추가 비용은 아직 알려져 있지 않다.

| 조건 | 다른 점 | 공통 부분 |
| --- | --- | --- |
| `agent_gate_off` | 검출 결과로 VLM 근거를 거부하지 않음 | 같은 Qwen digest·영상/계획 요청 방식·프롬프트·도구·이동기·사건 기한·현재 host의 freshness/품질/종료 규칙 |
| `agent_gate_on` | 같은 RGB에서 독립 검출기의 허용 조건을 만족하지 못하면 해당 프레임으로 자세를 확정하지 않고 기존 재관측/인계 경로 이용 | 위와 동일; detector latency와 실패도 대응 기한에 포함 |

이것은 **TRACE 전체 대 일반 에이전트의 효과가 아니라 추가 검출 veto의 효과**다. 기존 host의 근거 만료 검사 등을 두 조건에 함께 남긴다. planner, prompt, Qwen API, 생성 길이, 카메라 각도와 근거 관리 규칙을 동시에 바꾸지 않는다. 검출기 confidence만으로 Qwen 자세 판단을 정답으로 바꾸지 않는다. 탐지 실패는 `person absent` 확정이 아니라 `not independently corroborated`다. 검출기 실행 오류도 성공 검출로 취급하지 않는다.

후보 모델·가중치·입력 해상도·person class·confidence/NMS 임계값·CPU/GPU·오류 처리·재관측 예산을 개발 자료에서 정하고 실행 전 고정한다. 동일 Qwen 내부의 재질의나 자기평가는 독립 검출 경로가 아니다. crop 재질의, 시점 일치, detector 교체는 이후 별도 실험으로 둔다. 현재 한 명인 대상 작업자 설정에서 사람 bbox를 사용하며, 교차 카메라 신원 추적이나 여러 사람 중 대상 식별을 검증했다고 주장하지 않는다.

현재 개발 구현은 단일 후보 조건(singleton)을 포함한다. 후보 0개 거부와 후보 여러 개로 인한 모호성 거부를 구분한다. 과거 빈 화면에서 여러 false-positive 후보가 나와 거부됐다면 "사람이 없음을 올바르게 검출했다"가 아니다. 빈 화면의 단일 false-positive는 통과할 수 있고, 실제 작업자와 배경 false-positive가 함께 나오면 유효 관측을 거부할 수 있다. 5장 사후 자료의 통과/거부 일치만으로 검출 신뢰성·closed-loop 향상을 주장하지 않는다. 임계값과 singleton 포함 여부가 개발 중 바뀌면 버전별로 기록하고, 향후 미사용 조건 평가 전에 하나로 고정한다.

구현상 detector timeout 또는 늦은 응답은 거부하고 그 adapter의 추가 검출 호출을 중지한다. native inference를 실행하는 Python thread 자체를 강제 종료하지는 못한다. 따라서 이는 결과 수용 기한이며 backend 정지 시 process 종료 시간의 상한 보장은 아니다. 정식 실행 전에 backend 응답성과 상위 실행기 종료 처리를 확인한다.

## 2. 방법과 평가 데이터의 경계

방법에 허용되는 입력: 동일 원본 RGB, 실제 센서 시각·camera/evidence id, 검출 bbox/confidence, 도구 실행 결과와 공개 이동 후보. 대상의 실제 좌표·자세·가시성·segmentation id·정답 파일명은 planner, Qwen, detector 및 host에 전달하지 않는다.

평가 전용 저장소: simulator의 대상 instance mapping과 RGB에 정확히 동기화된 visible segmentation, 실제 자세, 외부 RGB 검토. 평가 과정이 detector 출력을 정답으로 사용하면 안 된다. 평가 segmentation을 수집할 때는 두 조건에 같은 수집을 적용하고 동일 오버헤드를 포함하거나 동일하게 측정한다. 별도 평가 파일은 실행이 끝난 뒤 join한다.

검출기 통과는 사람 후보가 있다는 보조 관측일 뿐 자세 가독성의 충분조건이 아니다. visible target mask의 0 pixel은 유효한 렌더·ID mapping이 검증됐을 때에만 대상 부재로 채점한다. mask 오류·미수집은 `unknown`이다. 1 pixel 이상 보이는 것을 곧바로 읽을 수 있는 자세로 채점하지 않는다. mask area/fraction은 별도 보조량으로 기록한다.

최종 확정이 실제로 인용한 evidence id의 원본 RGB를 사용한다. 여러 근거를 인용했다면 전부 보존하며, 수동 판독자는 정책·모델 답·gate 통과 여부를 모른 채 같은 프레임 묶음에서 `lying / standing / unreadable`을 고른다. segmentation은 대상 존재 여부만 정하고, 자세가 판독되는지는 독립적인 사람 검토가 필요하다. 검토 전에는 `claim_observed_posture=null`이다. 애매해서 `unreadable`이라고 명시한 것은 결측과 구분한다. 동료 검토가 불가능하면 해당 지표는 미완료 또는 보조 검토 결과로 남기고 독립 검증이라고 부르지 않는다.

## 3. 실행 전 고정할 시나리오와 일정

개발 자료에는 기존 5장뿐 아니라 별도의 선명한 서 있음/누움, 부분 가림, 작은 대상, 빈 화면을 포함한다. 과거 빈 화면만 잘 막는 임계값을 고르지 않도록 실제 사람이 있는 프레임의 검출 누락을 같이 측정한다. 이 과정에 사용한 모든 프레임·장면은 development다.

새 초기 계획은 20개 조건 × 2개 조건 = 40회 paired 실행이다. 예: 자세 각 10개로 맞춘 **초기 영상에서 판독 가능 8개, 이동 후 판독 가능 8개, 허용된 위치에서 끝내 판독 불가 4개**. 이것은 제안 분포이며 live feasibility 확인 후 manifest에 확정한다. 모델/검출 결과를 보고 유리한 장면만 남기지 않는다. 이동 후 유효 시점이 항상 west에 몰리지 않도록 입구·서쪽·문 후보와 거리·가림을 분산한다. 문이 시야에 영향을 주면 한 상태를 사전 고정하고 각 시험 시작 시 실제 상태를 기록한다. 개폐 구동 복구는 이 ablation의 전제 조건이 아니다.

같은 배치의 standing/lying, 작은 좌표 변화, 반복은 독립 연구실이 아니다. 실제 배치 cluster id를 기록하고, 독립 배치 수와 조건 수를 따로 보고한다. 20개는 실행 규모이지 검정력 보장이 아니다. 렌더·이동 가능 여부의 preflight는 두 정책 결과를 보기 전에 하고, 실패한 preflight 및 배제 이유를 남긴다. Qwen/검출 출력에 의한 사후 배제는 하지 않는다.

각 시나리오의 같은 initial state·seed에서 두 arm을 paired 실행하고, AB/BA 순서를 균형화해 고정 seed로 섞는다. actor pose, Spot 출발 pose, 문·가림 상태, 카메라 설정과 초기 안정화 검사를 공통 적용한다. 초기화 오류는 별도 기술 실패로 남기고 조용히 재실행하지 않는다. 한 arm이 실패한 pair도 보존한다.

한국 시각 2026-11-10 화요일 밤을 발표 결과 반영 기준으로 둔다. 이 시각까지 closed-loop 결과와 독립 근거 판정이 끝나지 않으면 기존 개발 파일럿 및 구현/검증 수준을 보고한다. 2026-11-12 목요일 발표 전에 새 비교군을 추가하지 않는다. 40회 × 5분을 완료 보장으로 삼지 않는다. 2026-11-07 cohort에서 일부 실행은 8–10분 이상이었고 초기화·실패·검토 시간이 추가된다. 실행 중 자동 개선·조기 종료를 유리한 결과 선택에 사용하지 않는다.

## 4. 일차 지표: 모든 시도한 실행이 분모

**A. 대상 존재 근거 없는 확정 위험**

`인용 근거에 평가 대상이 없는데 lying/standing으로 최종 확정한 실행 / 모든 시도한 실행`.

이는 segmentation으로 평가할 수 있는 좁은 정의이며, 모든 종류의 "근거 없는 자세 판단"과 같지 않다. 대상은 보이지만 자세가 읽히지 않는 확정은 별도로 RGB 검토에서 드러난다. 잘못된 확정 뒤 timeout/error가 되어도 확정 사건은 지우지 않는다. 현재 terminal-record 평가는 최종 확정만 다루므로, 중간 확정을 여러 번 허용하면 event-level 모든 확정으로 분석을 확장해야 한다. Qwen의 거부된 원시 출력은 외부로 확정된 답과 구분하여 보조 분석한다.

보조로 `대상 존재 근거 없는 확정 / 모든 확정`도 보고한다. 확정하지 않는 정책이 유리해지므로 일차 지표를 이 조건부 비율로 대체하지 않는다.

**B. 기한 내 근거 있는 자세 정답률**

`실제 자세와 일치하고, 독립 RGB 검토가 그 자세를 판독할 수 있으며, 대상 존재와 인용 프레임이 확인되고, simulation 및 wall 기한 안에 완료된 실행 / 모든 시도한 실행`.

실제 자세 정답을 우연히 맞힌 빈 화면 답은 성공이 아니다. `unknown`, 미확인 인계, timeout, error는 성공 0으로 분모에 남는다. 전체 안전 확인으로 해석하지 않는다. 판독 가능한 조건만의 성공률은 별도 보조 결과로 표시하며, 그 subset은 결과를 보기 전에 외부에서 정한다.

annotation 결측/미판정은 0 오류 또는 1 성공으로 채우지 않는다. `N`개 전체 분모에서 확인된 양성 `k`, 판단에 필요한 annotation 미정 `u`라면 식별 가능 범위 `[k/N, (k+u)/N]`, annotation coverage, 미정 수를 함께 표시한다. 미정이 있으면 확정 점 추정은 `null`; 확인된 subset 비율은 별도다. 이 범위는 신뢰구간이 아니다. 사람이 `unreadable`로 판정한 경우와 아직 판정하지 않은 `null`은 다르다.

**C. 비용**

모든 성공·보류·실패 실행에 대해 전체 wall time, sim time, 샘플링한 XY 이동 거리, 실제 model call 수와 detector call 수, 계획/영상/검출 지연을 보고한다. tool call 수는 model call 수가 아니며 둘을 혼동하지 않는다. 취소된 호출도 누적 시간에 포함한다. 검출기 latency는 gate-on의 실제 추가 비용이다. gate-off 사후 detector audit를 실행하는 경우 온라인 비용에 합치지 않는다. 비용 결측은 0 대신 측정 분모와 누락 수를 표시한다.

미해결률, 미확인 인계, deadline miss, error, 검출 gate rejection 수를 함께 보고한다. 검출기가 사람이 있는 선명한 누움/서 있음 근거를 거부한 비율과 실제 재관측·시간 증가를 별도로 보여준다. 이는 gate의 관측 비용이며, 해당 거부가 없었다면 closed-loop가 성공했을 것이라는 인과 주장과는 다르다.

## 5. 통계와 결과 해석

두 arm의 절대 수치·차이·각 분모를 함께 제시한다. 동일 시나리오의 짝 차이를 사용하고 실제 배치 cluster 단위로 불확실성을 계산한다. 프레임이나 도구 호출을 독립 실험 수로 세지 않는다. 작은 한 연구실 비교를 실제 현장 일반성으로 확대하지 않는다. 결과 전에 비열등성 margin을 정하지 않았다면 "확인률 유지 입증"이라고 하지 않고 관측된 차이와 구간을 적는다.

목표는 두 지표와 비용의 tradeoff다. A만 줄고 B도 크게 감소하면 효과가 확인된 해결책이라고 단정하지 않는다. B만 높고 A가 증가하면 마찬가지다. 개선 없음 또는 악화도 그대로 보고한다. gate-on 결과를 본 뒤 threshold·장면·지표를 바꾸면 새 development 버전으로 구분한다.

## 6. 평가기 및 검증 수준

새 `src/haiclaw/detector_gate_metrics.py`는 기존 `comparison_records.normalize_report`의 record와 외부 평가 파일을 받는 standalone 표준 Python 평가기다. `comparison_metrics.py`의 일반 paired 비교를 대체하지 않는다. 새 평가기는 전체 분모, 기한, 근거 부재와 자세 가독성의 분리, 결측 범위, 비용 측정 coverage를 명시한다. paired bootstrap이나 자동 통계 유의성은 추가하지 않았다.

```python
from haiclaw.detector_gate_metrics import evaluate_gate

summary = evaluate_gate(
    records,
    external_truth_by_trial_id,  # actual_posture, relative deadline_sim_s, wall_budget_s
    support_annotations_by_trial_id,  # exact evidence_ids, target presence, human-readable posture
    expected_trial_ids=frozen_manifest_trial_ids,
)
```

annotation 예시: `{"evidence_ids": ["body-003"], "claim_target_present": true, "claim_observed_posture": "lying"}`. 미완료 검토는 `claim_observed_posture: null`이다. 다른 프레임 annotation을 join하면 평가기가 거부한다. 실제 답변 wall timestamp가 없으면 실행 전체 wall time을 보수적인 상한으로 사용하며 그 수를 표시한다. 정식 비교에서는 답변 wall timestamp도 기록하는 것이 좋다.

실행기가 저장하는 `person_gate_cost.calls`와 `person_gate_cost.latency_wall_seconds`는 평가기에서 각각 `detector_calls`, `detector_latency_s`로 읽는다. Qwen 추론 시간과 별개다. 두 표현을 동시에 제공했는데 값이 다르면 평가기는 거부한다.

검증 명령: `PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -p 'test_detector_gate_metrics.py' -v`. 이 파일과 테스트는 simulator·모델·검출기를 호출하지 않는다. 테스트 통과는 fixture 평가 로직 검증이며 실제 검출 성능·온라인 제어 효과를 뜻하지 않는다. 기존 파일럿 결과, 구현 가이드, 장면과 검출기 설정은 이 작업에서 수정하지 않는다.
