# TRACE / DGX Spark 작업 요약

HAI-CLAW의 표시 이름은 TRACE로 전환했습니다. Python 패키지는 호환성을 위해 `haiclaw`를 유지합니다.

## 지금 되는 것

Isaac Sim 6.2.0 + Spot 물리 보행 + ROS 2 Jazzy/Nav2 + Ollama Qwen3-VL 8B를 연결했습니다. 실제 RGB에서 visible → occluded를 인식하고 사건을 생성하여 이동, 도착 이후 새 촬영, VLM 판단, 기한 종료까지 실행했습니다.

검증 실행 `263c92fc-bb26-492b-869d-d822a8e2e2ab`: 실제 이동 6.771m, 도착 40.242s, 촬영 41.200s, 후속 추론 29.061 wall초. 모델은 누운 자세와 pixelated texture를 보고했습니다. 정책은 확정을 보류하고 81.502 simulation초에 `escalated_unknown`으로 종료했습니다. 안전 확인이나 사고 확정 성공으로 해석하지 않습니다. 코어·계약 테스트 61개 통과 기록이 있습니다.

## 코드 안내

| 경로 | 역할 |
|---|---|
| `scripts/env_spark.sh` | 프로젝트 환경·SDK·ROS 경로 |
| `scripts/start_ollama.sh`, `configs/vlm_local.json` | 로컬 모델 서버와 추론 설정 |
| `src/haiclaw/providers/ollama.py` | Ollama 호출, JSON Schema와 근거 ID |
| `src/haiclaw/closed_loop.py` | 관측 소실·이동·추론·사건 기한 연결 |
| `scripts/prepare_closed_loop.py` | TRACE 전용 시뮬레이션 준비·재사용 |
| `scripts/closed_loop_scene.py` | 시나리오·카메라·센서 시각 |
| `scripts/run_closed_loop.py` | 실제 폐루프 실행·감사 기록 |
| `scripts/spot_lifecycle.py` | Spot 정책·보행 수명주기 |
| `tests/test_closed_loop.py`, `tests/test_ollama.py` | 폐루프·응답 계약 테스트 |
| `dashboard/` | 실제 실행 기록을 탐색하는 읽기 전용 웹 UI |

## 주요 문제와 수정

- 이전 PC 절대 경로 → 프로젝트 환경 스크립트로 교체.
- 없는 Docker 기반 이미지 → `ros:jazzy-ros-base` 사용.
- Ollama 서비스 작업 경로 오류 → WorkingDirectory 수정.
- 컨텍스트 262144로 과도한 메모리 사용 → 8192로 제한, GPU 사용 약 6.6GB.
- Qwen thinking에서 토큰 소진·최종 JSON 누락 → 출력 4096 토큰·180초 제한 적용.
- evidence_ids 문자열 출력 → JSON Schema로 배열 및 올바른 ID 강제.
- 장시간 정지 후 이동 명령에도 보행 정체 → 현재 측정 자세에서 공식 `RobotPolicyRunner.initialize()`로 정책/actuator 재초기화. 이동 시작 시 teleport/reset 사용하지 않음.
- cuSPARSELt 내부 wheel 플랫폼 태그 경고는 남아 있음. 라이브러리 로드·GPU tensor 연산 확인. 메타데이터를 변조하지 않음.

## 실행 명령

```bash
cd /home/juhwan/문서/ChatGPT/ROSCLAW/TRACE
source scripts/env_spark.sh
systemctl --user status trace-ollama.service
python scripts/prepare_closed_loop.py
python scripts/run_closed_loop.py --case lying_on_floor --budget 70
PYTHONPATH=src python -B -m unittest discover -s tests -v
```

저장 이미지 독립 추론: `python scripts/vlm_local.py <png 경로>`.

대시보드 데이터 갱신과 로컬 실행:

```bash
python3 dashboard/export_data.py
python3 -m http.server 8765 --bind 127.0.0.1 --directory dashboard/dist
```

브라우저에서 `http://127.0.0.1:8765`를 엽니다. 현재 export는 위 검증 실행과 대응 Nav2 기록을 명시적으로 선택합니다. 다른 실행을 표시하려면 exporter의 두 경로를 함께 바꾸고 다시 내보냅니다. 정적 배포본 갱신에는 재배포가 필요합니다. 원본 모델 reasoning과 로컬 파일 절대 경로는 export에서 제외합니다.

## 한계 / 다음 작업

통합 검증은 lying_on_floor 1건입니다. normal_work, insufficient_view는 생성기만 제공되며 통합 검증이 남았습니다. 마네킹, 시뮬레이터 정답 위치 localization, PhysX collision ray를 사용합니다. 실물 및 외부 신고는 연결하지 않습니다. 영상 노이즈 개선, 다중 위치 재관측, 새 서버부터 전체 준비 명령 검증이 남아 있습니다. 대시보드는 저장 기록 재생이며 실시간 스트리밍·로봇 제어 기능은 없습니다.

세부 기록: [설치](SPARK_SETUP.md), [실제 폐루프](CLOSED_LOOP.md), [전체 작업 이력](WORKLOG.md). 이전 PC 기록과 이번 Spark 검증을 구분합니다.

