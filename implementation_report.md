## 2026-10-26 Gemini Robotics ER 2 관측 연결 — 현재 상태

`gemini-robotics-er-2-preview` API 어댑터, 요청한 6필드 strict schema, 비동기 사건 관리자 연결 및 입력/결과 HTML을 추가했다. 단일 이미지의 사람 재발견/standing/seated만으로 안전 종료하지 않는다. 명확하고 한계 없는 lying만 위험 조건으로 전달하며 나머지는 기한에 unknown 인계한다. 이전 episode/motion 응답 거부, 기한 중 timer 진행, schema/서버/timeout 오류 및 중복 요청 회귀 포함 전체 **56 tests 통과**. API wire 검사는 fixture다.

실제 Nav2 도착 1회(arrival 31.542s) 이후 정적 인체 모형의 작업대 포즈·바닥 누움·가림판 세 장면을 실제 몸통 카메라로 촬영했다. capture=31.766666667/31.966666667/32.166666667s, 위치·yaw 기준 통과. 임시 장면을 제거하고 기존 proxy visibility 복원 확인. 사실적 사람/세 번의 독립 이동 검증이 아니다.

**실제 API 호출 0회, 모델 응답·지연·최종 판정은 키 입력 후 검증 필요.** 현재 CLI는 저장된 도착 근거를 사건 관리자에 1배속 wall-clock으로 재생한다. 실시간 Kit 사건 루프의 자동 API 연결은 아직 없다. 실제 결과를 fixture로 대체하지 않았다. 사용자가 `GEMINI_API_KEY`와 `--allow-api`를 지정하면 세 영상에 대해 실행한다. [vlm_report.md](vlm_report.md)에 명령, 종료 규칙, 사용 skills, 실패, 검증 수준 및 미해결 항목을 기록했다. 아래 기록은 이전 단계의 이력이다.

## 2026-10-26 Nav2 실제 연결 및 도착 후 새 영상

기존 Jazzy Docker를 보존한 `haiclaw-nav2:jazzy` 이미지와 GUI Nav2 통합을 추가했다. 실제 도착+새 RGB 성공 run은 `artifacts/nav2/1792984808819520772`이며 위치 .177744 m, yaw .080316 rad, capture 34.133333333 s > arrival 33.182 s, stop residual .006647 m로 사전 기준을 통과했다. 실제 영상에 사람 대체 캡슐이 보인다.

중간 GUI Reset 재시험은 실측 .255245 m로 실패했다. 이후 Smac Hybrid-A* + RPP lookahead .3 m / stateful=false로 조정했고 최종 동일 목표 GUI Reset 2회가 연속 통과했다. 위치 오차 .092373/.093260 m, yaw .086967/.098312 rad, 정지 잔여 .002705/.003952 m. 최종 run은 `1792985258921926274`, `1792985384306864306`이며 각 새 RGB/계획 경로/telemetry/verification.json을 저장했다. 임의 목표의 일반적 안정성까지 주장하지 않는다. 각 실패/후속 조정/최종 상태 및 GUI 명령은 [nav2_report.md](nav2_report.md)에 기록한다. Localization은 시뮬레이션 ground-truth, 장애물 scan은 PhysX collision rays이며 AMCL/SLAM/실제 LiDAR 검증과 다르다.

Fixture 41개 통과. ROS 연결 상태 기존 보행 회귀 2회와 실제 policy-sink 명령 만료 시험 통과. guide/공식 설치/기존 Docker 원본 보존. 아래 내용은 이전 단계의 역사적 검증 기록이다.

# 구현 및 검증 보고 — 2026-10-23

## 2026-10-26 Spot GUI 보행 — 최신 결과

공식 Spot PhysX 정책으로 빈 바닥 보행·회전·정지와 Reset 재실행, 가림 장면 waypoint 보행을 실제 검증했다. 상세 기준·측정·사용 skills·명령·미검증 항목은 [spot_report.md](spot_report.md)에 있다. 공식 설치 파일과 implementation_guide.md는 변경하지 않았다.

