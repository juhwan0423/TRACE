# TRACE 실제 시뮬레이션 폐루프

## 실행

```bash
cd /home/juhwan/문서/ChatGPT/ROSCLAW/TRACE
source scripts/env_spark.sh
python scripts/prepare_closed_loop.py
python scripts/run_closed_loop.py --case lying_on_floor --budget 70
```

준비 명령은 TRACE 소유의 Spot/Nav2 세션만 재사용합니다. 서버가 없으면 새 전용 헤드리스 서버를 시작합니다. 다른 작업의 장면이나 TRACE 데모가 없는 기존 장면은 자동 교체하지 않습니다. Ollama 사용자 서비스 `trace-ollama.service`가 실행 중이어야 합니다. 같은 실행기를 중복 실행하면 파일 잠금으로 거부합니다.

`--case normal_work`와 `--case insufficient_view`도 시나리오 생성기에 제공됩니다. 이번 실제 통합 검증은 `lying_on_floor` 한 경우이며, 다른 경우의 성공을 주장하지 않습니다.

## 구성

1. 실제 고정 RGB와 Qwen3-VL로 사람이 보이는 초기 관측을 얻습니다.
2. 시나리오 생성기가 마네킹을 가립니다. 시나리오 이름·위치·정답은 모델이나 사건 정책에 전달하지 않습니다.
3. 새 고정 RGB에서 Qwen이 관측 소실을 보고하면 `LossTracker`가 사건을 생성합니다.
4. `ClosedLoop`가 Nav2 이동을 시작합니다. 공식 Spot 정책이 실제 관절·물리 보행을 수행합니다.
5. Nav2 성공과 실제 도착 위치/방향을 함께 검사한 뒤, 도착보다 늦은 센서 타임스탬프의 몸통 RGB를 저장합니다.
6. Qwen 관측을 `IncidentVLM`에 넣고 추론 중에도 시뮬레이션 시각의 사건 기한을 계속 처리합니다.
7. 확정에 필요한 근거가 부족하면 기한에 `escalated_unknown`으로 모의 인계합니다. 로봇 도착·사람 재발견·한 장의 서 있는 자세만으로 안전 종료하지 않습니다.

## 이번 검증

- 코어·계약 테스트: 61개 통과.
- 실제 새 영상의 Qwen 감지: visible → occluded.
- Nav2 실제 도착: 시작 약 (0.304, -3.258), 종료 약 (3.040, 1.231), XY 누적 경로 약 6.77m.
- 센서 시각: 도착 40.242s, 새 RGB 41.200s, 수신 41.242s.
- 실제 Qwen 후속 관측: person_visible=yes, posture=lying, 약 29.1초 wall latency.
- 모델이 pixelated texture를 관측 한계로 보고하여 위험 확정을 보류했고, 사건 시각 81.502s의 기한에 `escalated_unknown`으로 실제 종료했습니다. 판정 규칙을 성공에 맞춰 완화하지 않았습니다.
- 최종 로봇 속도는 약 0.00036m/s였고, 전용 시뮬레이션을 일시정지했습니다. 결과 폴더에 `final_scene.usda`를 저장했습니다.
- 실행 기록: `artifacts/closed_loop/263c92fc-bb26-492b-869d-d822a8e2e2ab/result.json`.

## 범위와 한계

마네킹은 절차적으로 만든 인물 모형입니다. 실제 사람 데이터/의학적 판단 검증이 아닙니다. Localization은 시뮬레이터 정답 위치이고, 장애물 입력은 PhysX collision ray입니다. 실제 하드웨어는 연결하지 않습니다. 단일 확인 지점·단일 후속 영상 정책이며, 불확실한 경우 추가 지점을 선택하는 정책은 아직 없습니다. 렌더링에 노이즈가 남아 Qwen이 영상 한계를 보고합니다.

최초 통합 시 오래 정지한 후 보행이 진행하지 못했습니다. 공식 `RobotPolicyRunner.initialize()`로 현재 물리 자세를 유지하면서 정책/actuator 내부 상태를 다시 초기화하도록 수정해 재개를 검증했습니다. 위치를 순간 이동시키는 `reset()`을 이동 시작에 사용하지 않습니다. 실패한 실행도 보존했으며, 해당 사건은 안전 종료되지 않았습니다.

사건 예산은 시뮬레이션 초입니다. 별도 wall watchdog은 서버 정지/정체 시 실행을 중단하고 로봇 정지를 요청합니다. 이런 중단은 완료나 안전 판정으로 보고하지 않습니다.

준비 스크립트의 기존 세션 재사용 경로는 실행 검증했습니다. 새 서버 생성 경로는 개별 구성 명령들의 실행 결과를 바탕으로 구성했으며, 단일 명령으로 처음부터 재시작하는 검증은 별도입니다.
