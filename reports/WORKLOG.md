# DGX Spark setup — 2026-10-26

User explicitly requested Isaac Sim 6.2.0, TRACE clone/install, and Qwen 8B. This authorizes the required package/model downloads beyond the original workstation restrictions. Original implementation_guide.md preserved.

- Cloned https://github.com/juhwan0423/TRACE.git into this workspace.
- Ubuntu 24.04.4 aarch64, GB10, driver 580.159.03, CUDA toolkit 13.0.88.
- Existing /home/juhwan/isaac installations preserved. Old /home/jude paths unavailable.
- Created project-local .venv; pip install -e . succeeded.
- PYTHONPATH=src python3 -B -m unittest discover -s tests -v: 56 tests PASS (fixtures/core only).
- Installing: .venv/bin/python -m pip install 'isaacsim[all,extscache]==6.2.0.0' --extra-index-url https://pypi.nvidia.com
- Downloading official Ollama ARM64 archive into artifacts/downloads.
- docker build -t haiclaw-nav2:jazzy -f ros2/nav2/Dockerfile . (official ros:jazzy-ros-base replaces unavailable previous-PC base).
- Added scripts/env_spark.sh and scripts/start_ollama.sh; no shell profile or driver changes.
- sudo -n true requires password; user-local installs avoid requiring it.
- Read repository AGENTS.md and implementation_guide.md. Located older official Isaac skills in /home/juhwan/isaac/IsaacSim-6.0-newton; do not use that version as API validation for 6.2.0. Installed 6.2.0 guide will be inspected after download.

Initial pending items recorded below; see final verification section for completed installation checks. No new rendering, ROS transport, locomotion, or online VLM loop claimed.

## User confirmations
- Qwen variant confirmed: Qwen3-VL 8B for visual judgment.
- Explicit NVIDIA Omniverse EULA acknowledgment and authorization to run compatibility/startup validation received in this chat.
- Official 6.2.0 isaac-sim-installation skill read from downloaded wheel; reference extracted unchanged under artifacts/install-reference. Prior installation request already authorized the target and downloads; explicit EULA now recorded.
- Local CLI added: scripts/vlm_local.py reuses existing LocalChatTransport and SingleFrameVLM, writes saved-image inference reports; no live-incident claim.

## Verified local Qwen / Nav2
- Ollama 0.40.11 ARM64, qwen3-vl:8b (9cf69da2b16d, 6.2 GB), pull completed with digest verification.
- User service: ~/.config/systemd/user/trace-ollama.service enabled and active; loopback only. Initial WorkingDirectory quoting error corrected before start.
- Initial 262144 context used 45 GB; configured context 8192 and parallel=1, observed 6.6 GB and 100% GPU via ollama ps.
- Initial 512-token responses exhausted the budget during reasoning (empty final content). Explicit think=false still emitted reasoning. Switched to bounded think=true, 4096 output tokens, 180s timeout.
- Next response had evidence_ids as a string, rejected by existing strict validator. Added Ollama native JSON Schema enforcing arrays/enums and evidence ID. No weakening of validation.
- scripts/vlm_local.py artifacts/vlm/captures/6815cc79-72fe-405b-bb83-768a7dfcec49/rgb.png --output artifacts/vlm_local/spark-schema-verified.json: status ok, 23.77 seconds, person visible / lying; retained limitation '3D rendered scene'. Saved-image inference only; no live incident or medical/safety validation.
- Nav2 image build succeeded: sha256:102948ea8e4551beca7bd90e4db30524c5a99f6cf2e3af489db8904f4a966894. Offline container package checks nav2_bringup/nav2_controller and rclpy import passed. ROS transport/navigation not yet tested.
- Network stalls required resumable range downloads. Isaac kit cache SHA256 verified: 5fc92edb1af4c324f42d94d9cacb29ad6b327194eeead73901cf8f41a385658a.
- pip --find-links still selected the remote equivalent; restarted with the verified wheel as an explicit argument to prevent re-download.

## Final verification
- Isaac Sim pip package 6.2.0.0 installed in .venv; official runtime health reports 6.2.0. Startup full-build string is 6.2.0-rc.14 from the published wheel.
- PyTorch 2.11.0+cu130, CUDA 13.0, GB10 available; CUDA tensor sum passed (45).
- `source scripts/env_spark.sh; isaacsim isaacsim.exp.compatibility_check --no-window --/app/quitAfter=30`: exit 0, `System checking result: PASSED`. Log: artifacts/logs/isaac-compatibility.log.
- `source scripts/env_spark.sh; bash scripts/start_sim_server.sh`: started dedicated headless instance; official isaac-sim-remote health_check.py reports version 6.2.0, 490 extensions, stage 14 prims, stopped timeline, `Health: OK`. Log: artifacts/logs/isaac-health.log. Requested post_quit; process did not exit promptly, so sent SIGTERM only to the identified test process PID 84165 afterward.
- Read 6.2.0 isaac-sim-remote SKILL.md and Python Server Overview.md/SETTINGS.md before using the loopback server.
- `pip check`: one upstream wheel metadata warning: nvidia-cusparselt-cu13 0.8.0 uses internal WHEEL tag py3-none-manylinux2014_sbsa despite its aarch64 filename. No third-party metadata was rewritten to hide this warning. Its native library loads with ctypes and torch.backends.cusparselt.is_available() is True.
- Startup reports optional DLSS-RR unsupported / disabled on this hardware/driver; compatibility and health checks still pass. No driver changes.
- Final `.venv` core tests: 56/56 PASS. Shell syntax and git diff whitespace checks pass.
- Verification scope: install + simulator startup/health + GPU tensor compute + actual saved-image Qwen inference + Nav2 package loading. New camera rendering, Spot locomotion, ROS transport, and full online incident loop remain unverified on this Spark. Historical repository reports are from the previous machine.