- 실제 모델/환경/descriptor/USD 로딩 확인. 500 Hz 물리, decimation 10, 50 Hz 렌더/정책; 공식 runner의 관측·행동·gains 사용.
- 빈 바닥 전진 평균 0.23183m/s, 회전 0.31524rad/s, 정지 잔여 0.01380m. Reset 후 동일 결과, 9500 engine step에 callback 9500회.
- 가림 장면 목표 오차 0.20772m, 정지 잔여 0.00960m, 실제 보행 도착. 몸통 카메라 /World/Spot/body에 부착.
- 중간 캡처의 타임라인 pause로 첫 Reset 재검증이 timeout. 실패 로그 보존 후 캡처 없이 재검증 통과. 기준 완화 없음.
- 사용자가 GUI를 직접 닫았다고 확인했고 재실행하지 않았다. 마지막 별도 Stop→Play 검사는 연결 실패로 미실행. Reset 내부 Stop/Play 검증은 통과.
- 현재 단위 테스트 33개 통과. 실제 Spot 증거는 artifacts/spot 아래에 별도로 있다. ROS/Nav2/YOLO/VLM은 추가하지 않았다.


## 2026-10-23 코어 결함 수정 기록

요청된 네 가지 코어 문제를 수정했다. 전체 테스트 **29개 통과, 실패·skip·expected failure 0개**. 이 중 28개는 합성 근거를 사용하는 코어/비동기 회귀 테스트이고 1개는 이전에 저장한 실제 렌더링 결과 파일 검사다. 이번 작업에서는 Isaac Sim을 실행하거나 장면·ROS 코드를 변경하지 않았다.

실행 명령:

```bash
PYTHONPATH=src python3 -B -m unittest discover -s tests -v > artifacts/logs/core_regression_tests.txt 2>&1
```

결과: `Ran 29 tests in 0.017s`, `OK`. 로그: `artifacts/logs/core_regression_tests.txt`. 기존 expected-failure 2개는 일반 회귀 테스트로 전환했다. 아래의 5 통과/2 expected failure 기록은 수정 전 실험 이력이다.

### 적용한 전이 규칙

1. **관측 순서와 세대**: LossTracker는 visible뿐 아니라 occluded/unavailable를 포함한 모든 수락 관측의 capture_time을 갱신한다. 같은 시각/과거 관측은 history·last·lost를 변경하지 않는다. 단일 카메라/subject/track 스트림에 결속하며 다른 source는 재관측으로 취급하지 않는다. episode/generation을 검증하고 reset마다 generation을 증가시킨다. loss_sequence는 해당 세대에서 소실 사건마다 증가한다. 식별 키는 `(episode, generation, loss_sequence)`로 사용할 수 있다. 새 visible이 tracker의 lost를 해제해도 Incident의 안전 종료를 뜻하지 않는다.
2. **출처별 근거 유효성**: `latest_by_source`는 수신한 근거의 최신 촬영 시각, `latest_valid_by_source`는 품질·관련성·가시성·충분성·판정 참조를 통과한 결론 가능한 근거의 최신 촬영 시각이다. 위험 판정의 역순 검사는 후자에 대해 source별로 수행한다. 다른 카메라나 같은 카메라의 최신 저품질/불충분 프레임은 유효한 위험 근거를 막지 않는다. 동일 source의 더 최신 유효 근거가 있으면 과거 근거는 거부한다. 안전 종료에는 여전히 도착 이후의 새 프레임과 전역 최신성 검사를 요구한다. 같은 프레임의 재처리·ID 별칭은 독립 근거가 아니다.
3. **이동 시도**: moving은 새 motion_attempt를 만들고 arrived_at을 무효화한다. failed/timed_out/cancelled도 이전 도착을 무효화한다. 실패한 시도의 늦은 arrived는 거부하며, 새 시도는 moving으로 시작한다. 비동기 콜백은 반환된 attempt_id를 전달해야 이전 시도의 응답을 차단할 수 있다. 중복 arrived는 도착 시각을 다시 쓰지 않는다.
4. **기한 우선순위**: 처리 시각 now < deadline에서는 유효한 위험 근거를 즉시 신고한다. now == deadline에서는 유효한 위험 근거가 UNKNOWN보다 우선한다. tick이 먼저 UNKNOWN을 만들었어도 동일 시각 accept가 DANGER로 보정하며 `alert_update=true`, `local_alert=false`로 기존 신고 갱신 이력을 추가한다. 새 신고 수는 1개다. 안전/불충분/오래된/잘못된 세대 근거는 기한을 넘겨 안전 종료할 수 없다. now > deadline에서는 위험이 나중에 도착해도 이번 사건의 기한 결과를 소급 변경하지 않는다.
5. **비동기 판정**: VLM 캐시 키에 generation을 포함했다. 이전 세대의 in-flight 응답은 원래 Evidence와 함께 전달되어 Incident에서 거부된다. mock VLM 대기 중 tick 진행/timeout에도 UNKNOWN 인계가 유지되는 것을 실행 검증했다. 실제 추론 서버 호출은 없다.

