# Nav2 확인 이동 작업 기록 — 2026-10-26

## 환경과 범위

호스트 Ubuntu 24.04에는 `/opt/ros`와 PATH의 `ros2`가 없다. 기존 Docker 이미지 `ros2-jazzy-gazebo:latest`, `ros:jazzy-ros-base`에는 Nav2 실행 패키지가 없었다. Isaac bundled Jazzy에는 nav2_msgs/common/simple_commander가 있지만 planner/controller 서버는 없다.

사용자가 기존 Jazzy Docker에 Nav2를 추가하는 방식을 요청했다. 원본 이미지와 호스트 ROS를 변경하지 않고 `ros2/nav2/Dockerfile`로 `haiclaw-nav2:jazzy`를 빌드했다. apt 사전 추정은 다운로드 89.5 MB, 설치 공간 576 MB. 모델 가중치 다운로드 없음. 원본 ID `61692107afc248c2043239454b703c9e4f70f7ed5668536c4f92d6c64afa3962`, 파생 ID `f5dd5ba334f295edf645237412d3ac8a592704aac2e830d1a982e2e5060b9b7e`.

공식 설치·skills·전역 설정은 수정하지 않았다. guide SHA256 `09adb11f375e5b03dff4b0f4713e9eff925ba7253c9d6f67bbaf76c42ac66403` 보존.

## 실제 사용한 인터페이스와 제한

- 공식 `isaac-sim-ros2-bridge`, `isaac-camera`, `isaac-sim-remote`와 Python Server Overview, 설치된 카메라/시간 annotator·PhysX RaycastsDemo 소스 검토. `isaac-sim-ros-workspaces`는 읽었지만 이 작업은 bridge/Nav2이므로 workspace clone/build helper를 실행하지 않았다. `occupancy-map`의 정적 투영/물리 지도 구분을 검토했다.
- 기존 `get_spot_spec()`/`RobotPolicyRunner`, 500 Hz physics, 50 Hz 정책, 공식 관절 순서/gains/decimation 유지. root pose를 매 프레임 쓰지 않는다.
- ROS adapter는 공식 `isaacsim.ros2.bridge`로 로딩한 bundled Jazzy rclpy를 사용한다. OmniGraph ROS publisher 그래프를 사용했다고 주장하지 않는다.
- `/clock`, `/odom`, `/tf`, `/tf_static`, `/scan`, `/cmd_vel`, `/navigate_to_pose`. namespace 없는 단일 로봇, domain 173, localhost 전용 UDP XML, 같은 host UID/GID와 IPC. 호스트 네트워크를 쓰지만 DDS 인터페이스를 127.0.0.1로 제한.
- localization은 **시뮬레이터 ground-truth**: map→odom 항등, odom→base_link 평면 위치/yaw. IMU/leg odometry/AMCL/SLAM 검증 아님.
- `/scan`은 PhysX collider raycast 360개, 높이 0.65 m, 10 Hz, 자기 로봇 제외. 실제 충돌 장면을 관측하지만 RTX LiDAR 자산이나 실물 센서 모델은 아니다. base_link 기준 수평 가상 센서로 쓰며 수직 장애물 형상 추정은 하지 않는다.
- 정적 map은 현재 생성 장면의 설비 직사각형과 바닥 끝을 직접 래스터화한 5 cm 지도이다. SLAM/omap 추출 결과 아님. local/global costmap에 실시간 scan obstacle layer 연결. 보수적 footprint 1.3×0.7 m + padding 0.1 m.
- Navfn planner + Regulated Pure Pursuit. 참고: https://docs.nav2.org/jazzy/configuration_and_development/configuration_guide/controller_plugins/configuring_regulated_pp/ . 설치된 Jazzy params reference는 `artifacts/nav2/installed_nav2_reference.txt`.
- 학습 env 원문 `artifacts/nav2/physx_env.yaml`: command range x [-2,3], y [-1.5,1.5], yaw [-2,2]. 실제 데모는 기존 검증 범위로 더 제한: x [0,.25], y=0, yaw ±.3. 뒤/옆 이동 요청은 zero. wall-clock 명령 수신 후 .25초 만료, Stop/Reset/hold 때 lease 폐기.
- NavigateToPose action success만으로 도착 처리하지 않고 실제 위치 .25 m, yaw .15 rad 재검사. goal ID가 다른 응답·종료 후 응답 무시. failed/timed_out/cancelled 분리.
- 몸통 `/World/Spot/body/HAIFrontCamera` 유지. `IsaacReadSimulationTime`을 해당 render product에 부착해 RGB 시각을 확인한다. frame sequence는 sensor native counter가 아니라 timestamp ns에서 유도한 식별자다. 도착보다 엄격히 새로운 capture_time을 요구한다.