비공개 배포: https://trace-spark-mission-control.sweethinny15.chatgpt.site

## 네이티브 프로그램 UI (2026-10-27)

브라우저와 별개로 GTK 데스크톱 프로그램을 추가했습니다. 시스템에 설치된 GTK를 사용하며 추가 패키지 다운로드는 없습니다. 앱 목록에서 **TRACE Monitor**를 실행하거나 아래 명령을 사용합니다.

```bash
./scripts/trace_desktop.sh
```

- 왼쪽 큰 화면: Isaac Sim의 고정/몸통 RGB 카메라. 약 1초 간격으로 실제 센서 버퍼를 읽습니다. 창 크기와 분할선으로 영상/텍스트 비중을 조절할 수 있습니다.
- 오른쪽 큰 화면: 로컬 Ollama의 `thinking` 토큰과 `content` JSON을 실시간 표시합니다. 모델 출력과 스키마 검증 결과를 구분합니다.
- `현재 프레임 Qwen 분석`: 선택한 화면을 고정 저장하고 실제 Qwen 추론을 실행합니다. 수동 프레임 분석은 사건 정책이나 이동을 실행하지 않습니다.
- 폐루프 실행기 또한 새 실행부터 같은 추론 스트림 로그를 기록하므로 프로그램에서 확인할 수 있습니다. 이미 시작된 이전 실행에는 소급 적용되지 않습니다.
- 프로그램은 시뮬레이션을 자동 재생/초기화하지 않습니다. 현재 시뮬레이션이 일시정지이면 마지막 센서 프레임과 일시정지 상태를 명시합니다. Isaac Sim 전체 편집기/3D orbit viewport가 아니라 실제 RGB 카메라 화면입니다.
- 로컬 로그: `artifacts/live/qwen.jsonl`, 카메라 수신 상태: `artifacts/live/camera_status.json`. 프로그램 시작 시 과거 추론 로그는 건너뜁니다.
- 창을 닫으면 모니터와 해당 창에서 시작한 분석 프로세스만 종료합니다. Isaac Sim·Ollama·별도 폐루프 실행기는 종료하지 않습니다.

코드: `scripts/trace_desktop.py`, `scripts/trace_desktop.sh`, `scripts/vlm_stream.py`, `scripts/qwen_events.py`, `src/haiclaw/providers/ollama_stream.py`.

### 프로그램 v2: 전체 장면과 ROS 그래프

프로그램 상단 탭을 전환합니다.

- **실시간 장면 / Qwen**: 왼쪽 1280×720 전체 작업구역 관찰 영상, 오른쪽 고정/몸통 카메라와 Qwen 출력. `로봇 따라가기`로 설명용 카메라만 로봇 중심으로 이동합니다. 판단 카메라에는 영향을 주지 않습니다. JPEG 연속 프레임 방식이며 실측 수신 약 5–6 FPS(현재 paused 환경); WebRTC나 30 FPS를 보장하지 않습니다. 실행 시 GPU 부하에 따라 달라집니다.
- **ROS 노드 / 토픽**: 실제 기존 `ros_bridge` 노드에서 DDS graph를 읽어 약 5초마다 갱신합니다. 기본 `/scan`, `/odom`, `/plan`, `/cmd_vel` 연결을 표시합니다. `전체 토픽`, 토픽 검색, 토픽 선택, 확대/축소와 스크롤을 지원합니다. 토픽 선택 시 타입·발행자·구독자·QoS 상세를 표시합니다. 화살표는 발견된 연결 구조이며 실제 전달 성공·메시지율을 측정한 표시가 아닙니다.
- 이번 조회: 노드11 / 토픽59. 외부 컨테이너의 Nav2 노드까지 포함되며 별도 fixture 그래프를 사용하지 않습니다.
- 카메라와 Qwen은 Python/로컬 HTTP로 연결되어 있으므로 ROS 노드로 꾸며 넣지 않았습니다. 전체 장면은 `/World/TraceOverviewCamera`라는 관찰 전용 카메라이고 모델 입력에 사용하지 않습니다.
- 추가 코드: `scripts/monitor_scene.py`, `scripts/monitor_ros.py`, `scripts/monitor_graph_ui.py`. 실행 명령은 동일합니다.

### 프로그램 v3: 전체 시스템 / VSS 비교

세 번째 탭의 선택 메뉴에서 **전체 시스템 연결**, **도구 / 에이전틱 구성**, **NVIDIA VSS 비교**를 전환합니다. TCP/ROS/HTTP/로컬 파일 경로와 현재 자동화·미구현 agent 기능을 구분합니다. VSS는 공식 문서 기반 비교이며 설치·통합·벤치마크하지 않았습니다. 상세: [전체 구성 및 VSS 비교](VSS_COMPARISON.md).

### TRACE 하네스 v1

고정 baseline과 별도인 모델 선택형 하네스를 추가했습니다. [도구 계약·실행·검증 범위](HARNESS.md)를 참조하세요. 프로그램 **에이전트 실행** 탭에서 시작·중단·모델 선택과 실제 도구 결과를 볼 수 있습니다. 전체 시스템 탭에서도 하네스와 baseline 구성을 따로 표시합니다.