### 변경 파일과 통합 조건

`src/haiclaw/core.py`, `src/haiclaw/providers/perception.py`, `src/haiclaw/providers/vlm.py`, `tests/test_core.py`, README 및 보고/작업 기록만 변경했다(테스트 로그 추가).

공급자는 캡처 또는 요청 시점에 episode/generation을 저장하고 비동기 응답에 원래 Evidence를 결합해야 한다. reset 후 응답에 현재 generation을 덧씌우면 안 된다. Incident 생성 시 해당 generation을 전달한다. 기존 최초 에피소드 호출은 generation=0 기본값으로 호환된다. 전체 사건 실행기/타이머 스케줄러는 여전히 미구현이므로 자동 폐루프 전체 검증으로 해석하지 않는다.

## 이전 카메라 실험 완료 범위

공식 skill 연결과 작은 장면의 고정 카메라 가림 → 이동 카메라 추가 관측을 구현했다. 전체 HAI-CLAW MVP/P1 완료를 의미하지 않는다.

- `AGENTS.md`: 설치된 공식 지침/skill 경로, 단계별 읽기, pip 설치 원칙, GUI 보존 규칙.
- `scripts/start_sim_server.sh`: workspace 전용 headless Python Server, loopback, ROS 자동 로딩 차단, 기존 리스너 보호.
- `scripts/build_scene.py`: 평면, 설비 상자, 사람 대체 캡슐, 조명, PhysicsScene 및 정적 충돌, RtxCamera/CameraSensor 2대.
- `scripts/occlusion_demo.py`: 서버 내부 실행, 소유 세션 검사, 기존 stage 백업, 진입/가림/카메라 이동/캡처, USD 및 수치 결과 저장.
- `scripts/run_occlusion.py`: 공식 remote client를 호출하는 실행 CLI.
- `tests/test_core.py`: fixture 회귀 검사. 최초 expected-failure 2개는 이번 수정으로 일반 테스트로 전환했다.
- `tests/test_occlusion_artifacts.py`: 실제 캡처 결과 파일 검증. 이 테스트 자체가 시뮬레이터를 실행하는 것은 아니다.
- README, 환경 보고, WORKLOG: 명령, 결과, 제한, GUI 절차.

## 실제 검증 결과

실제 Isaac Sim 6.2.0-rc.14 / RTX 카메라 / 1280×720 RGB, 5장 모두 파일 생성 및 비검정 검사. 진입·가림·측면 재관측 이미지 직접 시각 확인.

| 단계 | 카메라 | 대상 렌더러 분할 픽셀 수 |
|---|---|---:|
| 진입 양성 대조 | 고정 | 13229 |
| 설비 뒤 가림 | 고정 | 0 |
| 이동 전 | 이동 | 0 |
| 측면 이동 후 | 이동 | 36178 |
| 측면 이동 후 | 고정 | 0 |

