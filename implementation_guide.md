# HAI-CLAW 구현 가이드

작성일: 2026-10-23 (Asia/Seoul)
작업 경로: /home/jude/isaac_ws_61/haiclaw_ws

## 1. 목표와 연구 범위

고정 카메라에서 관측이 끊긴 작업자를 미해결 안전 사건으로 유지하고, 이동 로봇의 추가 관측으로 확인하거나 기한 내 모의 신고하는 시뮬레이션 전용 MVP를 구현한다.

첫 완료 목표: 사람 진입 → 설비 뒤 가림 → 사건 생성 → 확인 위치 이동 → 새 영상 확보 → 정상 확인/추가 확인/위험 신고/미확인 인계.

HAI-CLAW는 ROSCLAW와 분리된 프로젝트다. ROSCLAW 저장소를 변경하거나 전체 구조를 복사하지 않는다. 새 JEPA, PSQ 압축, 보행 정책 학습, 실물 로봇, 실제 신고 서비스는 이번 범위 밖이다. 모든 신고는 로컬 이벤트다.

핵심 가설: 같은 대응 기한과 센서·이동 예산에서 필요한 증거를 수집하는 정책이 잘못된 안전 종료와 불필요한 신고를 줄일 수 있는가? 아직 검증된 성과가 아니다.

## 2. 실행 권한과 작업 원칙

- 이 workspace 내 소스·설정·문서 작성, 로컬 테스트, 기존 설치를 이용한 시뮬레이션 구현을 진행한다. 기존 파일은 보존하고 변경을 설명한다.
- 먼저 적용되는 AGENTS.md와 실제 설치를 확인한다. 버전·SDK·로봇 자산 경로를 추측하여 성공으로 보고하지 않는다.
- 요청 버전은 Isaac Sim 6.2.0이다. 상위 폴더 이름 isaac_ws_61은 버전 증거가 아니다. 설치가 6.1 등 다른 버전이면 사실을 기록하고, 시스템 업그레이드 없이 가능한 범위와 차이를 보고한다.
- 시스템 패키지 설치, 외부 경로 변경, 대형 모델 다운로드, 유료 API 호출, 로그인·비밀정보 변경은 별도 필요 사항으로 보고한다. 자격증명을 읽어 출력하지 않는다.
- 실물 ROS/DDS/serial/vendor 장치에 연결하거나 명령을 보내지 않는다. 시뮬레이션 ROS_DOMAIN_ID를 분리하고 실제 장치와 연결되지 않는 실행 구성을 사용한다.
- 환경이 부족하면 독립 코어·fixture 검증을 계속한다. fixture 통과를 Isaac Sim/ROS/Nav2/VLM 실증으로 표현하지 않는다.
- 문서만 만들고 멈추지 말고 사용 가능한 환경에서 코드와 테스트까지 진행한다. 기본 모델 설정을 유지하며 임의로 모델을 변경하지 않는다.

## 3. 단계별 구현과 완료 기준

### P0. 환경 조사

Python, ROS 배포판, Isaac Sim 실행 파일·버전, GPU, 기존 quadruped 자산·보행 컨트롤러, Nav2 설치 여부를 읽기 전용으로 조사한다. 발견 경로·명령·결과를 environment_report.md에 기록한다. GUI가 실행 중이면 기존 세션을 종료하거나 덮어쓰지 않는다.

완료: 사용할 실행 경로와 누락된 의존성이 분명하다.

### P1. 의존성 없는 사건 코어와 반복 실험

표준 Python 중심으로 observation, incident, action, evidence, decision, run 결과 자료구조를 작성한다. 정책과 시뮬레이터·추론 공급자를 분리한다. 시뮬레이션 시각과 wall-clock 처리시간을 별도 필드로 기록한다.

실제 상태(normal_work, exited, fallen 등), 관측 상태(visible, occluded, unavailable), 판단 상태(open, verifying, resolved_safe, danger_confirmed, escalated_unknown)를 분리한다. 실제 상태는 평가기에만 전달한다.

근거에는 id, source, capture_time, received_time, frame/artifact reference, 품질·판단 불가 이유를 둔다. 같은 근거를 반복 처리해 확신을 누적하지 않는다. 오래되거나 역순 도착한 프레임이 최신 확인을 덮어쓰지 않게 한다.