## Closed-loop integration — 2026-10-26
User requested connecting and running the simulation closed loop. Feature mapping: orchestration/remote for owned Kit session, assets for official Spot artifacts, physics for existing PhysX policy, sensor/camera for fresh capture, validator for output QA. Existing Incident/LossTracker/IncidentVLM contracts and Nav2Inspection will be reused; Qwen stays local. No hardware or paid APIs.

Closed-loop implementation progress (2026-10-27 Asia/Seoul):
- Spot foundation: official PhysX policy loaded; Nav2 reached (3, 1.3, pi), arrival sim=30.602, fresh RGB sensor stamp=31.533333333. artifacts/logs/loop-nav-foundation.log.
- New ClosedLoop coordinator reuses LossTracker, Incident, IncidentVLM; Ollama adapter extracted from offline CLI. Added fresh live fixed camera and scenario-only mannequin motion, plus live external runner.
- 60 tests pass including late inference deadline, stale frame rejection, wrong episode rejection, and arrival-not-safe.
- Trial 1 Qwen observed visible then occluded; automatic Nav2 start worked, but robot did not progress although commands arrived. Nav2 aborted; no safe closure. Trial interrupted after failure to investigate.
- Root cause hypothesis: collider topology authored during running physics after reset. Changed all topology creation before reset; occlusion changes only mannequin transforms. Subsequent actual validation moved Spot from (0.269,-3.273) to (1.042,-2.539), no policy failure. Trial 2 running with predeclared 70 simulation-second incident budget.
- prepare_closed_loop.py reused the owned context and returned Health OK without replacing stage.
- Trial 2 reproduced non-progress even with topology-before-reset. The original topology hypothesis was insufficient. Trial ended escalated_unknown after its deadline (no safety closure); manual policy diagnostics were performed after Nav2 had already failed.
- Follow-up: step commands persisted but posture stayed fixed after long zero-command hold. Changing PhysX sleep threshold/wake call did not restore motion; restored original sleep threshold 5e-5. Official RobotPolicyRunner.initialize() resets controller/actuator state from current measured pose WITHOUT teleport (validated local runtime.py doc/source). Calling it restored >1 m movement. Added initialize() when starting moving modes in SpotDemo.start; no physics state/pose setter is used. Trial 3 runs from a fresh episode with this fix.

### Closed-loop final result
- Trial 3 completed the live chain: Qwen fixed camera visible -> occluded, automatic Nav2 start, actual Spot locomotion, measured goal arrival, new body-camera RGB, actual local Qwen, incident deadline outcome.
- Result: artifacts/closed_loop/263c92fc-bb26-492b-869d-d822a8e2e2ab/result.json. Incident opened 11.502s; arrival 40.242s; sensor RGB capture 41.200s; received 41.242s; deadline 81.502s; final escalated_unknown with local_alert=true. No external alert sent.
- Qwen status ok, 29.06 wall seconds, person visible / lying, limitation pixelated texture. Existing incident_decision rejects non-empty observation limitations for danger confirmation, so no risk/safe certainty was fabricated.
- Nav2 path length from XY telemetry: 6.77099m. Start (0.304,-3.258), end (3.040,1.231). Arrival position/yaw gate passed.
- Manual applicable isaac-sim-validator checks: freshly rendered fixed frames 1280x720, 1.43/1.41MB, mean RGB 188/190, variance 3428/2920; body frame 640x360, 400268 bytes, mean 175.86, variance 3967.93. Visually inspected initial fixed and final body images: visible mannequin / lying mannequin; not black. Noticeable render noise retained as a limitation (not presentation-polished output).
- Final scene exported to run directory final_scene.usda. Verified near-zero physical velocity (~0.00036m/s), mode hold, then paused only the dedicated timeline. Isaac and Nav2 remain available for reuse; no other instance changed.
- Final tests: 61/61 pass; live result assertions verify arrival precedes sensor capture, model status ok, final deadline alert and no resolved_safe. git diff --check passes.
- Verification scope: one actual lying-mannequin simulation case. Normal/insufficient-view CLI cases are implemented but not yet live-validated; no medical safety, real hardware, multi-camera re-ID or adaptive multi-waypoint efficacy claim.
- Reproduction helper was verified against the existing owned context. Its new-process branch has not yet been exercised end-to-end; all individual launch/setup commands were exercised during this task.

