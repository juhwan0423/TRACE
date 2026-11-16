# 공식 Spot GUI 보행 데모 — 2026-10-26

## 결과

공식 `get_spot_spec()`와 `RobotPolicyRunner`를 재사용해 **실제 PhysX 보행**을 검증했다. 로봇 위치를 매 프레임 직접 옮기지 않았다. 빈 바닥에서 자세 유지·저속 전진·회전·정지·Reset 재실행 후 기존 설비/대체 사람 장면의 waypoint 보행까지 통과했다. 기존 사용자 GUI가 없는 상태에서 전용 GUI를 열었으며, 사용자가 직접 GUI를 닫았다고 확인한 후 다시 열지 않았다. 프로세스 종료코드 0.

사용자의 육안 보행 판정 자체는 별도 확인하지 않았다. 수치 검증과 렌더 이미지 확인 결과를 아래에 구분한다.

## 자산과 정책 실제 로딩

공식 factory가 설치된 자산 루트에서 아래 경로를 해결했다. 완전한 실제 URL은 `artifacts/spot/preflight.json`에 보존했다. 다른 엔진/정책으로 대체하지 않았다.

| 파일(자산 루트 상대 경로) | 확인 크기 | 확인 수준 |
|---|---:|---|
| Isaac/Robots/BostonDynamics/spot/spot.usd | 3,491,625 B | 실제 stage reference 로딩, 12관절 articulation 생성, 렌더링 |
| Isaac/Samples/Policies/Spot_Policies/physx_policy.pt | 776,662 B | 모델 바이트 SHA256 확인, runner 초기화와 추론·제어 실행 |
| Isaac/Samples/Policies/Spot_Policies/physx_env.yaml | 50,228 B | PolicyEnvConfig 파싱 및 runner 사용 |
| Isaac/Samples/Policies/Spot_Policies/spot_physx_IO_descriptors.yaml | 7,530 B | descriptor 파싱 및 공식 runner joint binding |

모델 SHA256: `37084fd7d48ffc23100b025b3ffc92bc00507a5be6f676b005781d579d834b8d`. 설치된 공식 `bundled/spot.py`의 digest와 일치. 기록: `model_verified.json`, `runtime_status.txt`, 각 실행 폴더의 `manifest.json`. 캐시되지 않은 공식 파일은 정상 자산 로딩으로 취득했다. 새 모델 학습이나 대형 모델/전체 자산 팩 다운로드는 없었다. preflight는 모델 10 MB 초과 시 거부한다. USD 참조 의존성의 총 네트워크 전송량은 측정하지 않았다.

실제 런타임: Isaac Sim 6.2.0-rc.14, engine `physx`, GPU RTX 5090. Newton 정책은 실행하지 않았다. Newton actuator 모듈 로그는 공식 runner의 actuator 구현에서 발생하며 시뮬레이션 엔진 전환을 뜻하지 않는다.

## 공식 구현과 시간 설정

읽은 파일은 설치 루트 아래 다음과 같다.

- AGENTS.md, skills/SKILLS.md
- skills/isaac-sim-robot-navigation/SKILL.md 및 references/policy-deployment.md
- skills/isaac-sim-remote/SKILL.md, Python Server docs/Overview.md·SETTINGS.md
- navigation-primitives의 footprint/경로 관련 지침 및 scripts/robot_footprint.py
- isaacsim.robot.policy.examples의 interactive/quadruped/quadruped_example.py
- interactive/example_base.py의 LocomotionPolicySample/PolicySampleBase
- isaacsim.examples.base의 base_sample_experimental.py
- bundled/spot.py, runtime.py, env_config.py, spec.py 및 articulation API
- 이전 작업에서 읽은 physics/camera/validator 지침을 적용했다. 공식 파일은 변경하지 않았다.

기존 `build_scene.py`의 60 Hz는 카메라 전용 기본값으로 유지했다. 선택 매개변수 `physics_hz`, `create_sensors`를 추가하고 Spot 장면만 **500 Hz**로 생성한다. 실제 export는 physics_dt=0.002, decimation=10, render_interval=10으로 공식 QuadrupedExample의 500 Hz 물리/50 Hz 렌더와 일치한다. runner의 export 값을 확인해 SimulationManager와 RenderingManager에 반영했다.

관측 48차원·행동 12차원 순서, gains, actuator 설정, 정책 decimation은 공식 runner가 descriptor/env에서 구성한다. workspace 코드는 이를 재작성하지 않는다. spawn은 공식 예제 높이 0.8 m, 위치는 작업 바닥의 (0,-3)이다. 바닥은 공식 예제와 같은 마찰 1/1, 반발 0의 정적 충돌면이다.

## 사전 통과 기준과 실제 측정

