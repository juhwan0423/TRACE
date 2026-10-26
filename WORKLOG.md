# HAI-CLAW official skill integration — 2026-10-23

## Feature → skill mapping (before foundation verification)
- Installed pip runtime and integration: isaac-sim-orchestrator; installation references if needed.
- Asset access: isaac-sim-assets; primitive substitutes avoid network asset downloads.
- Ground and static equipment collisions: physics-simulation.
- RGB acquisition: isaac-sim-sensor; isaac-camera.
- Existing GUI / Python Server: isaac-sim-remote.
- Capture validation: isaac-sim-validator.

Official AGENTS.md and skills/SKILLS.md read from installed 6.2.0.0 package. Skills loaded by filesystem reads; no native skill invocation tool is available. Official originals and global configuration remain unchanged. Workspace AGENTS.md added as the persistent pointer, not a copy of skill bodies.

Prior code is Kit-independent: no existing Isaac Sim API calls to migrate. Scene creation, camera acquisition, and ROS integration are absent. Core boundary bugs found in prior review remain pending while the user-prioritized camera experiment is prepared.

## Execution evidence
- Read Python Server Overview.md and SETTINGS.md before connecting.
- Actual host GPU works after sandbox change; RTX 5090 / driver 580.178.04.
- Runtime identifies as 6.2.0-rc.14 (distribution 6.2.0.0).
- Official remote health succeeded; owned headless session only. Existing default stage exported before replacement.
- Scene uses primitive capsule substitute, static collisions/PhysicsScene, UsdPreviewSurface, RtxCamera + CameraSensor. No external asset fetch required.
- Installed camera implementation/test confirms get_data returns (data, info), not just an image.
- First real render contract passed: 13229 visible → 0 hidden → 36178 after camera motion; fixed view stays 0.
- Second independent launch repeated identical segmentation counts. Logs and PNG/JSON/USD are in artifacts/.
- Official validator Level 1 rejects helper module for missing SimulationApp lifecycle; recorded as failed, not waived into a pass. Remote runtime and capture checks passed separately.
- Seven persisted tests: five pass, two expected failures (known core bugs).
- First full app attempted default ROS bridge initialization and failed; final launcher explicitly disables automatic ROS extensions, and second run has no ROS startup warnings.
- Graceful post_quit helpers returned OK but both owned processes remained. Saved session USDs, then SIGTERM only the known task-owned PIDs; no global pkill.

## Distillation (proposal only)
- Skill update candidate: isaac-camera capture snippet should unpack tuple and guard warm-up None; authoritative source camera_sensor.py already documents it.
- Validator procedure candidate: separate remote module validation from standalone SimulationApp lifecycle checks.
- pip launch path: use installed main() and scoped settings; not missing source-build python.sh.
- User prohibits editing official skill originals, so no skill-library writes were made. These are recorded proposals, not promoted upstream fixes.

## Core regression fix — 2026-10-23 (supersedes known-core-bug status above)
- Scope: incident/perception/async decision core, tests and reporting only; no scene or ROS extensions and no simulator launch.
- LossTracker now checks episode, generation, bound source/subject/track and strictly increasing capture_time across all states. reset increments generation; loss_sequence identifies successive loss events.
- Incident separately tracks latest observed and latest conclusive valid capture per source. Unusable frames cannot suppress fresh danger; old safe closure still rejected.
- moving/failure/timeout/cancellation invalidate arrived_at. Attempts tag async callbacks; failed/old/duplicate completions cannot restore stale arrival.
- At exact deadline, valid danger wins, including timer-first correction with one local alert plus alert_update audit event. After deadline, no retroactive terminal correction.
- VLM cache now includes generation. Mock async tests exercise late prior-generation responses and timeout with independent ticking.
- Removed both expectedFailure decorators. Full command: PYTHONPATH=src python3 -B -m unittest discover -s tests -v > artifacts/logs/core_regression_tests.txt 2>&1
- Result: 29 tests, 0.017 s, OK; no expected failures/skips. 28 fixture/core tests + 1 prior-render artifact check. Earlier seven-test results remain historical.
- Isaac API/skill bodies not reloaded: this change contains no Isaac API use; existing workspace guide and previously read project requirements apply.

