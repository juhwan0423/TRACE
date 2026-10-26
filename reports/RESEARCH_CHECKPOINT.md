# TRACE 중간점검 — 2026-10-27

## 결론

**개발·파일럿 실험: 시작 가능. 논문용 성능 비교: 아직 준비 부족.**

모델이 도구를 고르고 결과를 받아 재계획하는 실행 기반은 생겼습니다. 그러나 최신 코드의 전체 통합 재검증, 정상/위험/가림 조건의 반복 검증, 공통 평가기와 공정한 baseline 조건이 아직 없습니다. 현재 기록을 논문 결과표로 바로 쓰면 안 됩니다.

이번 점검은 소스·계약 테스트·기존 실행 기록 검토입니다. 새로운 문헌 novelty 조사나 새로운 대규모 물리 실험을 수행한 것은 아닙니다.

## 지금 시작할 수 있는 실험

- fixture 기반: 도구 실패, 취소, stale evidence, deadline, 잘못된 모델 action의 처리.
- 실제 Qwen + fixture 도구: action JSON 안정성, 선택/재계획 패턴, planner 지연.
- 제한된 실제 Isaac pilot: fresh image → model choice → motion → result → stop. 통합 오류와 관측 품질 탐색용.

현재 사용하면 안 되는 주장: 안전성이 검증됐다, 위험 탐지 정확도가 높다, 에이전트가 baseline보다 낫다, VSS보다 빠르다, 자율 에이전트 구조 자체가 새로운 논문 기여다.

## 논문 실험을 막는 항목

| 우선순위 | 문제 | 실험 시작 전 통과 기준 |
|---|---|---|
| P0 | 마지막 live 이후 도착 관측 gate/실패 viewpoint 상태를 수정 | 최종 commit을 고정하고 baseline/harness 각각 end-to-end 재실행, 정상 stop 및 evidence/audit 연결 확인 |
| P0 | 단일 프레임 adapter는 upright_active를 입증하지 못해 정상 안전 종료를 지원하지 않음 | 시간 구간/활동 근거의 operational definition과 공통 provider 구현·검증. 아니면 연구 과제를 '안전 종료'가 아닌 관측·인계로 명확히 한정 |
| P0 | live 검증은 누움 장면 소수 개발 실행; 다른 조건과 반복 부족 | 정상 작업/누움/가림/저화질, 위치·가림 정도·관측 실패를 분리한 고정 pilot 시나리오 manifest |
| P0 | 공통 batch runner와 평가기 없음 | 같은 입력/사건 시작/예산/센서/기한 규칙으로 정책만 교체, timeout·미종료도 모두 저장 |
| P0 | 초기 관측은 VLM 완료 뒤 사건을 생성; 지연 일부가 예산 밖 | truth 발생 시각은 평가기만 보유하고 관측/사건 생성/행동/알림 시각을 모두 기록. wall와 simulation 결과를 분리 |
| P1 | 모델 선택이 관측 없이 이동하거나 정보 없는 재관측을 반복 | decision validity, 새 정보 획득 여부, 반복 횟수, 호출 비용을 측정. 정책 수정은 평가 split과 분리 |
| P1 | runtime 파일/모델/설정·scene 버전이 결과마다 완전히 묶이지 않음 | 코드 commit+hash, config snapshot, 모델 digest, prompt/schema, seed/scene, 이미지 해시, 실행 조건을 run manifest에 저장 |
| P1 | 배포·설치가 현재 Spark에 맞춰짐 | 새 checkout에서 CPU smoke 확인, 별도 깨끗한 runtime 준비 경로 검증. GTK·Graphviz·Ollama·Docker 버전/설치 절차 명시 |

도착/종료 기록만으로 sensor correctness나 물리 안전성을 증명하지 않습니다. `completed=true`는 사건 상태가 종료됐다는 뜻이며, unknown도 포함합니다. `agent_cycle_exercised` 역시 정답 판정 성공률이 아닙니다.

## 최소 비교 설계 제안 — 아직 실행하지 않음

연구 질문 후보: **같은 기한과 이동·관측 예산에서, 사건 상태와 근거의 유효성을 사용하는 적응형 도구 선택이 불확실성을 줄이고 잘못된 종료를 억제하는가?** 문헌 대비 차별점은 별도 검증해야 합니다.

비교군:
1. Fixed-time handoff: 추가 이동 없이 같은 기한에 인계.
2. Fixed-route verification: 정해진 지점/순서 + 동일 VLM + 동일 evidence gate.
3. Adaptive harness: 동일 도구/후보/관측 provider/evidence gate, 다음 행동만 모델 선택.

기한·증거 gate가 다른 시스템을 비교해서 'agent 효과'로 해석하지 않습니다. 모델·렌더 품질·센서 수·이동 속도 차이도 통제합니다. VSS는 별도 영상 시스템 비교군이며 ROS 능동 이동 효과를 평가하는 직접 baseline과 섞지 않습니다.

Pilot 제안: 4개 상황 × 3개 배치 × 3개 정책 × 3회 반복 = 108 episode. 이는 테스트 인프라와 분산을 확인하기 위한 **제안**이지 통계적 충분성이나 사전 power 분석 결과가 아닙니다. 본 실험 반복수는 pilot 변동성과 효과 크기로 정합니다. 개발에 쓴 장면과 최종 평가 장면을 구분합니다.

필수 지표:
- 잘못된 안전 종료율 / 위험 누락률 / 불필요 인계율 / unknown 비율. 분모와 정답 정의 명시.
- 사건 발생→첫 관측, 사건 생성, 첫 유효 근거, 최종 판정까지의 wall 및 simulation 지연. timeout은 삭제하지 않음.
- 이동 거리, 도구/모델 호출 수, planner/vision/queue 시간, 모델 출력 오류, 예산 초과.
- scene/seed별 paired 결과 및 신뢰구간. 몇 개의 성공 영상이나 평균 하나로 결론 내리지 않음.

유효한 ablation 후보: 고정 선택 vs 적응 선택, episode memory 유무, post-arrival observation guard 유무. guard 제거 실험도 시뮬레이션에서만 하고 별도로 표시합니다.

## 좋은 GitHub 프로젝트로 가기 위한 작업

이번 체크포인트에서 현재 README, GPU 없는 CPU CI, fixture smoke 경로, 선별 실행 요약을 추가했습니다. 이전 머신 설명은 역사 문서로 이동했습니다.

남은 작업: 라이선스/third-party asset 권한 정리, 재현 가능한 runtime 설치와 버전 고정, 공통 experiment CLI 및 metric schema, 실패 포함 공개 가능한 작은 데이터셋, 독립 실행 가능한 예제와 짧은 데모, 영어 방법/제한 문서, 릴리스 태그와 changelog. LICENSE나 CITATION의 저자/라이선스 선택은 임의로 만들지 않습니다.

다음 구현의 우선순위는 대시보드 추가나 새 프레임워크 이식이 아니라 **고정 버전 통합 검증 → 공통 평가기 → 소규모 pilot**입니다. 문헌조사는 이 연구 질문과 baseline/측정 기준을 좁히는 범위로 진행하는 것이 적절합니다.