Distillation: classified the long-hold policy re-arm issue as a project-specific procedure until reproduced more broadly. Recorded current-state initialize vs pose-reset distinction in code and CLOSED_LOOP.md; no official skill files or global agent settings changed.

## 2026-10-27 — 요약 및 TRACE 대시보드

- `reports/PROJECT_SUMMARY.md`에 구현 위치, 오류와 수정, 재현 명령, 검증 범위를 통합.
- Sites 스킬 사용: `/home/juhwan/.codex/plugins/cache/openai-curated-remote/sites/1.1.2/skills/sites/SKILL.md`.
- `dashboard/export_data.py`: 실행 263c92fc와 Nav2 1793028034581052790에서 구조화 관측, 3개 RGB, 다운샘플 궤적 추출. 원본 reasoning·로컬 경로 제외. 누적 거리는 원본 1435개 샘플로 계산(6.771m).
- 정적 대시보드: 프레임 선택, 시간 이동/재생/배속, XY 궤적, 증거 게이트, 실행 명령 복사, JSON 다운로드, 오류 수정과 한계 표시. 실시간 제어로 오인하지 않도록 저장 기록·읽기 전용 명시.
- 실행: `python3 dashboard/export_data.py`, `node --check dashboard/dist/app.js`, `python3 -m http.server 8765 --bind 127.0.0.1 --directory dashboard/dist`.
- 시뮬레이션 장면 및 실행 프로세스는 변경하지 않음.
- 검증: HTTP 200, JavaScript 구문 검사 통과. 앱 브라우저에서 관측 소실 프레임 전환(unknown/no), 재생 시각 변화, 최종 프레임(lying), 도착 위치(3.04,1.23) 표시 확인. 좁은 뷰포트에서 단일 열 레이아웃 확인. 타임라인 슬라이더 정밀도를 0.001초로 수정.
- 대시보드 소스는 Sites 도구가 `dashboard/.git`의 별도 저장소로 관리합니다. TRACE 상위 저장소 전체를 사이트로 업로드하지 않았습니다.
- 비공개 배포 성공: https://trace-spark-mission-control.sweethinny15.chatgpt.site (Sites status=succeeded). 소스 commit a04a4389e03ace30895d7a504ddab25a0b60db58. 배포 완료 후 로컬 QA 서버 종료.

## 2026-10-27 — 담백한 GTK 프로그램 UI와 Qwen 스트리밍

- 사용자 요청에 따라 웹 홍보 문구 대신 제목·연결 상태·카메라·모델 출력 중심의 네이티브 GTK 창으로 전환. 기존 웹 배포는 수정하지 않았고 로컬 프로그램을 우선 제공.
- 시스템 `/usr/bin/python3`의 Gtk 3 사용. 설치 없이 실행. 앱 목록용 사용자 로컬 `trace-monitor.desktop` 등록.
- 공식 `isaac-sim-remote` 및 `isaac-sim-validator` 스킬 읽음. 기존 TRACE 소유 context에서 guard와 health/snapshot 확인 후 센서 버퍼만 읽음. 장면/타임라인 변경 없음.
- `trace_desktop.py`: 1초 간격 카메라 폴링, 영상 letterbox, 고정/몸통 선택, 센서 시각·정지·동일 프레임 표시. 큰 Qwen 출력 패널, 자동 스크롤, 현재 프레임 수동 분석.
- `ollama_stream.py`: loopback/proxy/redirect 제약 유지, bounded NDJSON, 종료 마커/크기/시간 검사, thinking와 최종 content 분리. 기존 비스트리밍 호출은 그대로 지원. 폐루프의 사건 규칙은 변경하지 않음.
- 검증: `PYTHONPATH=src .venv/bin/python -B -m unittest discover -s tests -v` → 65 tests OK. 신규 스트림 테스트: 청크 조립, 불완전 종료, 서버 오류, 초과 크기.
- 실제 센서 읽기: body 640×360, capture_time 94.166666667, RGB mean158.27/std68.05. fixed1280×720 mean189.63/std56.00. paused 상태 명시.
- 실제 로컬 Qwen 스트림을 실행해 start/thinking/content/done/result 이벤트 확인. UI 오류 로그 비어 있음. 시뮬레이션 폐루프 전체를 다시 실행한 검증은 아님.

## 2026-10-27 — 전체 장면 스트리밍 / 실제 ROS graph 탭