## Spot GUI policy task — 2026-10-26, pre-execution contract
- Read official navigation SKILL.md, policy-deployment.md, QuadrupedExample, LocomotionPolicySample/PolicySampleBase/BaseSample and RobotPolicyRunner.
- First validate bundled PhysX Spot on an empty contact floor, then the existing occlusion layout. No kinematic replacement, ROS, Nav2, perception or policy retraining.
- Fixed acceptance thresholds in configs/spot_acceptance.json BEFORE loading assets/running locomotion. Do not relax them in response to results.
- Reuse official get_spot_spec/RobotPolicyRunner. Official example 500 Hz physics / 50 Hz render versus old camera-only scene 60 Hz; exported env timing must match before deployment.
- Skills: isaac-sim-robot-navigation (policy deployment), remote (owned GUI/control), existing physics/camera skills for contact scene and body sensor.

### Spot foundation evidence
- Dedicated GUI started with HAICLAW_HEADLESS=0 bash scripts/start_sim_server.sh; no existing Kit process or port 8226 listener was present. User scenes untouched.
- get_spot_spec resolved PhysX Spot artifacts. stat: USD 3,491,625 bytes; policy 776,662 bytes; env 50,228 bytes; IO descriptor 7,530 bytes. Env and descriptor actually parsed. Model SHA256 independently matched the bundled trusted digest and official runner initialized with 12 matching joints.
- Exact exported timing: physics_dt=0.002, decimation=10, render_interval=10. No observation/action ordering, gains, or controller cadence implemented in client.
- Reuse QuadrupedExample/LocomotionPolicySample lifecycle; build scene floor with official friction 1/1/0. Real camera body mount /World/Spot/body/HAIFrontCamera.
- First floor replay passed. Concurrent official viewport capture paused timeline, interrupting second replay -> 180s wall timeout. Preserved flat_validation_interrupted.log; repeated cleanly without captures during validation. Thresholds unchanged.
- Clean flat runs both passed: 9500 callback ticks == 9500 engine steps, callback IDs unchanged, reset pose difference 0 m. Metrics identical: forward 0.23183 m/s, 1.17183 m; turn 0.31524 rad/s, 1.25771 rad; max tilt 3.0332 deg; height .4964-.5665m; stop residual .01380m, final speed .001783m/s.
- Explicit scene switch cleans up old callbacks, closes runner, destroys UI window and saves prior stage before creating the new owned occlusion stage. Existing GUI replacement requires --replace-demo; a changed active stage identifier is refused.

### Spot task completion / limits
- Occlusion waypoint physical walk passed: goal error .20772m (limit .25), stop residual .00960m, max tilt 1.671deg, height .4948-.5673m. Mounted camera produced RGB; final camera points toward empty floor, so target reacquisition is NOT claimed.
- Actual viewport captures inspected: flat_gui.png and occlusion_gui.png. Scene exported as occlusion_spot.usda; policy requires Python launcher, not USD alone.
- Last independent Stop/Play probe returned connection failure. Process had exited normally (0); user explicitly confirmed they closed the GUI. Did not reopen it. Separate probe remains unverified; previously executed reset_async Stop/Play and duplicate-callback checks passed.
- Skills distillation proposal only: viewport screenshot helper has timeline side effects; never run it concurrently with timed locomotion acceptance tests. Record/capture after trial, or preserve/restore playback deliberately outside the measured window. Official skills unchanged.
- Exact commands and GUI instructions in spot_report.md. Criteria stayed fixed throughout all attempts.

### 2026-10-26 — Jazzy Docker Nav2 통합