## 실행한 주요 명령

```bash
command -v ros2
ls /opt/ros
ss -ltnp 'sport = :8226'
docker image ls --format '{{.Repository}}:{{.Tag}}'
docker run --rm --network none --read-only --entrypoint bash ros2-jazzy-gazebo:latest -c 'source /opt/ros/jazzy/setup.bash; ros2 pkg list | grep -E "nav2|navigation|slam|amcl"'
docker run --rm --network none --read-only --entrypoint bash ros:jazzy-ros-base -c 'source /opt/ros/jazzy/setup.bash; ros2 pkg list | grep -E "nav2|navigation|slam|amcl"'
docker run --rm --pull never --entrypoint bash ros2-jazzy-gazebo:latest -c 'apt-get update -qq >/tmp/haiclaw-apt-update.log 2>&1 && apt-get install --assume-no --no-install-recommends ros-jazzy-navigation2 ros-jazzy-nav2-bringup 2>&1 | tail -30'
docker build --pull=false -t haiclaw-nav2:jazzy ros2/nav2 > artifacts/nav2/docker_build.log 2>&1
bash scripts/start_nav2.sh > artifacts/nav2/bringup_trial2.log 2>&1
python3 scripts/nav2_gui.py > artifacts/nav2/gui_restart_setup.log 2>&1
PYTHONPATH=src python3 -B -m unittest discover -s tests -v > artifacts/nav2/unit_tests.log 2>&1
bash -n scripts/start_sim_server.sh scripts/start_nav2.sh
```

Remote client:
`/home/jude/isaac_ws_61/IsaacLab/.venv/lib/python3.12/site-packages/isaacsim/skills/isaac-sim-remote/scripts/isaacsim_send.py`

```bash
python3 /home/jude/isaac_ws_61/IsaacLab/.venv/lib/python3.12/site-packages/isaacsim/skills/isaac-sim-remote/scripts/isaacsim_send.py --context spot --timeout 400 --execution-timeout 400 --file scripts/nav2_gait_regression.py > artifacts/nav2/gait_regression.log 2>&1
python3 /home/jude/isaac_ws_61/IsaacLab/.venv/lib/python3.12/site-packages/isaacsim/skills/isaac-sim-remote/scripts/isaacsim_send.py --context spot --timeout 650 --execution-timeout 650 --file scripts/nav2_run_validation.py > artifacts/nav2/run_validation2.log 2>&1
```

## 실패와 해결 기록