- 적용 스킬: 기존 `isaac-sim-remote`, `isaac-sim-validator`; 추가 `isaac-sim-sensor`를 읽고 설치 API 및 기존 로컬 센서 코드를 확인.
- 기존 TRACE stage guard와 paused 상태를 조회하고 관찰 전용 카메라 `/World/TraceOverviewCamera` 및 Replicator RGB render product 추가. 기존 장면 교체·물리 초기화·기존 카메라 이동 없음. 신규 관찰 카메라에만 전체/로봇 따라가기 적용.
- JPEG 연속 수신 1280×720 전체 장면 + body640×360 + fixed1280×720. 실측 약5.78 FPS (paused 상태); 움직이는 폐루프 전체 재실행은 하지 않음. 실제 render `artifacts/live/overview.png` 시각 검토: 로봇·설비·마네킹 확인. 밝은 장면과 기존 렌더 노이즈는 남아 있음.
- ROS graph: rclpy Node의 get_node_names_and_namespaces, get_topic_names_and_types, endpoint info로 11노드/59토픽 확인. 기존 노드를 읽으므로 모니터용 publisher/subscriber는 생성하지 않음.
- Graphviz로 실제 endpoint 방향 node→topic→node를 렌더. 기본4토픽, 전체59토픽, 검색, 선택 상세, 줌·스크롤 제공. 토픽 메시지율/전달 성공을 측정한 것으로 표현하지 않음. Python/HTTP 카메라·Qwen 경로는 비ROS라고 별도 표시.
- 검증: GTK GraphTab에 실제 snapshot 입력하여 기본4행·선택 /cmd_vel controller endpoint·전체59행·/clock 검색·PNG 렌더 검사 통과. 코어 및 스트림 65 tests OK. 실행 로그 `desktop-v2.log` 오류 없음.
- 실제 실행 환경의 프로그램만 새 버전으로 재실행. Isaac Sim·Nav2·Ollama와 물리 타임라인 상태 유지.
- 일반 py_compile은 Kit용 `monitor_scene.py`의 top-level await를 거부하므로 해당 스크립트만 `ast.PyCF_ALLOW_TOP_LEVEL_AWAIT`로 구문 검사(통과). 나머지 일반 Python 모듈 py_compile 통과.


## 2026-10-27 — HAI-Real2Sim 다운로드 및 실행 사전 준비

- 사용자 명칭은 TRACE로 통일. NAS 데이터 수령 및 실제 실행은 사용자 요청으로 후속 작업으로 남김.
- `git clone --depth 1 https://github.com/sayhee-kim/HAI-Real2Sim.git` 완료: 형제 폴더 `../HAI-Real2Sim`, commit `66fe5e3e4069f061afa1344a0ff8a9fdf0376e88`, 약 48MB. 원본 소스 수정 없음.
- 적용 스킬: 설치된 공식 `isaac-sim-assets/SKILL.md`; 설치된 AGENTS.md 및 skills/SKILLS.md 확인. 기존 시뮬레이터에 명령을 보내거나 장면 교체하지 않음.
- `bash HAI-Real2Sim/lab_west/reproduce/simulate.sh --no-video` (상위 ROSCLAW 디렉터리): exit 1, retarget_scene.usda 누락으로 시뮬레이터 시작 전 중단.
- NAS manifest의 12개 파일 모두 없음(997,184,395 bytes). 기본 GVFS 위치에 NAS 마운트 없음. 스캔 USDZ와 풍력터빈 레이어, retarget_scene이 빠져 완전한 장면 재현 불가.
- 정적 호환성 확인: 원본 6.0.1 standalone의 python.sh가 pip 6.2 설치에는 없음. 원본 순찰기의 SpotFlatTerrainPolicy는 설치된 `_legacy.py`에서 생성 시 RuntimeError를 내는 제거된 API. RobotPolicyRunner 포팅 필요. TRACE 연결에는 카메라/사건 인터페이스 및 Nav2 장면 설정이 필요하며 USD만 열어 폐루프가 연결되지는 않음.
- 장면 실행 의존성은 기존 설치 활용: Isaac Sim 6.2.0.0, NumPy 2.3.1, Pillow 12.3.0, SciPy 1.17.0, OpenCV, USD 26.8, ffmpeg. 실제 import 확인. 새 패키지 설치 불필요. 선택적 스캔 재구성/학습 환경(nerfstudio, GVHMR, Open3D 등)은 장면 실행 필수가 아니므로 설치하지 않음.
- `scripts/env_real2sim.sh` 및 `scripts/check_real2sim.py` 추가. `source TRACE/scripts/env_real2sim.sh; python TRACE/scripts/check_real2sim.py`: 의존성 통과, NAS 누락을 의미하는 exit 2 확인. 원본 Git 작업 트리는 clean.
- 재개 시 NAS 마운트 경로로 원본 nas_data.py fetch 실행 후 체크섬 검증. 별도 6.2 호환 실행기를 만들고 독립 장면에서 렌더/보행 검증한 다음 TRACE 공급자 연결. 현재 렌더링/보행/ROS 통합 성공을 주장하지 않음.