기준 파일 `configs/spot_acceptance.json`을 실행 전에 저장했다. 결과에 따라 수정하지 않았다. 단계: settle 3s → hold 3s → forward 5s → turn 4s → stop 4s. 높이·기울기는 초기 settle 3s 이후를 평가한다. 속도는 실제 물리 tensor에서 읽고, 명령은 base-frame [vx,vy,wz]다.

| 지표 | 고정 기준 | 빈 바닥 / Reset 재실행 |
|---|---|---:|
| 몸통(root) 높이 | 0.35–0.85 m | 0.4964–0.5665 m |
| 최대 기울기 | ≤25° | 3.033° |
| hold 이동량 | ≤0.20 m | 0.00426 m |
| 전진 명령 / 실제 평균 | 0.25 m/s / 0.10–0.45 m/s | 0.23183 m/s |
| 전진 변위 | ≥0.50 m | 1.17183 m |
| 회전 명령 / 실제 평균 | 0.30 rad/s / 0.10–0.60 rad/s | 0.31524 rad/s |
| 회전 각도 | ≥0.40 rad | 1.25771 rad |
| 정지 1s 후 최대 잔여 이동 | ≤0.15 m | 0.01380 m |
| 마지막 0.5s 평균 수평 속도 | ≤0.08 m/s | 0.001783 m/s |
| Reset 초기 위치 오차 | ≤0.10 m | 0 m |
| callback 중복 | callback tick = engine step | 9500 = 9500, 두 실행 모두 |

Reset 후 두 실행의 측정 결과는 동일했다. 공식 reset_async의 Stop/Play 경로를 실제 실행했으며 callback ID 재등록 시 동일성도 확인했다. 별도로 마지막 waypoint 이후 실행하려던 toolbar-equivalent Stop→Play 검사(`spot_stop_play_check.py`)는 사용자의 GUI 종료로 **연결 실패하여 실행되지 않았다**. 이 별도 항목을 통과했다고 보고하지 않는다.

가림 장면은 동일 runner로 [(3,-3),(3,1)] 경로를 추종했다. 45s deadline/0.25m tolerance, 속도 0.25m/s·회전 0.3rad/s 제한. 결과 `arrived`, 최종 위치 [2.89398, 0.82137, 0.49482], 목표 오차 **0.20772m**, 잔여 이동 **0.00960m**, 최대 기울기 **1.671°**, 높이 0.4948–0.5673m로 통과. 고정 단순 경로이며 일반 장애물 회피/경로 계획기를 검증한 것은 아니다.

## 파일별 책임과 lifecycle

- `scripts/spot_scene.py`: 바닥·가림 설비·조명과 실제 `/World/Spot/body/HAIFrontCamera` 부착. 로봇 이동 제어 없음.
- `scripts/spot_lifecycle.py`: QuadrupedExample 상속, 공식 runner spawn/restart/step/close 및 공식 callback 등록/해제 재사용, 측정 기록.
- `src/haiclaw/spot_commands.py`: 제한된 속도 명령 시퀀스 및 waypoint 추종. 관절/로봇 pose 쓰기 없음.
- `src/haiclaw/spot_validation.py`: 실행 전 기준으로 telemetry 평가.
- `scripts/spot_gui_setup.py`: owned GUI 보호, 백업, 재실행 정리, GUI 버튼.
- `scripts/spot_gui.py`: pip GUI 실행과 health/preflight/setup CLI. source-build python.sh 사용 없음.

Play: 첫 physics tick에서 공식 runner가 default state와 정책을 재초기화한다. Stop: ready latch와 속도 명령을 초기화하며 다음 Play는 hold로 시작한다. Reset 버튼: 공식 reset_async를 사용하고 새 시퀀스를 시작한다. Reset 버튼 연속 입력은 busy latch로 겹치지 않게 한다. Zero velocity는 타임라인을 멈추지 않고 균형 유지 정책에 0 명령을 보낸다.

같은 서버에서 재실행 시 기본적으로 기존 demo를 거부한다. 명시적 `--replace-demo`만 이전 stage를 workspace로 백업한 뒤 old callback 해제·runner close·UI destroy를 수행하고 새 stage를 만든다. 다른 active stage identifier로 바뀌었으면 교체를 거부한다. 시작 시 소유 표시가 없는 기존 GUI는 교체하지 않는다. 정책 실패 시 이유를 저장하고 timeline을 pause한다.

기존 occlusion_demo의 카메라 좌표 이동은 이번 Spot 경로에서 사용하지 않는다. robot reset 시의 default pose 복원만 공식 lifecycle에서 수행된다. 보행 중 매 프레임 robot pose 변경은 없다.

## 재현 명령 / 사용자 GUI 동작

```bash
cd /home/jude/isaac_ws_61/haiclaw_ws
python3 scripts/spot_gui.py --scene flat
```