1. root 컨테이너에서 ROS 로그 경로가 read-only → `/tmp` tmpfs와 ROS_LOG_DIR 적용.
2. DDS 토픽/구독자는 발견되지만 clock/odom/TF 데이터 미수신. 기본 전송, 양쪽 loopback UDP 설정, standalone bundled rclpy도 실패. 컨테이너 내부 pub/sub는 성공. 컨테이너를 호스트와 동일 UID/GID로 실행하자 실제 odom 수신·TF·Nav2 lifecycle active 확인. 원인 세부는 미확정이며 사용자/공유 메모리 접근 차이가 유력하다. 전역 권한 변경 없음.
3. Python Server에서 새 module import cache → invalidate_caches 적용.
4. Camera render_product는 문자열이 아니라 UsdRender.Product → GetPath 문자열로 annotator attach 수정.
5. 첫 Nav2 실행은 명령 .20 m/s를 수신했지만 실제 진전 부족으로 Nav2 progress checker abort. 결과 `artifacts/nav2/1792983800026835720/result.json`의 failed를 보존. 실패를 성공으로 변경하지 않았다. 첫 실행 telemetry 파일은 후속 보행 회귀 시험에서 같은 demo 출력으로 덮어쓴 한계가 있어, 이후는 run별 telemetry도 저장하도록 수정.
6. Reset 후 기존 보행 회귀 2회 모두 통과. .25 m/s와 Reset 직후 출발로 두 번째 Nav2 시도. 도착 허용오차/안전 기준 완화 없음.

## 검증 수준

- Python fixture: 40 tests pass. 속도 clamp/만료/역순/비정상 입력, 도착 위치·방향, 목표 세대, terminal 결과, 새 프레임 시각 검사. 실제 ROS/보행 검증과 별도.
- 실제 Isaac+ROS 연결 상태의 기존 보행 회귀: 2회 통과. 각 9500 physics ticks = callback ticks, callback ID 불변, reset 초기 위치 차이 0. 전진 평균 .23183 m/s, 회전 평균 .31524 rad/s, 정지 잔여 .01380 m, 최종 속도 .00178 m/s. `artifacts/nav2/gait_summary.json`, `gait_lifecycle.json`.
- 실제 DDS odometry 수신 및 Nav2 map/planner/controller/bt_navigator active 확인.
- Nav2 최종 이동/캡처 결과는 아래 후속 실행 결과에 기록한다.

## 실제 Nav2 도착 및 새 카메라 영상 확보

`artifacts/nav2/1792984808819520772/`에서 실제 Nav2 경로 추종 → 공식 Spot 물리 보행 → 도착 → 새 RGB 저장을 확인했다.

- 결과 arrived, 실제 위치 오차 0.177744 m, yaw 오차 0.080316 rad.
- 도착 33.182 s, RGB capture_time 34.133333333 s, received_time 34.182 s. 같은 render product에 부착한 공식 시간 annotator 사용.
- 정지 후 1~4초 잔여 이동 0.006647 m, 최종 속도 0.001866 m/s. 높이/기울기 기준 통과.
- body_camera.png 실제 육안 검사: 파란 설비 옆의 분홍색 사람 대체 캡슐이 보인다. 사람 탐지/VLM 결과 아님.
- 640×360 RGB, mean 178.41, std 55.78, PNG 74,999 bytes. validator의 150 KB 파일 크기 휴리스틱은 충족하지 않는다. 따라서 validator 전체 통과라고 쓰지 않는다. 이 작은 장면의 실제 RGB 내용과 촬영 시각 검사는 통과했다. 불필요한 용량 부풀리기는 하지 않았다.
- GPU 32607 MiB 중 6754 MiB 사용(관측 시점), 약 79% 여유.
- 당시 Nav2는 Smac Hybrid-A* (DUBIN, turning radius .9 m)와 RPP .25 m/s, 단일 계획 경로. 도착 방향을 경로 생성에 포함했다. 공식 Jazzy 참고: https://docs.nav2.org/jazzy/configuration_and_development/configuration_guide/planners_plugins/smac/smac_hybrid/configuring_smac_hybrid/ . 성공 당시 params.yaml/inspect.xml은 해당 run 폴더에 보존.

### 추가 발견과 반복성 제한