첫 실행 RGB 평균 163.22–175.60, 표준편차 44 이상, PNG 각각 약 2.7 MB(무압축 저장). 결과 JSON `passed=true`. 단순 장면이라 validator의 권장 평균 80–160보다 밝지만 검정/무변화 이미지가 아니고 가림 대상 식별이 명확하다. timeline 읽기 시각 4.35–7.42초. 정적 장면 렌더링이지 동적 보행 안정성 테스트가 아니다.

자료: `artifacts/occlusion/results.json`, `results_first.json`, `scene.usda`, PNG 5장, 시작 전 stage 백업. `session.usda`는 첫 세션 종료 전 save_as_stage로 추가 저장했다.

## 공식 skill 및 API 대조

사용: isaac-sim-orchestrator, isaac-sim-assets, physics-simulation, isaac-sim-sensor, isaac-camera, isaac-sim-remote, isaac-sim-validator, isaac-sim-troubleshooting, skill-distillation. 파일 기반으로 필요한 순서에 따라 읽었으며 전체 라이브러리 일괄 로드는 하지 않았다.

참조 예제/문서(모두 설치 루트 기준):
- `skills/isaac-sim-sensor/scripts/create_camera_sensor.py`
- `skills/isaac-sim-remote/references/workflows.md`
- `skills/isaac-sim-remote/scripts/{health_check,open_stage,shutdown_app,isaacsim_send}.py`
- `exts/isaacsim.code_editor.python_server/docs/{Overview,SETTINGS}.md`
- `exts/isaacsim.sensors.experimental.rtx/isaacsim/sensors/experimental/rtx/impl/camera_sensor.py`
- 동일 경로 `tests/test_camera_sensor.py`
- `isaacsim/__init__.py` 및 `exts/isaacsim.app.setup/isaacsim/app/setup/startup.py`

공식 API 검증: RtxCamera + CameraSensor, 해상도 (height,width), get_data()의 (Warp 배열, metadata) 반환값, semantics.add_labels를 설치 소스/테스트와 대조하고 실제 실행했다. 캡슐·설비는 로컬 USD primitive/UsdPreviewSurface여서 외부 자산 루트나 전역 asset profile을 변경하지 않았다.

기존 src/haiclaw 코드는 Isaac API 호출이 없으므로 이름 변경 대상은 없다. 실제 camera provider와 incident core 연결은 아직 없다.

## 실제 명령 및 로그

```bash
# 작업 디렉터리 /home/jude/isaac_ws_61/haiclaw_ws
bash scripts/start_sim_server.sh > artifacts/logs/server.log 2>&1
python3 /home/jude/isaac_ws_61/IsaacLab/.venv/lib/python3.12/site-packages/isaacsim/skills/isaac-sim-remote/scripts/isaacsim_send.py --timeout 30 --file /home/jude/isaac_ws_61/IsaacLab/.venv/lib/python3.12/site-packages/isaacsim/skills/isaac-sim-remote/scripts/health_check.py
python3 /home/jude/isaac_ws_61/IsaacLab/.venv/lib/python3.12/site-packages/isaacsim/skills/isaac-sim-remote/scripts/isaacsim_send.py --context haiclaw --timeout 180 --execution-timeout 170 --args-json '{"workspace":"/home/jude/isaac_ws_61/haiclaw_ws"}' --file scripts/occlusion_demo.py
PYTHONPATH=src python3 -B -m unittest discover -s tests -v
bash /home/jude/isaac_ws_61/IsaacLab/.venv/lib/python3.12/site-packages/isaacsim/skills/isaac-sim-validator/scripts/validate_sim.sh --level 1 scripts/build_scene.py
```

