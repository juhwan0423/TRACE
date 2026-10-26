# HAI-CLAW — 시뮬레이션 MVP

사람 관측 소실 사건의 기한 관리, Spot 보행을 통한 확인 지점 이동, 도착 후 카메라 관측을 실험하는 프로젝트입니다. 실제 하드웨어 제어는 범위 밖입니다.

| 구성 | 현재 검증 수준 |
|---|---|
| 사건 코어 | 촬영 시각·세대·출처 품질·이동 시도·기한 전이 회귀 테스트 |
| Spot | 공식 Isaac Sim 정책으로 GUI 보행·회전·정지 및 Reset 검증 |
| Nav2 | Jazzy Docker 연결, 기본 목표 실제 도착 및 새 몸통 RGB 확보 |
| VLM | Gemini ER 2 어댑터 및 fixture 검증; 실제 API 호출은 미실행 |
| 전체 온라인 폐루프 | 미완료; VLM CLI는 저장된 도착 근거의 사건 재생 평가 |

전체 테스트 56개 통과. 아래 명령은 API/Isaac 실행 없이 코어·계약 테스트와 저장 캡처를 검사합니다.

```bash
PYTHONPATH=src python3 -B -m unittest discover -s tests -v
```

저장소에는 소스, configs, ROS/Nav2 구성, 보고서와 선별된 캡처를 포함합니다. 런타임 캐시·USD 백업·대부분의 실행 로그는 로컬에 보존하고 Git에서 제외합니다. 보고서의 제외된 산출물 링크는 원래 workspace에서만 열립니다. 저장된 VLM 메타데이터와 일부 실행기는 이 머신의 절대 경로를 포함하므로 다른 머신에서는 설치 경로 설정과 캡처 재생성이 필요합니다. 공식 Isaac Sim 설치 파일·모델·Docker 이미지는 포함하지 않습니다.

## Gemini ER 2 단일 프레임 관측

도착 후 RGB 세 장과 API 어댑터를 준비했다. 실제 API 추론은 아직 실행하지 않았다. [실행 및 검증 보고서](vlm_report.md), [입력 영상 화면](artifacts/vlm/run_1792987006415864192/index.html).

```bash
python3 scripts/vlm_run.py --cases artifacts/vlm/cases.json  # 호출 없는 미리보기
read -rsp 'Gemini API key: ' GEMINI_API_KEY
export GEMINI_API_KEY
python3 scripts/vlm_run.py --cases artifacts/vlm/cases.json --allow-api
unset GEMINI_API_KEY
```

`--allow-api` 실행 시 세 RGB가 Google로 전송되며 과금될 수 있다. 키는 파일에 저장하지 않는다. 출력된 index.html에서 이미지·판단·지연·사건 이력을 확인한다. 현재 실행은 저장된 근거의 사건 재생 평가이며 실시간 GUI 사건 루프의 자동 호출은 아니다.

# HAI-CLAW simulation-only MVP

프로젝트 요구사항은 `implementation_guide.md`, 공식 Isaac Sim skills 사용 절차는 `AGENTS.md`에 있다. 고정/이동 카메라 가림 실험에 이어 공식 Spot PhysX 정책의 실제 보행·정지·Reset과 가림 장면 waypoint 이동을 검증했다. 사건 코어와의 연결, 사람 탐지, ROS는 미완료다.

## 공식 Spot GUI 데모

```bash
cd /home/jude/isaac_ws_61/haiclaw_ws
python3 scripts/spot_gui.py --scene flat
```

**HAI-CLAW | Official Spot Policy** 패널의 **Run / Reset validation** 버튼으로 자세 유지→저속 전진→회전→정지를 직접 볼 수 있다. **Zero velocity (keep balance)**는 정지 명령을 주면서 균형 제어를 유지한다. GUI를 닫았다면 위 명령으로 다시 연다.

가림 장면으로 전환하려면 `python3 scripts/spot_gui.py --scene occlusion --replace-demo`를 실행하고 **Reset and follow waypoints**를 누른다. 기존 소유 demo만 백업·정리 후 교체하며 다른 사용자 stage는 거부한다. USD만 열어서는 정책이 실행되지 않는다. [Spot 보고서](spot_report.md)에 실제 수치·자산 경로·lifecycle·제한을 기록했다.


## 재현

작업 위치: `/home/jude/isaac_ws_61/haiclaw_ws`.

```bash
# 터미널 1: 전용 headless Python Server. 기존 8226 리스너가 있으면 거부한다.
bash scripts/start_sim_server.sh > artifacts/logs/server.log 2>&1
# 터미널 2: app ready 확인 후 실행
python3 scripts/run_occlusion.py --timeout 300
PYTHONPATH=src python3 -B -m unittest discover -s tests -v
```

