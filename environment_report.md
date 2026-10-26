# 환경 조사 — 2026-10-23

## 범위 및 권한

작업 경로 `/home/jude/isaac_ws_61/haiclaw_ws`. 원본 가이드 보존. 기존 workspace/상위 AGENTS.md는 없었고 이번에 workspace AGENTS.md를 생성했다. 형제 IsaacLab 저장소는 수정하지 않았다. 설치된 Isaac Sim의 AGENTS.md와 skills/SKILLS.md를 읽고 공식 파일은 참조만 했다.

## 실제 조사 결과

| 항목 | 결과 | 검증 수준 |
|---|---|---|
| 시스템 Python | 3.12.3 | `python3 --version` 실행 |
| Isaac Python | `/home/jude/isaac_ws_61/IsaacLab/.venv/bin/python` | 실제 Kit 실행 |
| 설치 루트 | `/home/jude/isaac_ws_61/IsaacLab/.venv/lib/python3.12/site-packages/isaacsim` | 파일 및 패키지 메타데이터 |
| Isaac 버전 | 배포판 6.2.0.0, app 6.2.0, 런타임 상세 **6.2.0-rc.14** | metadata + startup 로그 + remote health |
| GPU | NVIDIA RTX 5090, VRAM 32607 MiB, driver 580.178.04 | nvidia-smi 실행 및 RTX 캡처 |
| 이전 GPU 오류 | 읽기 전용/제한 샌드박스에서 드라이버 접근 실패 | 현재 호스트 장애로 해석하지 않음 |
| ROS | 시스템 ros2 미발견. 설치 내 Jazzy rclpy/ROS bridge 존재 | 경로 확인, 전송 검증 없음 |
| Nav2 | 조사한 시스템/설치 범위에서 미발견 | 전체 디스크 부재를 단정하지 않음 |
| 보행 | quadruped_example.py 발견 | 소스 존재만 확인, USD·정책 로딩/보행 미검증 |
| YOLO | 시스템 및 Isaac venv에서 ultralytics 미발견 | find_spec 확인; 가중치 다운로드 없음 |
| GUI | 실험 시작 전 Isaac 프로세스 및 8226 리스너 미발견 | `ps -eo pid,comm`, `ss -ltnp 'sport = :8226'` |

## 사용 명령

```bash
python3 --version
nvidia-smi
nvidia-smi --query-gpu=utilization.gpu,memory.used,memory.total --format=csv,noheader
command -v ros2
ps -eo pid,comm
ss -ltnp 'sport = :8226'
/home/jude/isaac_ws_61/IsaacLab/.venv/bin/python -B -c 'import importlib.metadata as m; print(m.version("isaacsim"))'
sha256sum implementation_guide.md
```

가이드 SHA256: `09adb11f375e5b03dff4b0f4713e9eff925ba7253c9d6f67bbaf76c42ac66403`.

## 실행 주의 사항 및 발견

pip 설치에는 시도한 `isaacsim/kit/kit` 실행 파일이 없었다. 설치된 `isaacsim/__init__.py`의 `main()`을 확인해 기존 venv Python으로 실행했다. source-build 명령을 복사하지 않았다.

첫 Full 앱 기동은 기본 ROS bridge 자동 활성화를 시도했으나 로딩 경고 후 관련 확장이 종료됐다. ROS 노드·DDS publisher·장치 명령은 만들지 않았다. 후속 실행 스크립트는 `/isaac/startup/ros_bridge_extension`과 `ros_sim_control_extension`을 비워 자동 활성화를 끄고, ROS_DOMAIN_ID=173/localhost 설정을 프로세스에 한정한다.

Python Server는 설치 문서상 loopback 127.0.0.1:8226, require_auth 기본 false다. 기존 인증/자격증명은 읽거나 변경하지 않았다. 사용자 EULA 동의를 새로 설정하지 않았다. 사용자 설정 저장을 끄고 userConfigPath/XDG/cache/data/CUDA 캐시를 workspace로 지정했다. shader cache는 실제 렌더링이 생성한 로컬 데이터이며 모델 다운로드가 아니다.

첫 기동에서 셰이더 컴파일 및 viewport 준비 후 약 163초에 app ready가 나왔다. 조기 health 성공만으로 렌더러 준비 완료를 단정하면 안 된다. GPU 메모리 관측값 5648/32607 MiB, 여유 80% 이상. 실제 image 검증은 별도 수행했다.

## 2026-10-26 Spot 추가 검증