첫 launcher 수정 전에는 소유 표시가 없어, 해당 작업에서 만든 서버에 한해 `carb.settings.get_settings().set('/haiclaw/workspace', workspace)`를 공식 client로 설정했다. 최종 launcher는 시작 플래그로 설정한다.

단위 검사 7개: 5 통과, 2 expected failure. 이전 읽기 전용 세션에서 실행한 19개 메모리 테스트와 이번 저장된 테스트를 혼동하지 않는다.

공식 정적 validator는 **실패(오류 2, 경고 1)**: build_scene 모듈에 SimulationApp 생성·close가 없기 때문이다. remote 모듈의 의도된 구조이므로 억지로 다른 app을 생성하지 않았다. Python syntax 검사는 통과. top-level await 파일은 `compile(..., flags=ast.PyCF_ALLOW_TOP_LEVEL_AWAIT)`로 별도 통과. 공식 도구 전체 통과로 보고하지 않으며, 실제 remote health/캡처 계약/이미지 QA를 별도 증거로 제시한다.

## 미해결 사항 및 다음 단계

1. 요청된 코어 결함 4종은 수정·회귀 검증 완료. 남은 것은 실제 공급자와 실행기에서 generation/attempt_id를 전달하고 타이머를 구동하는 통합 작업이다.
2. 실험에는 사람 대신 정적 캡슐, 로봇 대신 이동 카메라를 사용했다. 보행/사람 탐지/YOLO/VLM/ROS/Nav2는 검증하지 않았다.
3. 센서 메타데이터가 빈 dict였다. sim_time_at_read는 취득 시각이며 실제 센서 capture timestamp 보존 검증은 미완료다.
4. 카메라 실험은 고정 배치이며 configs/scene.json과 연결되지 않았다. seed=7은 기록값이고 난수 실험·정상/쓰러짐 분기 평가가 아니다.
5. 전체 사건 폐루프, 평가 JSONL/CSV, 동일 예산 정책 비교는 미구현이다.
6. GUI 확인은 README 절차에 따라 사용자와 함께 수행한다. 이번에는 기존 사용자 GUI 변경 없이 별도 headless 세션에서 검증했다.

## 종료와 학습 기록

첫 전용 프로세스 PID 119181은 official shutdown helper의 post_quit 요청 두 번 뒤에도 남았다. session.usda 저장 성공을 확인하고 이 작업에서 시작한 PID에만 `kill -TERM 119181`을 보냈으며 종료코드 0을 확인했다. 다른 인스턴스 종료/전역 프로세스 kill은 하지 않았다. 종료 전 8226 점유 상태에서 재실행 시도는 launcher가 안전하게 거부했다.

Skill 개선 제안만 기록: camera skill의 get_data 예제에 tuple 반환/워밍업 None 처리를 명시하고, validator에 remote-module 모드를 구분하면 좋다. 공식 skill 파일은 사용자 지시에 따라 수정하지 않았다. source-build와 pip 실행의 차이를 workspace 문서에 남겼다.

## 최종 재실행

```bash
bash scripts/start_sim_server.sh > artifacts/logs/server_final.log 2>&1
python3 scripts/run_occlusion.py --timeout 300 > artifacts/logs/occlusion_repeat.txt 2>&1
PYTHONPATH=src python3 -B -m unittest discover -s tests -v
```

최종 launcher로 실제 재실행: app ready 9.249초, ROS 자동 시작 로그 없음, health OK. 반복 결과는 다섯 단계 모두 첫 실행의 픽셀 수와 동일하며 `passed=true`. 테스트 재실행도 5 통과 / 2 expected failure. 최종 wrapper에는 동일 공식 health 검사를 선행하는 절차를 추가했다.

최종 전용 프로세스 PID 128174도 session_final.usda 저장 후 official shutdown 요청이 즉시 끝나지 않아, 해당 PID에만 `kill -TERM 128174`을 보내 정리했다. 다른 사용자 인스턴스는 없었으며 종료하지 않았다. headless 전용 세션은 남겨두지 않았다.