## 2026-10-27 — 전체 시스템·도구·VSS 비교 탭

- 사용자 요청: 전체 통신/도구/agent 구조를 설명하고 VSS는 통합 없이 비교.
- `monitor_system_ui.py` 및 세 번째 탭 추가. 전체 연결, 고정 실행기의 Python 도구와 미구현 자율기능, 문서상 VSS 비교 3개 보기. 소스 기반 설명도와 실제 DDS graph를 명시적으로 구분.
- 로컬 실행기/코어/adapter/Nav2Inspection 코드 확인. 실제 latency44.174/57.849/29.061초와 순차 대기·단일 프레임·추가 관측 부재를 표시. thinking이 유일한 병목이라고 단정하지 않음.
- 공식 VSS 3.3 Introduction, Agent Overview, NVIDIA blueprint 지원 하드웨어 자료 확인. `reports/VSS_COMPARISON.md`에 출처와 독립 비교 프로토콜 기록. VSS 모델/컨테이너 설치·외부 추론 호출·통합 없음.
- `/usr/bin/python3`로 SystemTab의 3개 선택 모드, Graphviz PNG, 본문 렌더 오류 여부 확인(통과). 구성도 `artifacts/live/system-{0,1,2}.png` 저장.

## 2026-10-27 — TRACE 하네스 v1 구현

