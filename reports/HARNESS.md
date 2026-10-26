# TRACE harness v1

## 범위와 baseline

`implementation_guide.md`의 관측 소실 사건, 근거 기반 종료, 기한 유지, 추가 관측 요구를 실행 구조로 옮겼습니다. 기존 `scripts/run_closed_loop.py`와 `ClosedLoop`는 고정 순서 baseline으로 보존합니다. 새 `scripts/run_harness.py`는 별도 실행기입니다. baseline 대비 성능 개선은 아직 주장하지 않습니다.

현재 구현은 한 로컬 모델을 두 역할로 호출하는 단일 에이전트 하네스입니다. 행동 선택은 텍스트 planner, 영상 해석은 기존 VLM adapter가 담당합니다. MCP 서버, 다중 에이전트, 학습된 최적 정보획득 정책은 아닙니다.

## 실행 루프

1. live 모드는 실제 초기 관측 visible과 이후 observed loss를 확보합니다. 실험 시나리오 생성은 에이전트 외부입니다.
2. 사건을 열고 목표, 근거 이력, 이동 결과, 남은 sim/wall 예산, 현재 허용된 도구 목록을 모델에 전달합니다.
3. Qwen이 `{tool, target, reason}`을 반환합니다. 짧은 이유는 결정 설명이며 장문의 내부 추론을 요구하지 않습니다.
4. 하네스가 도구/대상 조합과 반복·단계 제한을 검증합니다. 임의 코드·좌표·토픽을 실행하지 않습니다.
5. 도구 결과를 기록하고, 근거로 사건이 해소되지 않으면 갱신된 상태로 다음 행동을 다시 선택합니다. 실패한 이동 대상은 해당 사건에서 제외됩니다.
6. 근거 규칙, sim deadline, wall watchdog이 종료를 관리합니다. 모델은 safe/danger를 직접 출력하는 도구를 갖지 않습니다.

## 도구 계약

| 도구 | 허용 입력 | 반환/효과 |
|---|---|---|
| observe | fixed / body | 새 센서 RGB와 시각 → VLM 관측 및 유효성 검사 |
| inspect | configs/harness.json의 지점 ID | 실제 Nav2 이동, arrived/failed/timed_out/cancelled |
| wait | 빈 target | 2 simulation초 대기 후 재판단 |
| stop | 빈 target | 이동 취소·hold, 사건 안전 종료 아님 |
| escalate | 빈 target | 미확인 로컬 인계 요청 |

확인 지점은 두 개의 고정 후보입니다. 자유 좌표 탐색이나 사람 정답 위치를 사용한 이동 선택은 아닙니다. `east_inspection`은 기존 검증 지점, `southeast_inspection`은 다른 각도의 후보입니다. 후보별 실제 도착 검증 여부는 live 기록을 기준으로 합니다.

## 상태·실행 제한

- 에피소드별 관측 기억(최근8개), 실행/실패 이력(최근8개)을 planner에 전달합니다. 전체 감사 로그는 따로 저장합니다.
- 이미지 파일 경로, 시나리오 이름, 사람 정답 좌표는 planner context에 전달하지 않습니다. 원본 evidence/추론은 호스트의 evidence_records에 보존합니다.
- 사건 생성 이후 기본 simulation 예산180초, wall 예산900초, 계획/관측 작업180초, 이동 작업600초, 최대12단계, 근거 최대 나이45 simulation초입니다. `configs/harness.json` 참조.
- 도착 후에는 해당 지점의 새 몸통 관측을 얻기 전 다음 이동을 선택할 수 없습니다. 이것은 모델의 불필요한 연속 이동을 막는 도구 사전조건이며, 어느 지점으로 갈지와 관측 후 행동은 모델이 선택합니다.
- 같은 행동 연속2회 후에는 해당 조합을 다음 선택 목록에서 제외합니다. 무효 출력3회, 도구 연속 실패3회는 미확인 인계합니다.
- 전체 예산이 남아 있는 도구 시간초과는 재계획 입력으로 돌립니다.
- 모델·도구 대기 중에도 시뮬레이션 시각과 기한을 확인합니다. 기한을 넘긴 응답은 적용하지 않습니다. reset/paused/통신 오류는 완료로 보고하지 않습니다.
- 종료·사용자 중단 시 stop을 요청합니다. stop 실패는 결과에 남기고 completed=false로 처리합니다.
- 실제 provider가 쓰는 HTTP worker는 취소 후에도 전송 timeout까지 남을 수 있습니다. 늦은 응답이 사건에 반영되지는 않지만 모델 자원이 즉시 회수된다는 보장은 없습니다.
- baseline과 하네스는 동일 파일 잠금으로 동시 실행을 막습니다. UI 수동 VLM 호출은 같은 Ollama 자원을 공유하므로 비교 실험 중에는 중복 호출하지 않는 조건으로 기록해야 합니다.

## 모델 호출 설정과 발견한 문제

첫 chat planner 실험은 `think=False`여도 생성 예산을 소진하여 최종 JSON이 비어 있었습니다. 무효 응답을 거부하고 기한에 unknown으로 종료했으며, 도구를 실행한 성공으로 세지 않습니다.