- Navfn + 최종 제자리 회전은 목표 근처에서 위치가 밀려 검사 실패. 위치/yaw 허용오차를 완화하지 않았다.
- Reset 후 scan 발행 시각이 이전 에피소드 시각에 남는 버그 수정. `SimulationCadence`를 실제 bridge에서 사용하며 clock rewind 회귀 테스트 추가. 41 unit tests pass. 실제 scan time 21.322 s, sim time 21.402 s, 322 scan messages 확인.
- map→odom은 이후 **동적 ground-truth localization TF**로 odom→base_link와 함께 `/tf`에 발행한다. 초기 `/tf_static` 항등 변환에 의존하던 설명은 현재 구현에 적용하지 않는다. Nav2 lifecycle 시작은 5초 지연해 clock/TF 발견 시간을 준다.
- Nav2 첫 실패/수동 취소/비활성 서버 거절/도착 실측 실패는 각각 run 결과와 bringup 로그에 남겼다. result handler는 failed/cancelled일 때 tensor pose 조회를 요구하지 않게 수정해 Stop 이후 invalid tensor 접근을 피한다.
- 실제 정책 sink에 단일 명령을 주입하고 .8 wall-second 동안 관측한 watchdog 테스트 통과(`artifacts/nav2/watchdog.json`). 외부 ROS cmd_vel 전송과 별개의 정책 sink 만료 통합 시험이다.
- 성공 이후 GUI Reset 재시험 `1792984985882263171`은 Nav2 success였으나 실제 위치 0.255245 m로 **failed**. 첫 성공이 반복 안정성을 입증하지 않는다. 이후 RPP lookahead .3 m, 내부 stateful=false로 위치/방향 동시 검사를 강화한 시험은 후속 결과에 기록한다.

## 최종 설정 결과: GUI Reset 포함 2회 연속 통과

최종 params는 Smac Hybrid-A* + RPP lookahead 0.3 m, 내부 goal checker stateful=false이다. 내부 xy 0.10 m/yaw 0.12 rad를 동시에 검사한다. 외부 사전 기준 **0.25 m / 0.15 rad**와 정지/높이/기울기 기준은 변경하지 않았다. `configs/nav2_acceptance.json` SHA256 `188e2f534a93d2c80b7a1830a5cad3abab0bbe3f895341298736c4f2565dc5f5` 유지.

| GUI 실행 | 위치 오차 | yaw 오차 | 정지 잔여(1~4초) | 최종 속도 | 새 RGB |
|---|---:|---:|---:|---:|---|
| 1792985258921926274 | 0.092373 m | 0.086967 rad | 0.002705 m | 0.001531 m/s | capture 31.833333333 s |
| 1792985384306864306 | 0.093260 m | 0.098312 rad | 0.003952 m | 0.001660 m/s | capture 31.633333333 s |

둘 다 `verification.json`의 arrived/xy/yaw/fresh/height/tilt/residual/stop_speed가 true. 두 번째는 `python3 scripts/nav2_gui.py --attach`로 같은 장면에 컨트롤러를 다시 붙인 뒤 GUI 버튼과 같은 `reset_and_navigate()` 경로를 실행했다. 최종 /odom publisher 1개, /scan publisher 1개, haiclaw_spot_bridge node 1개, command=[0,0,0], mode=hold, failure=None을 확인했다. 이전 실패는 삭제하거나 성공으로 바꾸지 않았다.

마지막 실행 도착 30.702 s, RGB capture 31.633333333 s, 수신 31.702 s. 실제 영상에서 분홍색 사람 대체 캡슐과 설비 확인. RGB mean 186.65/std 50.51/640×360/81,316 bytes. 작은 PNG이므로 validator 파일 크기 150 KB 기준 전체 통과는 주장하지 않는다.

### 현재 한계 / 미검증