- 요구사항 `implementation_guide.md` 재확인. 기존 ClosedLoop/run_closed_loop baseline은 변경하지 않고 새 `haiclaw.harness.Harness`와 `run_harness.py` 작성.
- 모델에 목표·예산·관측·실패 이력·허용 도구를 전달 → JSON action 검증 → observe/inspect/wait/stop/escalate 실행 → 결과 기반 재계획. 등록한 위치만 사용, 임의코드/좌표/종료판정 도구 없음.
- 기존 Incident 근거 정책 유지. 별도 sim/wall deadline 감시, reset/paused 감지, 늦은 응답 무시, 실패·취소 시 stop. 모델 context와 원본 artifact 감사 기록 분리.
- 실제 모델 첫 fixture 실행 `2ea9500a-f344-465e-b250-8ed6845d4c10`: chat think=False에도 JSON 누락, 무효 출력 차단 후 180초에 unknown. 선택형 동작 성공으로 세지 않음.
- 공식 Ollama generate API 확인(https://docs.ollama.com/api/generate). 설치 qwen3-vl:8b 전용 raw assistant prefix + JSON Schema로 텍스트 planner 출력 분리. 실제 probe 정상 응답. 이미지 adapter는 변경하지 않음.
- 실제 Qwen + fixture 도구 `505ab74c-3903-49cf-aedc-a27f8f7bdc70`: 약8.07초, 이동 실패 후 다른 후보 선택, 도착 후 body 관측. 전체 trace 보존. 실제 로봇 보행과 구분.
- 실제 Isaac 실행1 `1d7ed205-0500-4626-b385-1e675d99f5df`: 모델이 body 관측 선택(no person) → east_inspection 이동 선택 → 실제보행. 180wall초 이동 제한에 도착 전 중단, 223.1wall초 unknown 종료·hold. 실제 도착 성공으로 주장하지 않음. 이 실행에는 후속 evidence_records 확장이 아직 로드되지 않았으며 trace/초기 bootstrap과 생성된 이미지로만 기록됨.
- 이동 작업 제한을 기존 Nav2 600wall초와 일치시키고 전체900wall초 유지. 작업 timeout은 예산 잔여 시 모델에 피드백하도록 개선. 별도 실제 실행2 시작.
- 계약/코어/stream/planner/harness 테스트84개 통과 (`artifacts/logs/harness-tests.log`). deadline 중 planning, 실패후 다른 지점, 제한근거 재관측, 불법tool/target, stale episode, frozen/reset/paused clock, 취소, late result, context 경로제외, timeout 재계획 포함.
- GTK `에이전트 실행` 탭 추가: 실제/fixture 모델 실행, SIGINT 중단, 계획/선택 이유/도구 결과 기록. SystemTab에 실제 하네스 구성을 추가하고 baseline 설명과 구분. UI 생성/4개 구성도 선택 검사 통과.
- 두 번째 live 실행 c83e19de: 실제 east_inspection 도착 확인(sim52.682s, 사건 이후270.06wall초). 모델이 도착 직후 새 관측 없이 다른 지점을 선택하는 비효율이 발견됨. 해당 실행의 선택은 그대로 보존.
- 후속 코드에 도착 후 새 몸통 근거가 있어야 다음 이동을 허용하는 도구 사전조건 추가. 모델 목표/위치 선택 자체를 고정하지 않음. 추가 계약 테스트 통과(총85개).
- 저장된 실제 도착 시점 context에 새 사전조건을 적용하여 실제 Qwen으로 재질의: observe(body) 선택 확인. `artifacts/live/harness-postarrival-probe.json`. 이는 기록 context에 대한 모델 probe이며 도구 실행/새 live episode라고 주장하지 않음. 현재 진행 중인 두 번째 live 프로세스에는 이 후속 변경이 소급 적용되지 않음.
- 두 번째 실제 통합 `c83e19de-077a-42d6-a979-ccc113d34d1b` 종료: 모델 선택8회, 도구 실행8회, east 실제도착, southeast Nav2 abort 후 fixed/body 재관측, 900wall초 예산 초과에 escalated_unknown. 정지/저장 포함901.3wall초, stop_error 없음. 종료 hold 및 실제 속도 확인, final_scene.usda/final_state.json 저장.
- 실험 중 발견한 후속 수정: 도착 후 body 관측 사전조건, 실패 이동 시 이전 current_viewpoint를 계속 주장하지 않도록 무효화, 늦은 task 예외 회수, 원본 evidence_records/향후 planner·motion 기록, 시작 시 code_manifest. 두 번째 실행에 소급 적용됐다고 주장하지 않음. 최신 계약 테스트86개 통과. 보완 후 전체 물리 폐루프 반복은 별도.

## 2026-10-27 — Git checkpoint and research readiness review

- 현재 TRACE 하네스/로컬 Qwen/GTK 모니터/ROS 연결 소스와 개발 기록을 커밋 대상으로 정리. 독립 Sites 저장소 `dashboard/` 및 별도 Real2Sim 스크립트 두 개는 포함하지 않음.
- README를 현재 실행 방법과 검증 한계 중심으로 정리; 기존 내용은 `LEGACY_README_2026-10-27.md`에 보존. `RESEARCH_CHECKPOINT.md`에 논문 실험 차단 사항과 비교 설계 제안 기록.
- `python3 scripts/export_checkpoint.py`: 기존 개발 실행 5개의 제한된 요약과 원본 SHA256을 `reports/evidence/checkpoint.json`으로 내보냄. 원본 이미지/모델 서술은 제외. 과거 실행은 최종 guard 수정 후 전체 통합 검증을 대신하지 않음.
- `PYTHONPATH=src python3 -B -m unittest discover -s tests -v`: 86 tests, OK. `git checkout-index --all --prefix=<temporary directory>/`로 staged 파일만 추출한 디렉터리에서도 같은 86개 통과.
- 같은 임시 디렉터리에서 `python3 -B scripts/run_harness.py --mode fixture --planner fixture --fail-first`: 첫 이동 실패 → 대체 지점 도착 → 새 body 관측 → danger_confirmed, exit 0. GPU/네트워크 모델/실제 시뮬레이션 호출 없는 fixture 검증.
- CPU 테스트와 fixture smoke용 GitHub Actions 추가. 로컬 검증 통과이며 원격 CI 결과는 별도 확인해야 함.
- 공개 clone 사용자의 EULA 동의를 자동으로 가정하지 않도록 env_spark에서 자동 동의 설정 제거. README에 명시적 동의 후 실행 명령 기록. 실행 중인 시뮬레이터는 변경하지 않음.
- `git diff --cached --check` 통과; staged 파일에 대형 파일 및 일반적인 비밀키 패턴 없음. 새 live simulation이나 성능 benchmark는 실행하지 않음.

## 2026-10-27 — Question resolution prototype

- `context.py`에 고정 presence/lying 질문, 조건부 해소, 만료/충돌/철회 재개방, visible-lying 파생 판단, 변경 이력과 JSON snapshot hash 구현.
- 기존 하네스 context/action/tool 결과에 question_id 연결. 새 planner schema에 질문 선택 추가; 기존 3필드 planner는 명시적 host fallback으로 구분. 상충한 근거로 context가 해소되지 않으면 사건 위험 종료를 차단.
- `python3 scripts/demo_context_resolution.py > /tmp/trace-context-demo.json`: 해소 → 충돌 → 철회 → 만료 → 새 근거 해소 확인.
- `PYTHONPATH=src python3 -B -m unittest discover -s tests -v`: 97 tests, OK. 신규 11개는 조건·의존성·재개방·해시·하네스 연결/충돌 gate를 검증.
- `reports/CONTEXT_METHOD_DECISIONS.md`에 임시 가정, 사용자의 연구 선택 사항, 원 논문 확인을 바탕으로 한 문헌 조사 출발점, 미구현/미검증 범위 기록.
- 이번 검증은 CPU fixture만 수행. 새 Qwen schema 및 live Isaac 재검증, LLM 자유 질문 생성, episode 종료 뒤 지속 관측 서비스는 미완료. 실행 중인 GUI/scene은 변경하지 않음.

## 2026-10-27 — RTX 5090 PC setup

- Host `jude-X870E-AORUS-PRO`; RTX 5090 32 GB, driver 580.178.04. This is not DGX Spark.
- Fresh latest checkout `be8f480` at `/home/jude/Documents/ChatGPT/ROSCLAW/TRACE`; previous `/home/jude/isaac_ws_61/haiclaw_ws` preserved.
- Reused `/home/jude/isaac_ws_61/IsaacLab/.venv` (Isaac Sim 6.2.0) via local `.venv` symlink. Added `scripts/env_5090.sh`; do not source ARM-only `env_spark.sh` on this machine.
- Skills read: installed `isaac-sim-orchestrator`, `isaac-sim-remote` and workflows, `isaac-sim-troubleshooting`, `isaac-sim-validator`. Remote tool workflow uses file-based skill loading.
- `PYTHONPATH=src python3 -B -m unittest discover -s tests -q`: 86 tests passed. `python3 scripts/run_harness.py --mode fixture --planner fixture --fail-first`: completed `danger_confirmed`, fixture only.
- `source scripts/env_5090.sh; HAICLAW_HEADLESS=0 python scripts/prepare_closed_loop.py`: new owned GUI stage, Spot policy, camera, ROS bridge, and Nav2 container prepared. First cold shader compilation took roughly three minutes. Initial 15-second health probe timed out during compilation; retry after compilation returned Health OK.
- Official health check: Isaac 6.2.0, 115 prims, Z-up, meters/unit 1.0, timeline playing, DISPLAY :1. Nav2 `inspection.client.server_is_ready()` true, `ros_bridge.failure` null. An initial diagnostic used nonexistent `inspection.navigator`; corrected to actual `inspection.client` API without changing simulation state.
- Real viewport capture `artifacts/trace-5090-viewport.png`: 1280x720, 252158 bytes, RGB mean [187.48, 200.09, 209.63], stddev [54.72, 32.78, 18.76]. Visually inspected rendered fixed-camera obstacle scene. This is not an end-to-end live harness result.
- Graphviz packages extracted into `artifacts/graphviz` without system changes; `bash scripts/trace_desktop_5090.sh` runs the native monitor with local Graphviz libraries. Optional neato plugin warns about missing dependency; dot layout is configured.
- Ollama amd64 official archive downloading into `artifacts/ollama`; Qwen live inference remains pending.
- Ollama 0.40.11 amd64 installed locally; `qwen3-vl:8b` downloaded and served on RTX 5090 (37/37 layers offloaded). Native monitor architecture graph rendered successfully with dot (113193 bytes).
- `source scripts/env_5090.sh; python -u scripts/run_harness.py --mode live --planner ollama --budget 60`: completed live episode `ae2e55b2-68e7-47af-b0bd-7daa3d72bb0c` in 127.86 wall seconds, with 5 actual Qwen decisions. Initial visible person and subsequent loss were inferred from rendered images. First east inspection arrived; new body-camera observation reported a person lying on the floor, but host evidence policy did not accept it for closure. Model requested southeast inspection; the 60-second simulation budget expired during that move, resulting in `escalated_unknown`, completed=true, error=null. This verifies live integration, not correct hazard resolution or benchmark performance.
- Exact result: `artifacts/harness/ae2e55b2-68e7-47af-b0bd-7daa3d72bb0c/result.json`; console log: `artifacts/logs/harness-live-5090.log`. Isaac GUI, native monitor, localhost Ollama and the owned Nav2 container remain running; the experiment itself has finished.
- Rerun entry point: `bash scripts/start_trace_5090.sh`; all new shell scripts pass `bash -n`. See `reports/RTX5090_SETUP.md`.

## 2026-10-27 — latest TRACE and Real2Sim monitor integration on RTX 5090

- Fast-forwarded main from be8f480 to e80f30a (evidence-grounded question resolution and reopening); preserved 5090 setup scripts and work log additions. 97 CPU tests passed.
- Added a selectable Real2Sim desktop source (`TRACE_SCENE=real2sim`, dedicated port 8227/context real2sim). Cameras attach to the existing owned scene in its USD session layer; no stage reset or physics stepping is performed by the monitor. Real2Sim and the original TRACE simulator remain separate processes.
- Verified three live RGB feeds: overview 1280x720, fixed and cage-side 640x360; approximately 6 monitor updates per second with advancing sensor timestamps. Visually inspected the worker and cage image. Cage-side is explicitly labeled as a stationary camera, not a robot-mounted camera.
- No Spot is attached to Real2Sim yet. Its autonomous harness start is disabled, and its ROS tab reports the missing connection. Separate `artifacts/live_real2sim` records prevent confusion with baseline logs.
- Changed configs/vlm_local.json to Spark tunnel endpoint http://127.0.0.1:11435/api/chat. Removed automatic local Ollama startup from the standard 5090 launcher. No local-model fallback. Added foreground SSH tunnel launcher and combined Real2Sim monitor launcher.
- Initial sudo check required a password; pkexec authentication returned 'Request dismissed'. User then installed Tailscale 1.104.2; observed NeedsLogin. Tailscale account authentication, Spark peer discovery, SSH tunnel, and Spark image inference remain pending.
- Verification: 97 tests pass after edits, shell syntax and Python syntax checks pass, git diff --check passes. This does not claim Real2Sim navigation or remote Qwen inference succeeded.

## 2026-10-27 — Spark Qwen connected

- Spark Tailscale address updated to 100.73.59.16 (spark-0a58), same tailnet as this PC 100.120.65.107. Direct Tailscale route established.
- First SSH key authentication failed; authenticated through a local Zenity password dialog passed directly to OpenSSH. No password saved. Host key pinned in ignored artifacts/ssh/known_hosts.
- Running SSH tunnel: 127.0.0.1:11435 → juhwan@100.73.59.16 → 127.0.0.1:11434. /api/tags confirmed qwen3-vl:8b; /api/ps confirmed GPU model residency.
- Captured a fresh Real2Sim fixed-camera frame, then ran the TRACE Ollama adapter against the Spark endpoint. Status ok, schema validated; person_visible=yes, posture=standing; 96.23 seconds wall latency. This is image-inference validation, not an autonomous incident/navigation run.
- Evidence: artifacts/live_real2sim/spark-frame.json, spark-verification.png, spark-verification.json. Response events emitted to the Real2Sim monitor.
- Tunnel remains running. Shell syntax and modified desktop Python syntax passed.

### 2026-10-27 — Real2Sim is the default 5090 environment
- Replaced the primary start_trace_5090.sh entry point with the Real2Sim launcher; desktop, event routing and environment defaults now select Real2Sim.
- Guarded live harness against silently running the old demo while Real2Sim navigation remains unimplemented.
- Exported the owned old demo stage to artifacts/baseline-retired/stage.usda, closed its monitor and simulator, and stopped haiclaw-nav2. Restarted the Real2Sim monitor using the primary launcher.
- Kept Real2Sim at 8227 and the Spark SSH tunnel at 11435; verified qwen3-vl:8b availability. All 97 CPU tests pass; launcher shell syntax passes.

### 2026-10-27 — Live TRACE → Real2Sim Spot navigation
- Attached RobotPolicyRunner/get_spot_spec to the owned Real2Sim GUI at port 8227, without replacing the lab scene. Worker animation, capsule colliders and door driver remain active.
- Added desktop patrol/west/cage/entrance/stop and explicit simulation reset buttons, plus scripts/real2sim_control.py. The body RGB camera now follows Spot; snapshots expose pose, goal status and remaining waypoints.
- Verified actual movement, cancellation and entrance arrival through TRACE commands. Initial full patrol exceeded 45-degree tilt near the final segment and failed safely. Reduced maximum speed to 0.45 m/s and waypoint radius to 0.15m; rerun completed all 23 targets in 65.726 simulation seconds, with the worker visible. Spot is holding at entrance.
- Evidence: artifacts/live_real2sim/navigation-validation.json, navigation.jsonl, spot-camera-evidence.json, spot-overview.jpg and spot-body.jpg. Spark qwen3-vl:8b tunnel remains available. Existing 97 CPU tests pass; changed scripts compile, including remote top-level await, and git diff --check passes.
- This is manual waypoint-command integration. The autonomous incident harness remains disabled pending adaptation to Real2Sim observations and locations; old Nav2 is not used.

### 2026-10-27 — Framework-free Real2Sim harness baseline
- Kept the existing native asyncio Harness. Added framework-independent Planner/InspectionTools protocols and a Real2Sim tool adapter; no LangChain/LangGraph dependency was added.
- Added operator-requested inspection runner, explicit Real2Sim viewpoint config, final-heading alignment, request-scoped cancellation, current-request duplicate suppression, and globally consistent simulation arrival timestamps.
- Live Spark Qwen run a5f12343-81cb-4a53-9e27-2b1e5ef0e4f2: 3 actual model decisions/tools over 131.142 wall seconds. Model selected body/fixed/body observation, detected a standing worker in the fixed view, and reached the explicit three-step budget. Terminal result escalated_unknown; no runtime or stop error. This is a completed unresolved handoff, not a successful diagnosis, and no model-selected movement occurred in this run.
- Per-episode manifest stores effective budgets, model config, starting state and source hashes for future runtime comparisons. Existing evidence-age limits were not loosened to accommodate inference latency.
- 102 tests pass including stale-frame rejection, scoped cancellation, replacement-goal rejection and arrival clock handling. Native scripts compile and git diff --check passes.
- Durable crash recovery and automatic incident triggering remain outside this baseline. No disappearance or ground-truth worker state was injected into the planner.
- Separate scripted live tool validation (not a model decision): entrance arrival at simulation 580.756s, duplicate request retained the same action ID, and post-arrival snapshot at 580.920s confirmed global-clock consistency and heading tolerance. Evidence: artifacts/live_real2sim/tool-validation/result.json. Heading can drift during a prolonged idle hold; downstream inspection must rely on the actual fresh image rather than assume permanent framing from the arrival event.