GUI의 **HAI-CLAW | Official Spot Policy** 창에서 **Run / Reset validation**을 누르면 약 19초의 시뮬레이션 동안 자세 유지→전진→회전→정지를 볼 수 있다. **Zero velocity (keep balance)**로 0 명령, **Reset and hold**로 초기화한다. GUI가 닫혔다면 위 명령으로 새로 시작한다.

같은 소유 GUI를 가림 장면으로 바꿀 때:

```bash
python3 scripts/spot_gui.py --scene occlusion --replace-demo
```

가림 장면의 **Reset and follow waypoints** 버튼으로 보행을 재생한다. 실행 중인 사용자 GUI에서 장면을 저장하지 않고 교체하지 않는다. 위 명령은 명시적 기존 demo 교체 명령이며 자동 백업을 만든다. GUI 창이 이동 경로를 가리면 HAI-CLAW 패널을 옆으로 옮길 수 있다.

## 실제 실행 명령과 증거

```bash
HAICLAW_HEADLESS=0 bash scripts/start_sim_server.sh > artifacts/spot/gui.log 2>&1
python3 /home/jude/isaac_ws_61/IsaacLab/.venv/lib/python3.12/site-packages/isaacsim/skills/isaac-sim-remote/scripts/isaacsim_send.py --context spot --timeout 90 --args-json '{"workspace":"/home/jude/isaac_ws_61/haiclaw_ws"}' --file scripts/spot_preflight.py
python3 /home/jude/isaac_ws_61/IsaacLab/.venv/lib/python3.12/site-packages/isaacsim/skills/isaac-sim-remote/scripts/isaacsim_send.py --context spot --timeout 180 --args-json '{"workspace":"/home/jude/isaac_ws_61/haiclaw_ws","occlusion":false}' --file scripts/spot_gui_setup.py
python3 /home/jude/isaac_ws_61/IsaacLab/.venv/lib/python3.12/site-packages/isaacsim/skills/isaac-sim-remote/scripts/isaacsim_send.py --context spot --timeout 300 --file scripts/spot_validate_remote.py
python3 scripts/spot_gui.py --scene occlusion --replace-demo
python3 /home/jude/isaac_ws_61/IsaacLab/.venv/lib/python3.12/site-packages/isaacsim/skills/isaac-sim-remote/scripts/isaacsim_send.py --context spot --timeout 300 --file scripts/spot_waypoint_validate.py
PYTHONPATH=src python3 -B -m unittest discover -s tests -v
```

remote 검증 로그: `preflight.log`, `setup_flat.log`, `flat_validation.log`, `setup_occlusion.log`, `waypoint_validation.log`. 모두 artifacts/spot 아래에 있다. 성공한 실행의 client 종료코드는 0이다. 첫 interrupted 실행은 nonzero로 별도 보존했다. 마지막 Stop/Play client는 연결 실패로 종료코드 1이다.

데이터: `flat_summary.json`, `lifecycle.json`, `flat_telemetry_0.json`, `flat_telemetry_1.json`, `waypoint_summary.json`, `waypoint_telemetry.json`. telemetry는 50 Hz로 시각·phase·command·position·quaternion·linear/angular velocity·tilt·physics tick을 기록한다.

이미지: `flat_gui.png`, `occlusion_gui.png`는 실제 viewport 캡처이며 직접 시각 확인했다. `body_camera.png`는 실제 몸통 카메라 RGB지만 최종 방향이 빈 바닥 쪽이어서 대상을 담고 있지 않다. 사람 재관측 성공 증거로 사용하지 않는다. `occlusion_spot.usda`는 stage 출력이며 USD만 열면 Python runner/callback은 복원되지 않는다. 위 CLI로 실행해야 한다.

## 실패·미검증 사항

- 검증 중 공식 viewport screenshot helper를 호출한 뒤 타임라인이 pause되어 두 번째 검증이 wall timeout으로 끝났다. `flat_validation_interrupted.log`에 보존했다. 캡처를 검증 후로 분리해 재실행했으며 통과 기준은 변경하지 않았다.
- 카메라 360×640에서 DLSS 최소 입력 크기 경고, Fabric interface version 경고, stage close 참조 수 경고가 있었다. 실측과 캡처는 성공했으나 경고가 없었다고 주장하지 않는다.
- 몸통 카메라의 대상 재관측, 일반 장애물 회피, 다른 마찰·경사·외란, 장시간 내구성은 미검증이다.
- GUI에서 임의로 중단한 시퀀스를 정식 통과 결과로 취급하지 않는다.
- 사용자가 GUI를 닫아 마지막 독립 Stop→Play 검사는 실행되지 않았다. 공식 Reset 내부의 Stop/Play와 callback 중복 방지는 실측했다.
- ROS/Nav2/YOLO/VLM은 추가하지 않았다. Python fixture 테스트와 실제 정책 추론·물리 보행 검증을 구분한다.