이동 성공·사람 재발견은 안전 종료가 아니다. 최신의 관련된 확인 근거가 있어야 종료한다. 기한 내 확인 실패는 escalated_unknown이며 안전 확인과 구분한다. 위험이 이미 확인되면 추가 관측 때문에 신고를 지연하지 않는다.

완료: 정상/쓰러짐/관측 실패 fixture를 같은 초기 관측으로 재생하고 사건 전이와 모의 신고를 검증한다.

### P2. Isaac Sim 장면과 시나리오

작은 작업 구역, 평평한 바닥, 가림용 설비 박스, 고정 RGB 카메라 1대, 사람 1명, 로봇개 1대와 전방 카메라를 구성한다. 순찰점과 확인점 2~3개를 설정 파일로 관리한다.

기존에 작동하는 보행 컨트롤러를 우선 재사용한다. 로봇 USD 로딩과 실제 보행 가능 상태를 구분한다. 보행이 막혀 kinematic 대체를 사용하면 명시하고 보행 검증으로 주장하지 않는다.

build_scene.py와 scenario_runner.py에 재현 가능한 생성·저장·시드·리셋·분기 제어를 구현한다. 정상 작업과 쓰러짐은 같은 진입/가림 장면 이후 분기한다. 사람 자산이 없으면 대체 모델을 명시하고 실제 사람 탐지 검증은 미완료로 남긴다.

완료: 고정 카메라에서는 보이지 않는 사람이 확인 위치의 로봇 카메라에서는 보인다. 두 시나리오를 동일 초기 상태로 반복한다. 가능하면 스크린샷을 저장한다.

### P3. ROS 2 연결

실제 설치 SDK에 맞는 ROS bridge와 bringup launch를 작성한다. /clock, use_sim_time, camera image/camera_info, TF, odometry, 이동 인터페이스를 정리한다. 이름은 설정 가능하게 하고 README에 실제 사용 이름을 적는다.

완료: 외부 ROS 노드가 두 카메라 영상을 수신하고 시뮬레이션 로봇의 전진·회전·정지를 확인한다. 센서 capture timestamp를 보존한다.

### P4. 이동 공급자

첫 공급자는 지정 경로/waypoint 이동이다. inspect(target_id) 요청이 arrived/failed/timed_out/cancelled 결과를 반환하게 한다. bounded velocity, stop, timeout을 구현한다. ground-truth pose를 이용하면 초기 통합용임을 기록하고 사람 ground truth는 전달하지 않는다.

Nav2는 같은 인터페이스의 별도 공급자로 구현한다. map/localization, map→odom→base TF, footprint, LiDAR 또는 depth→costmap, cmd_vel→보행 컨트롤러 경로가 준비된 뒤 활성화한다. Nav2가 다리 보행 정책을 대신한다고 가정하지 않는다.

완료: 확인 지점 도착 후 새 카메라 프레임을 요청한다. 도착 실패나 이동 시간 초과도 사건 관리자에게 반환한다.

### P5. YOLO 탐지와 추적

모델 경로를 명시적으로 받는 선택적 perception provider를 작성한다. 로컬 가중치가 없으면 자동 대형 다운로드 없이 fixture provider로 코어를 검증한다.

출력은 사람 bbox, confidence, camera_id, track_id, capture timestamp, evidence reference다. 최초에는 한 사람으로 제한하고 완전한 cross-camera re-ID를 주장하지 않는다. 탐지 누락만으로 퇴장/사고를 확정하지 않는다.

완료: 사람 가림 시 마지막 관측과 최근 짧은 구간 참조를 보존하고 관측 소실 이벤트가 발생한다.

### P6. 규칙 기반 폐루프

고정 시간 신고 정책과 규칙 기반 확인·종료 정책을 구현한다. latter는 기한과 근거 유효성을 고려하는 실질적인 기준선이어야 한다. 이동→새 영상→판정 결과까지 연결한다.

완료: 정상과 위험 분기 각각에서 자동 사이클을 수행한다. 상태 판단이 fixture라면 전체 결과를 fixture-assisted로 명시한다.

### P7. VLM 공급자

설정 가능한 local/remote adapter 인터페이스와 mock provider를 구현한다. 공급자·endpoint·모델이 미정이면 임의 유료 호출 없이 설정 방법을 제공한다.

