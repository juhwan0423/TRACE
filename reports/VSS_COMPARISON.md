# TRACE 전체 구성과 NVIDIA VSS 비교

확인일: 2026-10-27. TRACE는 소스 및 기존 실행 기록 기준, VSS는 NVIDIA 공식 3.3 문서 기준입니다. **VSS 설치·연결·추론·성능 벤치마크는 하지 않았습니다.**

## 현재 시스템

| 경로 | 실제 인터페이스 | 역할 |
|---|---|---|
| 실행기 ↔ Isaac Sim | localhost TCP 8226 Python Server | 캡처/이동/상태 함수 호출, JSON 메타데이터 반환 |
| 카메라 → 실행기 | Isaac RGB → 로컬 PNG 파일 | 영상과 센서 시각 확보 |
| Isaac Sim ↔ Nav2 | ROS 2 DDS / DOMAIN 173, NavigateToPose action | scan/odom/TF/clock 공급, plan/cmd_vel 및 action 결과 수신 |
| 실행기/사건 코어 ↔ Qwen | Ollama localhost11434 `/api/chat` | RGB·prompt·schema 입력, thinking/content 스트림 |
| 모델 관측 → 사건 판정 | SingleFrameVLM 검증 → IncidentVLM → Incident | 근거 ID, 시각, 품질, 기한 검증 |
| 실행기/adapter → 프로그램 | 로컬 JSON/JSONL | 결과·추론 출력 표시 |
| Isaac Sim → 프로그램 | TCP를 통한 JPEG 프레임 | 설명용 전체 장면 + 판단 카메라 표시 |

전체 장면 관찰 카메라는 모델 입력이 아닙니다. Qwen은 ROS를 직접 호출하지 않습니다. ROS 탭의 endpoint 그래프는 실행 중 DDS에서 읽지만, 세 번째 탭의 전체 구성도는 코드 기반 설명도입니다.

## 도구와 에이전트의 현재 수준

`trace_capture`, `inspection.start/cancel`, `trace_snapshot`, `adapter.infer`가 도구에 해당하는 Python 함수입니다. 호출 순서는 `run_closed_loop.py`가 정합니다. `ClosedLoop`/`Incident`는 규칙 기반 사건 관리자입니다. Qwen의 출력은 제한된 관측 JSON이며 도구 호출 계획이 아닙니다.

현재 미구현: LLM planner, Qwen의 자율 tool selection, MCP 도구 서버, 적응형 관찰 위치 선택, 영상 기억/검색, 다중 에이전트 실행 구조. Nav2 behavior tree와 Spot 보행 정책은 존재하지만 LLM agent와는 별개입니다. 프로젝트를 개발한 AI 도구의 기능을 TRACE 제품 기능으로 세지 않습니다.

## 관제에 단일 프레임 VLM을 붙였을 때 드러난 문제

- 기록 263c92fc의 wall latency는 초기44.174초, 소실57.849초, 후속29.061초입니다. 한 실행의 세 요청이며 p50/p95 추정치가 아닙니다.
- 초기와 소실 관측은 VLM 완료를 순차 대기합니다. 사건 생성도 소실 응답 이후이므로 실제 가림부터 사건 시작까지의 지연은 별도로 측정해야 합니다.
- 현재 `think=True`, `num_predict=4096`, `num_ctx=8192`입니다. thinking 생성량·영상 처리·GPU 경쟁·큐 대기·cold start별 기여는 아직 프로파일링하지 않았습니다. 스트리밍은 출력을 일찍 보여주지만 검증 가능한 최종 JSON 완료를 자동으로 앞당기지는 않습니다.
- 단일 프레임에는 움직임·전후 상태의 정보가 부족합니다. 카메라 수만 늘린다고 해결되는 문제는 아닙니다.
- 누운 자세를 봤어도 영상 한계 때문에 확정을 보류했습니다. 현재 정책은 다른 지점/시각을 선택해 불확실성을 줄이지 못하고 기한에 미확인 인계합니다.
- 사건 예산70초는 simulation clock입니다. wall latency와 같은 축으로 비교하면 안 됩니다. 시뮬레이션 속도·렌더링 부하를 함께 기록해야 합니다.