- 사용자 “기존 Jazzy Docker에 Nav2 추가” 지시에 따라 원본 보존 파생 이미지 `haiclaw-nav2:jazzy` 생성. 빌드/패키지 검사/실행 로그는 artifacts/nav2.
- 공식 ROS bridge, camera, remote 및 Python Server 문서, PhysX RaycastsDemo, 시간 annotator 소스 검토. ROS workspace skill은 비적용으로 분류. occupancy-map/validator의 검증 구분 참조.
- `navigation.py`의 lease/goal/fresh-frame/cadence 계약 및 tests/test_navigation.py 추가. 41 fixture tests pass.
- `spot_lifecycle.py`에 opt-in nav2 mode/lease 추가. 기존 policy/env/descriptor/gains/500Hz 유지. ROS 연결 상태 기존 보행 2회 actual replay pass, 각 physics/callback 9500회.
- `spot_ros_bridge.py`, `nav2_inspection.py`, Nav2 params/map/BT/launch, Docker/GUI 실행기 작성. 실제 /odom DDS 수신, Nav2 active, 실제 경로 추종, policy sink watchdog 확인.
- run 1792984808819520772에서 arrived + capture 34.133333333 s > arrival 33.182 s; 실제 RGB에서 목표 proxy 확인. 검증 결과 위치 .177744 m / yaw .080316 rad / stop residual .006647 m.
- 실패를 보존: root DDS 전달 문제, static TF 초기화/Reset scan cadence, Navfn 최종 회전 시 위치 드리프트, GUI 반복 실측 .255245 m fail. 전체 명령·제약·검증 수준은 nav2_report.md.
- 설치된 공식 파일/guide 원본 수정 없음. 실제 하드웨어/유료 API/YOLO/VLM 추가 없음.
- 최종 Smac Hybrid-A* + RPP lookahead .3/stateful=false 설정에서 GUI Reset 2회 연속 actual arrived + fresh RGB + stop pass. run 1792985258921926274 / 1792985384306864306. 마지막 위치 .093260 m/yaw .098312 rad, arrival30.702/capture31.633333333/receive31.702 s, residual .003952 m. --attach 실제 실행, publisher/node 단일성 확인. 보고서와 GUI 재실행 명령 갱신.

### 2026-10-26 — Gemini ER 2 단일 프레임 관측

- 로컬 VLM 환경을 조사한 후 사용자 지시로 공식 gemini-robotics-er-2-preview API 선택. Google 공식 Robotics/legacy generateContent/structured-output/image-understanding 문서 확인. 키/유료 요청/모델 다운로드 없이 구현.
- single_frame_vlm.py, gemini.py, configs/vlm.json, vlm_run.py 추가. 6필드 schema, 한 장의 한계, post-arrival freshness, episode/generation/motion binding, 비동기 tick, 오류 unknown, 단일 프레임 safe closure 금지. default dry-run, --allow-api + 환경변수만 호출 허용. HTML/JSON에 입력·원문·지연·결정 이력 출력.
- 설치 assets/camera/remote/Python Server 및 validator 지침 적용. 로컬 stylized human authoring. Quat precision 오류 수정. 장면별 이동 최초 시도 불안정하여 취소/원상복구, 공통 실제 도착 후 세 장면 새 RGB로 평가 범위 확정. 최종 matched_views.log에 capture 31.766666667/31.966666667/32.166666667, 공통 arrival31.542. root/visibility 복원 scene_restored.json 확인.
- 실제 실행: `PYTHONPATH=src python3 -B -m unittest discover -s tests -v > artifacts/vlm/unit_tests.log 2>&1` => 56 tests OK.
- 실제 실행: `python3 scripts/vlm_run.py --cases artifacts/vlm/cases.json > artifacts/vlm/three_case_dry_run.log` => 네트워크 없는 3-image HTML/JSON 생성.
- 실제 실행: `python3 scripts/vlm_verify_artifacts.py`, `python3 scripts/vlm_run.py --help` => PASS. 이미지 3장 직접 열어 시각 확인. 초기 remote 명령 argv 일부 미보존 사실 및 최종 재현 명령을 vlm_report.md에 명시.
- API 실제 결과/latency/최종 상태는 null, 키 입력 후 실행 필요. CLI incident clock은 offline saved-evidence replay이며 live Kit 통합은 아직 아님. guide SHA256 동일. 공식 설치/다른 프로젝트/전역 설정 변경 없음.

### Git 최초 스냅샷 준비

- workspace 자체를 Git main 저장소로 초기화하고 코드·설정·보고서 및 선별된 실제 캡처를 포함한다.
- artifacts/runtime, 대형 USD 백업, 일반 로그와 .env/키 파일은 제외. 로컬 파일 삭제 없음.
- README에 검증 수준 및 다른 머신에서 절대 경로/산출물 재생성이 필요한 한계 명시.
- staging 파일의 비밀키 패턴/크기 점검 및 전체 테스트 후 로컬 커밋. 원격 주소를 받기 전에는 push하지 않는다. 전역 Git 설정 변경 없음.