처음에는 로컬 RTX 셰이더 컴파일로 수분이 걸릴 수 있다. 새 인스턴스를 반복 실행하지 말고 로그를 확인한다. 서버는 loopback 127.0.0.1:8226, 공식 설정 기본값인 로컬 인증 없는 모드다. 외부에 포트를 공개하지 않는다. 스크립트는 `/haiclaw/workspace` 소유 표시가 없는 GUI에서 장면 교체를 거부한다. 설정은 프로세스 및 workspace 경로에 한정하고 ROS 자동 로딩은 끈다.

`ISAAC_LAB_DIR` 및 `ISAAC_SIM_DIR`로 설치 위치를 설정할 수 있다. pip 환경의 Python으로 설치된 `isaacsim.main()`을 호출하며 source-build용 `python.sh`나 `_build` 경로를 사용하지 않는다. EULA 동의를 새로 설정하지 않는다.

## 결과

`artifacts/occlusion/`에 RGB PNG 5장, `scene.usda`, `results.json`을 생성한다. 입력은 고정된 수치 배치이고 난수 연산은 없으며 seed=7은 메타데이터다. 카메라 이동은 좌표 변환이며 로봇의 물리 이동이 아니다. 분할 마스크는 렌더러의 정답 라벨로, 정책·탐지 모델의 출력이 아니다. 현재 기록 시간은 읽기 시점의 시뮬레이션 시각이고 센서 capture timestamp 검증은 별도 미완료다.

## GUI에서 함께 확인할 최소 단계

1. 사용 중인 GUI의 현재 장면을 먼저 저장한다. 다른 인스턴스를 종료하지 않는다.
2. `artifacts/occlusion/scene.usda`를 열고 카메라를 `/World/FixedCamera`, `/World/MovingCamera`로 번갈아 선택한다.
3. 함께 라이브 조작할 때만 Python Server를 사용한다. 공식 문서는 설치 경로의 `exts/isaacsim.code_editor.python_server/docs/Overview.md`, `SETTINGS.md`다.
4. GUI 실행 명령에 `--enable isaacsim.code_editor.python_server`를 추가한다. host는 `127.0.0.1`을 유지하고, 8226 사용 중이면 다른 포트를 정한다. 인증을 켠 기존 GUI는 토큰을 공개하지 않는다. 먼저 health와 stage 정보만 읽고, 장면 변경을 함께 진행한다.

기존 GUI를 실험 소유 세션으로 표시하거나 자동 초기화하지 않는다. 코어 결함 회귀 테스트는 모두 일반 테스트로 전환했다. 현재 전체 56개 테스트가 통과하며 expected failure는 없다. 현재 코어 검증 로그는 `artifacts/logs/core_regression_tests.txt`다.

## 코어 호출 계약

- `LossTracker.reset()`은 generation을 증가시킨다. 새 근거와 새 Incident에 그 generation을 전달한다. 비동기 응답에는 요청 당시의 Evidence를 그대로 사용한다.
- tracker는 한 source/subject/track 스트림을 처리한다. 여러 카메라는 각각 tracker를 두고 Incident의 근거 처리에서 결합한다.
- 이동 시작은 `attempt = incident.motion('moving', now)`, 응답은 `incident.motion('arrived', now, attempt_id=attempt)`처럼 시도 ID를 전달한다. 실패 후 재시도는 새 moving으로 시작한다.
- `tick(deadline)`과 같은 시각의 위험 근거는 호출 순서와 관계없이 DANGER가 우선하며, 타이머가 먼저 신고했으면 alert_update 이벤트를 소비한다. deadline 이후 입력은 소급 보정하지 않는다. 안전 종료는 deadline 이전에만 가능하다.
- 세부 규칙과 fixture 검증 범위는 `implementation_report.md`의 현재 상태 절을 참고한다.

### Nav2 확인 위치 이동과 도착 후 캡처

기존 Jazzy 기반 `haiclaw-nav2:jazzy` 파생 이미지가 설치되어 있다. 새 세션에서는 터미널별로 `bash scripts/start_nav2.sh`, `python3 scripts/nav2_gui.py`를 실행한다. 이미 열린 동일 HAI-CLAW Spot 장면에는 `python3 scripts/nav2_gui.py --attach`를 사용한다. GUI에서 목표 x/y/yaw를 입력하고 **Reset Spot, navigate, capture**를 누른다. 기본 검증 목표는 `(3, 1.3, 180°)`이다. **Cancel and stop**으로 취소한다.

최종 기본 목표는 GUI Reset 포함 2회 실제 보행·도착·새 RGB·정지 검사 통과. 현재 localization은 simulator ground-truth, 장애물 센서는 PhysX collision rays이다. [Nav2 보고서](nav2_report.md)에 정확한 명령, 모든 실패, 검증 수준, 이미지와 한계를 기록했다. 실시간 사건 코어 Nav2 공급자 연결과 온라인 VLM 자동 호출은 후속 단계다.