## VSS와의 구조 비교

| 항목 | 현재 TRACE | NVIDIA VSS 문서상 구성 |
|---|---|---|
| 분석 단위 | 단일 RGB 프레임 | 저장/스트리밍 영상 분석, 선택한 프로필별 처리 |
| 관측 경로 | VLM 직접 관측 | CV/VLM/embedding 모듈 및 downstream 분석 |
| 에이전트 | 고정 실행기 + 규칙 | 상위 에이전트, 보고 에이전트, MCP 도구 경로 |
| 맥락 확보 | 새 로봇 프레임 1장 | 클립·스냅샷·검색 등 영상 도구 |
| 물리적 추가 관측 | Nav2로 로봇 이동 | TRACE의 로봇 이동 정책을 대체한다고 가정하지 않음 |
| 위험 판정 | 근거/기한 규칙, 로컬 모의 인계 | 알림 검증 등 선택 가능한 워크플로 |
| 이 장비의 지연 | 위 3요청 측정값 존재 | N/A — 미실행 |

VSS는 CV/VLM·분석·에이전트 계층을 구분한 참조 아키텍처입니다. 모든 구성요소를 한 번에 사용하는 필수 단일 파이프라인은 아닙니다. [NVIDIA 아키텍처](https://docs.nvidia.com/vss)

Direct Video Analysis는 영상 업로드 기반 분석 경로이고, Agent 구성에는 MCP 도구를 통한 클립·사건 조회와 보고가 포함됩니다. 비교 실험은 이런 독립 경로를 사용해 TRACE와 분리할 수 있습니다. [NVIDIA Agent 설명](https://docs.nvidia.com/vss/vision-agent/vss-agents/agent-overview)

공식 blueprint의 core engine 지원 목록에는 DGX Spark가 포함됩니다. 다만 특정 프로필의 ARM64 이미지, 모델 메모리 및 Isaac Sim과의 동시 실행 여유는 별도 확인 대상입니다. [공식 Blueprint 카드](https://build.nvidia.com/nvidia/video-search-and-summarization/blueprintcard)

## 독립 비교 실험안 — 아직 실행하지 않음

1. 정상/누움/가림/저화질을 포함한 동일한 원본 영상과 정답 시각을 준비합니다. 기존 정지 영상 3장만으로 시간적 분석 성능을 평가하지 않습니다.
2. A는 원본의 지정 시각 프레임에 현재 Qwen을 호출합니다. B는 동일 원본/구간을 별도 VSS 영상 분석 또는 alert verification 프로필로 평가합니다. 영상 전체 미래 정보를 B에만 주는 비교를 피합니다.
3. 구성 효과와 모델 효과를 분리합니다. 모델이 다르면 모델+시스템 비교라고 명시합니다. VSS에 동일 모델을 지원하는 구성이 확인되어야 동일 모델 비교라고 할 수 있습니다.
4. 동일 가용 시간 구간·판정 기준·반복 횟수를 적용하고 cold/warm run을 나눕니다. 사고 판단을 억지로 강제하지 않고 판단불가도 기록합니다.
5. 첫 유효 관측/최종 판정 wall latency, p50/p95, 오탐·미탐·판단불가율, 처리량, GPU 메모리를 측정합니다. 타임아웃·미완료를 분모에서 빼지 않습니다.
6. VSS 결과를 로봇이나 실제 신고에 연결하지 않고 오프라인 결과 파일끼리 비교합니다. Isaac 동시 실행 여부도 별도 실험 조건입니다.

현재 결론: VSS와 구조 비교는 가능하고 UI에 반영했습니다. 성능 우열은 아직 판단할 수 없습니다.