설치된 `qwen3-vl:8b`의 텍스트 planner에만 `/api/generate`, `raw=True`, Qwen assistant prefix의 닫힌 thinking 블록, JSON Schema, 출력512토큰을 적용했습니다. 이는 실제 로컬 요청으로 검증한 모델 전용 템플릿이며 다른 모델에 자동 적용하지 않습니다. context 안의 템플릿 시작 토큰은 이스케이프합니다. 이미지 VLM adapter/판정 규칙은 변경하지 않았습니다. [Ollama generate API](https://docs.ollama.com/api/generate)

실제 Qwen+fixture 실패 재계획 실행은 약8.07초에 끝났습니다. 이는 짧은 **텍스트 행동 선택과 가짜 도구**의 측정값이며 영상 분석 속도나 실제 보행 속도 개선을 뜻하지 않습니다.

## 실행

프로그램 **에이전트 실행** 탭에서 `실제 Isaac + Qwen`을 선택하고 **하네스 실험 시작**을 누릅니다. 기존 TRACE 세션이 준비되어 있어야 합니다. 이 버튼은 전용 실험 장면에서 초기 관측/가림을 시작합니다. **내 실행 중단**은 그 창이 실행한 하네스만 중단합니다.

터미널:

```bash
cd /home/juhwan/문서/ChatGPT/ROSCLAW/TRACE
source scripts/env_spark.sh
python scripts/prepare_closed_loop.py
python scripts/run_harness.py --mode live --planner ollama
```

실제 Qwen을 쓰되 물리 시뮬레이션 없는 도구 fixture 검증:

```bash
python scripts/run_harness.py --mode fixture --planner ollama --fail-first
```

완전 fixture 계약 검증:

```bash
python scripts/run_harness.py --mode fixture --planner fixture --fail-first
PYTHONPATH=src python -B -m unittest discover -s tests -v
```

## 결과와 검증 수준

- `artifacts/harness/<episode>/result.json`: mode, planner, 상태, agent_decisions/executed_tools, 관측, 감사 trace.
- `events.jsonl`: 단계별 append-only 기록. `bootstrap.json`: 초기 감지 근거.
- `artifacts/live/harness.jsonl`: 프로그램용 선택·실행 기록. UI 로그의 live/fixture를 구분합니다.
- completed는 사건의 종료 여부입니다. agent_cycle_exercised가 false이면 모델의 행동 선택이 실행된 것이 아닙니다. 위험 사건이나 정상 사건을 올바르게 판정했다는 정확도 지표도 아닙니다.
- 코어/계약/스트림/planner/하네스 테스트86개 통과. 이동 실패 후 재계획, 제한 근거 후 다른 지점 선택, 불법 도구 차단, 시간초과/리셋/취소, 늦은 응답 폐기, 모델 context 경로 제외를 포함합니다.
- 실제 Qwen + 도구 fixture: `505ab74c-3903-49cf-aedc-a27f8f7bdc70`. 첫 이동 실패 후 다른 지점 선택 및 도착 후 관측으로 종료. 실제 Isaac 보행으로 해석하지 않습니다.

## 아직 남은 연구/구현

단일 정지 프레임에서 정상 활동을 입증하지 못하므로 정상 안전 종료의 실증은 남아 있습니다. 시간 구간 관측/활동 검증이 필요합니다. 단일 모델의 두 역할이고 기억은 사건 범위입니다. 반복 실패의 전략 개선, 영상 품질, 후보 지점 설계, baseline과 공정한 반복 비교가 남아 있습니다. 현재 단계는 실행 가능한 하네스 구현과 동작 검증이지 방법론의 우월성 입증이 아닙니다.


## 실제 Isaac 통합 실행 결과

`c83e19de-077a-42d6-a979-ccc113d34d1b` (mode=live, planner=ollama): 모델 선택8회/도구 실행8회.

실제 body 관측 → east_inspection 이동·도착 → southeast_inspection 이동·실패 → fixed/body 재관측으로 이어졌습니다. 새 근거로 사건을 확정하지 못해 전체900wall초 예산에 unknown 종료하고 hold를 확인했습니다. 기록 종료는 약901.3초(정지/저장 포함)입니다. stop_error는 없습니다. 실제 선택·도구 실행·실패 피드백·기한 종료를 확인했지만 위험/정상 판정 정확도나 baseline 대비 개선을 입증한 것은 아닙니다.

이 실행은 도착 후 새 관측 없이 다른 위치로 이동하는 선택 및 재관측 반복이라는 결함을 드러냈습니다. 실행 기록을 소급 수정하지 않았습니다. **도착 후 body 관측 사전조건, 실패 이동 후 current_viewpoint 무효화는 이 실행을 관찰하며 보완한 코드**입니다. 최신 사전조건은 계약 테스트와 기록된 실제 도착 context에 대한 실제 Qwen 재질의로 확인했으며, 보완 후 전체 물리 폐루프 반복 검증은 별도입니다.

`final_state.json`과 `final_scene.usda`에 종료 상태를 저장했습니다. 새 실행에는 시작 시 `code_manifest.json`을 기록해 실행 중 소스 변경과 실제 로드 버전을 구분합니다.