RTX 5090/Isaac Sim 6.2.0-rc.14 GUI에서 bundled PhysX Spot USD·정책·env·IO descriptor를 실제 로딩했다. `get_spot_spec()`로 해결한 정확한 경로와 크기는 `artifacts/spot/preflight.json`, 실제 모델 SHA256은 `model_verified.json`에 기록했다. 정책 약 0.78MB이며 대형 모델/전체 자산팩 다운로드는 하지 않았다. 공식 runner가 12관절에 바인딩하고 물리 보행을 실행했다. 자세한 실행·시간 설정·GUI 명령은 `spot_report.md` 참고. 사용자가 직접 GUI를 닫았다고 확인했으며 해당 프로세스 종료코드는 0이다.

## 2026-10-26 Nav2 Docker 및 실제 ROS 연결 추가 확인

호스트 `/opt/ros` 없음/PATH ros2 없음과 별개로 기존 Jazzy Docker가 있었다. 두 Jazzy 이미지의 `ros2 pkg list` 조사에서 Nav2 서버가 없음을 확인했고, 사용자 요청에 따라 기존 `ros2-jazzy-gazebo:latest` 기반 `haiclaw-nav2:jazzy`를 별도 빌드했다. 원본 이미지 변경/호스트 apt 설치 없음. 다운로드 사전 추정 89.5 MB. `ros2/nav2/Dockerfile`, 정확한 이미지 ID·명령·로그는 `nav2_report.md`에 기록.

새 이미지에서 `/opt/ros/jazzy`, `nav2_controller controller_server`, `nav2_planner planner_server` 확인. 실제 Isaac Sim bundled Jazzy rclpy와 컨테이너의 odom/TF/scan/cmd_vel/Nav2 action 연결 확인. domain 173, loopback UDP XML, host UID/GID, host IPC 사용. root 컨테이너에서는 토픽 발견만 되고 데이터 전달이 실패했으며 동일 UID/GID 후 전달 성공. 원인 내부까지 확정한 것은 아님.

실제 Nav2→공식 Spot 보행→확인 지점 도착→새 몸통 카메라 RGB 성공 run `artifacts/nav2/1792984808819520772`. Localization은 simulator ground-truth, scan은 PhysX collision rays, map은 장면 설비 형상에서 만든 정적 지도이며 AMCL/SLAM/RTX LiDAR 검증이 아니다. 실제 완료 수준과 후속 반복 실패는 `nav2_report.md` 참조.

최종 GUI Reset 포함 동일 목표 2회 연속 도착+fresh RGB+정지 검사 통과: `1792985258921926274`, `1792985384306864306`. 현재 컨테이너/GUI는 사용자 확인용으로 보존. 단일 ROS bridge node와 odom/scan publisher 각 1개 확인. 최종 실행 절차와 알려진 한계는 nav2_report.md 마지막 절을 따른다.

## 2026-10-26 VLM 환경 조사 및 Gemini 선택

조사 범위에서 Ollama 실행 파일/프로세스, vLLM 서버, 통상적 로컬 VLM listen endpoint, 로컬 모델 디렉터리를 찾지 못했다. Hugging Face cache 약 360KB는 kernel cache였으며 모델 weight를 확인하지 못했다. IsaacLab venv에는 torch/transformers가 있으나 패키지 존재를 모델 가용성으로 해석하지 않았다. GPU는 RTX 5090, 32607MiB 중 약 6686MiB 사용 관측. 이것은 머신 전체에 어떤 모델도 없다는 보장이 아니다.

사용자 후속 지시에 따라 Gemini Robotics ER 2 API로 선택했다. 표준 라이브러리 urllib 사용, 별도 SDK/대형 모델 다운로드 없음. API 키를 읽거나 저장하거나 실제 유료 요청을 실행하지 않았다. 키는 사용자가 shell의 GEMINI_API_KEY로 제공한다. 모델 계정 접근 권한/quota/실제 요청 성공은 미검증이다. 공식 endpoint와 structured REST 형식, 실행 명령은 vlm_report.md에 기록했다.

실제 Isaac/ROS는 기존 소유 GUI와 haiclaw-nav2 연결을 사용했다. 한 번의 실제 도착 후 세 장면의 새 RGB 확보, 원래 장면 proxy 복원 확인. 호스트 ROS/전역 설정/공식 설치 수정 없음. 검증 결과 artifacts/vlm/verification.json 및 unit_tests.log(56 pass). API 실제 결과는 없음.