- 이 장면/목표/설정에서 2회 연속 검증한 결과이며 임의 목표·복잡한 지도·동적 장애물 전체 신뢰성을 뜻하지 않는다. map과 설비 bbox가 다르면 bridge attach가 거부한다.
- simulator ground-truth localization, 가상 평면 collision-ray scan이다. AMCL/SLAM, 실물 센서, 실제 하드웨어, ROS camera Image transport, VLM 검증은 하지 않았다.
- `arrived`, Nav2 `failed`, 수동 `cancelled`는 실제 실행 기록이 있다. `timed_out` 의미/경계는 fixture 시험이며 실제 Nav2를 기한까지 방치하는 시험은 하지 않았다.
- 정지 평가는 도착 후 1~4초 구간이다. 장시간 zero-command hold에서는 yaw drift가 관측돼 무기한 정밀 자세 유지까지 보장하지 않는다. 카메라 증거는 도착 직후 실제 새 프레임이다.
- 최종 capture 대기 중 timeline Stop/reset 감지 시 실패, 30 wall-second camera timeout 방어를 추가했다. 중간에 Stop시켜 캡처 실패를 유도하는 실제 시험은 아직 수행하지 않았다. 이는 실제 성공 캡처와 구분한다.
- 기존 사건 코어의 `Nav2Motion` stub을 이 GUI adapter로 연결하는 incident 통합은 아직 별도 작업이다. 이번 실제 결과는 `Nav2Inspection`/`InspectionRun` JSON으로 제공한다.

## GUI 실행 / 재실행

현재 HAI-CLAW GUI와 `haiclaw-nav2` 컨테이너는 남겨 두었다. GUI `HAI-CLAW | Nav2 inspection`의 x=3, y=1.3, yaw=180을 사용한다. **Reset Spot, navigate, capture**: 로봇 물리 상태만 Reset하고 3초 안정화 후 Nav2 목표 전송. **Cancel and stop**: action 취소 요청 + 즉시 zero command. 상태 표시와 run별 result.json으로 arrived/failed/cancelled 및 RGB 저장을 확인한다. 임의 target은 별도 검증 대상이다.

완전히 새로 실행할 때, workspace에서 두 터미널:

```bash
# 터미널 1: 설치된 파생 이미지 사용, 외부 다운로드 없음
bash scripts/start_nav2.sh

# 터미널 2: 새 소유 GUI/Spot 장면 + ROS adapter + 목표 입력 UI
python3 scripts/nav2_gui.py
```

기존의 **동일 HAI-CLAW Spot 장면**에 컨트롤러/UI만 다시 연결할 때:

```bash
python3 scripts/nav2_gui.py --attach
```

`--attach`는 기존 action을 취소하고 보행을 hold로 만든 뒤 이전 ROS node/update subscription을 정리한다. 사용자로 교체된 stage나 workspace 소유 표식이 다른 stage는 거부한다. USD를 새로 생성하지 않는다. `nav2_gui.py` 기본 실행은 이미 배치된 Spot demo를 무단 교체하지 않고 거부하므로 `--attach`를 사용한다. ROS 없이 실행한 이전 GUI는 loader 환경을 hot-patch하지 않으며, 사용자가 저장·종료 후 새 launcher를 실행해야 한다. 전역 ROS/Codex 설정을 바꾸지 않는다.

정리할 경우 이 작업 컨테이너만 `docker stop haiclaw-nav2`로 종료하고 GUI는 사용자가 닫는다. 다른 인스턴스를 종료하지 않는다.

추가 실제 검증 명령:

```bash
python3 scripts/nav2_gui.py --attach > artifacts/nav2/attach_verified.log 2>&1
python3 /home/jude/isaac_ws_61/IsaacLab/.venv/lib/python3.12/site-packages/isaacsim/skills/isaac-sim-remote/scripts/isaacsim_send.py --context spot --timeout 650 --execution-timeout 650 --file scripts/nav2_gui_replay_check.py > artifacts/nav2/gui_precise_replay.log 2>&1
python3 /home/jude/isaac_ws_61/IsaacLab/.venv/lib/python3.12/site-packages/isaacsim/skills/isaac-sim-remote/scripts/isaacsim_send.py --context spot --file scripts/nav2_postcheck.py > artifacts/nav2/precise_replay_postcheck.log 2>&1
python3 /home/jude/isaac_ws_61/IsaacLab/.venv/lib/python3.12/site-packages/isaacsim/skills/isaac-sim-remote/scripts/isaacsim_send.py --context spot --file scripts/nav2_final_status.py > artifacts/nav2/final_status.log 2>&1
```