입력은 마지막 관측, 새 프레임/짧은 클립, 시간 및 출처다. 출력은 person_visible, observable_posture, distress_cues, insufficient_evidence, evidence_refs 등 제한된 schema로 검증한다. 진단이나 숨겨진 실제 상태를 확정하지 않는다.

새 이벤트·관측에서 호출하고 오래된 같은 프레임 반복 호출을 독립 증거로 세지 않는다. timeout, malformed response, unavailable에 대해 판단 불가로 처리한다. VLM 처리 중에도 사건 기한 처리가 살아 있어야 한다. 이미지 전송·호출은 공급자 설정 및 사용자 권한 내에서만 한다.

완료: 응답 정상/판단 불가/실패/지연을 테스트하며 실패가 안전 종료로 이어지지 않는다.

### P8. 평가와 제안 정책

우선 기준선 성능을 측정한다. 제안 정책은 확인 후보별 예상 정보 이득 또는 해소 가능성, 이동·관측 시간, 남은 기한, 위험 비용을 고려하는 설명 가능한 초기 heuristic으로 구현할 수 있다. 최적성이나 학습 성과를 주장하지 않는다. 파라미터·가정·각 행동 선택 이유를 기록한다.

비교군: fixed-time escalation, rule-based verification with evidence closure, proposed policy. 모든 정책에 동일한 관측·인식 공급자, 동일 시드, 예산을 사용한다. 이후 reacquisition-only closure와 evidence-required closure ablation을 추가한다.

지표: 위험 사건의 잘못된 안전 종료율, 위험 발생→신고 시간, 구별 가능한 관측 발생→신고 시간(정의 가능할 때), 불필요 신고, 미확인 인계, 기한 초과, 이동 거리, 호출 수, 처리 지연. 분모와 미종료 사례 처리를 명시한다. 항상 미해결로 남기는 정책이 유리하지 않게 한다.

완료: evaluate 명령으로 JSONL/CSV 요약을 생성하고 검증 수준별 결과를 분리한다.

## 4. 권장 구조

```text
haiclaw_ws/
  implementation_guide.md
  README.md
  environment_report.md
  implementation_report.md
  pyproject.toml
  configs/                 # scene, timing, policy, provider settings
  src/haiclaw/             # contracts, incidents, policies, evidence, evaluation
  src/haiclaw/providers/   # mock, perception, VLM, motion adapters
  scripts/                # environment check, scene, scenario, demo, evaluation
  ros2/                   # ROS packages, launch, Nav2 configs if available
  tests/
  artifacts/              # runs, evidence, reports; avoid committing large assets
```

기존 구성이 있으면 존중한다. 파일 분할은 필요한 수준으로 제한하고 빈 scaffold를 대량 생성하지 않는다.

## 5. 필수 의미적 테스트

- 관측 소실이나 로봇 도착만으로 안전 종료하지 않는다.
- 같은 프레임의 반복 처리와 오래된 프레임 도착이 잘못된 종료를 일으키지 않는다.
- 최신의 적절한 확인 근거로 정상 종료할 수 있다.
- 명확한 위험은 지체 없이 모의 신고한다.
- 이동 실패, VLM timeout, 센서 정지에도 기한 처리가 동작한다.
- reset 후 이전 에피소드의 근거나 비동기 응답이 유입되지 않는다.
- 정책 입력에 시나리오 분기 정답과 사람의 실제 좌표가 포함되지 않는다.

## 6. 이번 CLI 구현 의뢰

먼저 P0와 P1을 완성하고 사용 가능한 환경에서 P2 이후를 차례로 연결한다. 의존성이 부족해도 독립적인 코드와 검증을 진행한다. 미검증 SDK 호출을 추측으로 작성하고 완료 처리하지 않는다. 대규모 문헌 조사나 새로운 이론 연구로 돌아가지 않는다.

최종 보고는 한국어로 작성한다. 구현 파일, 실제 테스트 명령과 결과, fixture만 검증한 항목, 실제 Isaac Sim/ROS에서 검증한 항목, 미해결 사항, 사용자가 GUI에서 할 최소 작업, 다음에 실행할 정확한 명령을 포함한다.

공식 구현 참고: https://docs.isaacsim.omniverse.nvidia.com/6.2.0/ 및 설치된 로컬 예제. 로컬 설치와 문서 버전이 일치하는지 확인한다.
