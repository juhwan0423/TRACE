# Gemini Robotics ER 2 관측 연결 — 2026-10-26

## 완료 수준

Gemini API 어댑터, 엄격한 단일 RGB 출력 schema, 비동기 사건 관리자 연결, 세 장면 실제 렌더링, 입력/결과 HTML 화면을 구현했다. **실제 Gemini 요청은 0회**다. 사용자가 키를 넣기 전이므로 실제 모델 응답·지연·최종 사건 판정은 미검증이며 dry-run 결과에는 null로 남겼다. Fixture 응답을 실제 추론으로 대체하지 않았다.

현재 실행기는 **저장된 실제 도착 근거를 사건 관리자에 재생하는 오프라인 평가 CLI**다. 추론 요청 자체는 `--allow-api` 실행 시 실제 API를 사용하지만, 사건 시계는 기록된 수신 시각부터 wall clock 1배속으로 재생한다. 실행 중인 Kit/ROS의 사건 타이머와 자동 연결한 온라인 폐루프는 아직 아니다.

## 모델과 실행

모델 ID는 `gemini-robotics-er-2-preview`다. 공식 [Robotics 문서](https://ai.google.dev/gemini-api/docs/robotics-overview)와 [generateContent Robotics 문서](https://ai.google.dev/gemini-api/docs/generate-content/robotics-overview), [구조화 출력 REST 예제](https://ai.google.dev/gemini-api/docs/generate-content/structured-output), [이미지 입력 문서](https://ai.google.dev/gemini-api/docs/generate-content/image-understanding)를 확인했다. streaming 모델을 사용하지 않는다.

Python 표준 라이브러리 HTTPS로 `https://generativelanguage.googleapis.com/v1beta/models/gemini-robotics-er-2-preview:generateContent`에 요청한다. 현재 공식 legacy generateContent REST 예제의 `generationConfig.responseFormat.text.schema` 형식을 따른다. 실제 계정의 모델 접근 권한·quota·이 요청의 서버 수락은 키를 넣은 첫 실행에서 확인해야 한다. SDK 설치/모델 다운로드는 없다. temperature=0, maxOutputTokens=2048, thinking 설정은 서버 기본값이다. 출력 잘림/차단은 판단 불가다.

workspace에서 실행:

```bash
cd /home/jude/isaac_ws_61/haiclaw_ws
# 네트워크 호출 없는 입력/화면 확인
python3 scripts/vlm_run.py --cases artifacts/vlm/cases.json

# 사용자가 직접 실행: 세 RGB 이미지를 Google API에 전송하며 과금될 수 있음
read -rsp 'Gemini API key: ' GEMINI_API_KEY
export GEMINI_API_KEY
python3 scripts/vlm_run.py --cases artifacts/vlm/cases.json --allow-api
unset GEMINI_API_KEY
```

키를 채팅/소스/설정 파일에 넣지 않는다. CLI는 `.env`를 자동으로 읽지 않는다. 환경변수와 `--allow-api`가 모두 있어야 요청한다. 키는 헤더에만 들어가고 URL·결과 JSON에 저장하지 않는다. 프록시/redirect/자동 재시도는 비활성화했다. HTTP 실패는 코드만 저장하며 자격증명을 반사할 수 있는 오류 본문은 저장하지 않는다. 정상 모델 응답 원문 및 schema 오류 응답 원문은 결과에 보존한다.

실행 결과 경로가 터미널에 출력된다. `artifacts/vlm/run_*/index.html`은 입력 이미지·관측·사건 상태·근거/결정 이력을 함께 보여 준다. 같은 디렉터리 `results.json`에는 원문, 응답 지연, inference_status, evidence ID, 촬영 시각, 이미지 SHA256이 저장된다. 현재 준비된 화면: [세 장면 dry-run](artifacts/vlm/run_1792987006415864192/index.html).

`--timeout` 기본 20초, `--incident-budget` 기본 30초다. 타임아웃은 API await를 종료하고 사건 tick은 계속된다. 내부 HTTP worker가 이미 진행 중이면 socket timeout까지 정리될 수 있지만 그 늦은 결과를 사건에 적용하지 않는다. 위험 외 관측은 기한까지 기다리므로 세 장면 평가에는 약 90초가 걸릴 수 있다. 기본 실행에는 API 호출이 없다.

## 입력, schema, 최초 종료 조건

모델에는 고정 지시문과 RGB 한 장, 불투명 UUID인 evidence_id, capture_time만 보낸다. 평가용 시나리오 이름·simulator 사람 좌표·goal·파일 경로·episode는 보내지 않는다. 모든 이미지와 도착 메타데이터를 전송 전 점검한다. 한 장으로 움직임, 정상 작업 여부, 응답성, 의식, 부상, 호흡을 추론하지 말도록 지시한다. 모델이 이 지시를 완벽히 준수하는지는 실제 추론 평가가 필요하다.

출력 필드는 정확히 다음 여섯 개다:

- person_visible: yes/no/uncertain
- posture: standing/seated/lying/unknown
- visible_risk_cues: 관측 징후 문자열 목록
- observation_limitations: 가림·화질 등 한계 문자열 목록
- needs_more_observation: boolean
- evidence_ids: 실제 입력 ID 한 개

추가 필드·잘못된 enum/type·다른 evidence ID·보이지 않는 사람의 단정적 자세는 schema 오류다. 서버 장애·차단·timeout·잘린 출력도 uncertain/unknown 및 추가 관측 필요로 기록한다.

최초 전이 규칙:

1. `yes + lying + needs_more_observation=false + limitations=[]`만 충분한 위험 근거로 코어에 전달하여 `danger_confirmed`로 종료한다. 의료 진단이나 실제 사고 확정이 아니라 시뮬레이션 위험 신고 조건이다.
2. standing/seated 또는 사람 재발견만으로 `resolved_safe`가 되지 않는다. 이번 단일 프레임 경로에는 안전 종료 조건을 두지 않았다.
3. 불충분/오류 관측은 verifying을 유지하고 기한에 `escalated_unknown`이 된다. 위험 징후 텍스트는 원문과 함께 보존하지만 임의 문자열을 별도 위험 규칙으로 실행하지 않는다.
4. 완료된 응답을 tick보다 먼저 처리해 정확한 기한의 유효 위험 근거가 unknown보다 우선한다. 기한 후 응답은 이미 종료된 사건을 소급 변경하지 않는다.
5. 요청은 `(episode, generation, motion_attempt, evidence_id)`에 결속한다. 이전 에피소드/이동 요청의 늦은 응답은 audit에 남기고 거부한다. 동일 키의 재요청도 억제한다. 코어의 source별 품질/촬영 시각 검사를 유지한다.

기존 `providers/vlm.py`는 이전 fixture adapter로 보존했다. 실제 Gemini 경로는 `providers/single_frame_vlm.py`와 `providers/gemini.py`, 실행기는 `scripts/vlm_run.py`다.

## 실제 장면 및 캡처 검증

외부 사람 자산을 다운로드하지 않고 USD primitive로 관절 모양·머리·안전모·작업복·손발을 가진 정적 인체 모형을 작성했다. 사실적 사람/애니메이션/인체 물리 검증은 아니다. normal_work는 작업대 앞 정적 포즈를 뜻하며 실제 작업 중이라는 정답을 모델에 주지 않는다. 누운 모형과 가림판 장면도 별도 생성했다.

기존 GUI의 소유 stage ID를 읽기 전용 검사하고 백업을 export했다. 기존 Nav2 GUI 실행기로 실제 Spot을 (3.0, 1.3, yaw 180도) 확인 지점까지 이동했다. 공식 policy runner/물리 보행을 그대로 사용했다. 공통 실제 도착 기록은 `artifacts/nav2/1792986891752088881/result.json`, arrival=31.542 s다. **한 번의 실제 도착 후 같은 시점 근처에서 세 장면 변형을 순서대로 촬영**했다. 세 번의 독립 Nav2 이동 성공으로 집계하지 않는다.

| 평가 장면 | 촬영 시각(s) | 위치 오차(m) | yaw 오차(rad) | 실제 추론 |
|---|---:|---:|---:|---|
| normal_work | 31.766666667 | .081454 | .104425 | 키 입력 대기 |
| lying_on_floor | 31.966666667 | .081335 | .101656 | 키 입력 대기 |
| insufficient_view | 32.166666667 | .081210 | .098733 | 키 입력 대기 |

촬영 시각은 같은 몸통 카메라 render product에 붙인 공식 simulation-time annotator에서 읽었다. 각 프레임은 도착과 해당 장면 작성 시각보다 새롭고, 사전 위치/yaw 허용 범위 .25m/.15rad를 만족했다. 실제 RGB 640×360 세 장을 열어 작업대 앞 모형, 바닥에 누운 모형, 시야를 막는 가림판을 확인했다. 파일은 `artifacts/vlm/captures/<UUID>/rgb.png`, 관련 메타데이터는 같은 폴더 result.json이며 `cases.json`이 연결한다.

새 장면은 session layer에서 작성하고 finally에서 제거했다. `scene_restored.json`에 임시 human root 제거=true 및 기존 proxy visibility=inherited 복원 확인. 기존 사용자 stage 교체/다른 GUI 종료 없음. 백업 `before_matched_views_*.usda`와 세 장면 USD export를 보존했다.

초기 실패도 보존했다. 첫 authoring은 Quatf/Quatd precision mismatch로 실패하여 double precision orient op로 수정했다. 각 장면마다 이동하려던 첫 시도는 Nav2 목표 수렴이 불안정해 소유 작업을 취소했다(`capture_cases.log`, `capture_cases_retry.log`, `capture_cancel.log`). 이후 동일 도착 위치의 세 후속 영상으로 평가 범위를 명시했다. 초기 `vlm_capture_cases.py` 대신 `vlm_capture_matched_views.py`가 최종 경로다.

## 명령과 검증 수준

이번에 실제 실행한 최종 검증 명령:

```bash
PYTHONPATH=src python3 -B -m unittest discover -s tests -v > artifacts/vlm/unit_tests.log 2>&1
python3 scripts/vlm_run.py --cases artifacts/vlm/cases.json > artifacts/vlm/three_case_dry_run.log
python3 scripts/vlm_verify_artifacts.py
python3 scripts/vlm_run.py --help
```

- 전체 56 tests 통과, expected failure 없음. 기존 코어/보행 명령/Nav2 계약 포함. 새 API wire/schema/비동기 검사는 fixture이며 실제 Google 호출이 아니다.
- syntax/top-level await 검사, PNG 크기·capture freshness·도착 오차·dry-run HTML/JSON 검사 통과. `verification.json` 참조.
- 실제 Isaac 렌더링 및 실제 Nav2→Spot 보행 도착: 위 공통 run에서 확인. 새 VLM 작업은 기존 500Hz/gains/정책 코드를 수정하지 않았다. 이전 독립 보행 회귀 2회는 nav2_report.md의 역사적 결과다.
- 공식 validator 지침에 따라 실제 이미지와 시간 계약을 별도로 검사했다. 이미지 89–100KB는 일반 validator의 큰 파일 크기 heuristic을 충족한다고 주장하지 않으며 공식 전체 validator 통과로 표시하지 않는다.
- 실제 API 통신, 모델 판단 정확도·지연·최종 사건 상태, 온라인 Kit 사건 폐루프: 미검증/미연결.

실제 GUI 캡처는 공식 Python Server client의 `spot` context에 `scripts/vlm_stage_inspect.py`, `vlm_capture_cases.py`, `vlm_cancel_capture.py`, 최종 `vlm_capture_matched_views.py`를 순차 제출했다. 각 stdout은 artifacts/vlm에 있다. 초기 호출별 timeout 인자를 포함한 완전한 shell argv는 파일로 보존하지 못했다. 다음은 **최종 경로의 재현 명령**이며 이전 argv 전체를 재구성한 기록은 아니다. 기존 소유 Spot/Nav2 GUI와 `spot` context가 준비되어 있어야 한다. 이 명령은 Spot reset/이동 및 임시 장면 변경을 수행하므로 다른 사용자 장면에 실행하지 않는다.

```bash
python3 /home/jude/isaac_ws_61/IsaacLab/.venv/lib/python3.12/site-packages/isaacsim/skills/isaac-sim-remote/scripts/isaacsim_send.py --context spot --timeout 180 --execution-timeout 170 --file scripts/vlm_capture_matched_views.py
```

적용 skills: 설치본 `isaac-sim-assets`(로컬 primitive 자산), `isaac-camera`(몸통 RGB), `isaac-sim-remote` 및 Python Server 문서(소유 GUI 연결), `isaac-sim-validator`(검증 수준 분리). 이전 보행/ROS 통합은 robot-navigation/policy-deployment 및 ROS bridge skills 기준을 유지했다. 공식 skills/설치 파일/전역 설정은 변경하지 않았다. implementation_guide.md SHA256은 `09adb11f375e5b03dff4b0f4713e9eff925ba7253c9d6f67bbaf76c42ac66403`로 동일하다.
