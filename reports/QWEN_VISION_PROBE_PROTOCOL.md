# Qwen3-VL 응답 신뢰성 점검: 별도 개발 프로토콜

등록 당시 상태: 구현·모의 테스트 완료, 추론 미실행. **2026-11-07에 10회 비교 파일럿 종료 후 등록된 8회 호출을 모두 완료했다.** 비교 파일럿의 소스, 설정, 모델, 런타임은 변경하지 않았다. 이 점검은 다음 코호트에서 사용할 수 있는 요청 방식의 개발 검증이며 기존 결과를 교체하지 않는다.

## 실행 결과

| 측정 | 기존 chat | raw closed-think 후보 |
|---|---:|---:|
| 완료된 strict JSON | 4/4 | 4/4 |
| 빈 최종 응답 / 길이 종료 | 0 / 0 | 0 / 0 |
| wall 지연 중앙값 | 46.228초 | 2.956초 |
| wall 지연 범위 | 22.384–58.998초 | 2.138–4.821초 |

속도 차이는 이 네 캘리브레이션 이미지의 요청 방식 비교 결과다. 독립적인 인식 정확도나 정책 성능 개선을 뜻하지 않는다. 두 방식 모두 명확한 standing/lying 이미지의 자세 라벨은 맞혔지만, lying 이미지에서 후보는 추가 관측 필요와 제한을 표시했다. 기존 방식은 그렇지 않아, 현재 `incident_decision`의 clear-lying 판정 자격이 달라진다. 따라서 동일한 종료 성능을 가정해 자동 교체하지 않았다.

원자료: [완료 요약](../artifacts/qwen_vision_probe/20261107_calibration_01/summary.json), [사후 모델 보조 시각 검토](../artifacts/qwen_vision_probe/20261107_calibration_01/visual_review.md). 네 이미지 검토는 독립 인간 주석이 아니다. 다음 절들은 변경하지 않은 사전 등록 설계다.

## 근거와 변경 범위

현재 어댑터는 `qwen3-vl:8b`에 `/api/chat`, `think=true`, `num_predict=4096`, `num_ctx=8192`, 온도 0, 타임아웃 180초를 사용한다. 기존 첫 시험에서는 한 응답이 출력 토큰 4096개를 소진하면서 최종 내용이 비어 있었다. 이는 개선 후보를 조사할 이유이며, 아직 일반적 실패율 추정은 아니다.

읽기 전용 `/api/version`과 `/api/show` 확인 결과는 Ollama **0.40.11**, Qwen3-VL 8.2B Q4_K_M, `llamacpp` 실행기, vision·thinking 지원, boolean thinking 선택 지원이다. 템플릿 문자열은 `{{ .Prompt }}`이므로 그 문자열만으로 멀티모달 요청의 실제 템플릿을 추정하지 않았다.

[공식 generate API](https://docs.ollama.com/api/generate)는 Base64 `images`, JSON schema `format`, `raw`를 지원한다. [공식 thinking 설명](https://docs.ollama.com/capabilities/thinking)은 모델별 허용 값을 `/api/show`로 확인하도록 설명한다. 설치 버전의 [서버 구현](https://github.com/ollama/ollama/blob/v0.40.11/server/routes.go)은 raw 요청에 이미지를 전달하고, raw 출력에서는 첫 토큰부터 형식 제약을 적용한다. 같은 버전의 [llama-server 연결 구현](https://github.com/ollama/ollama/blob/v0.40.11/llm/llama_server.go#L1741-L1758)은 **`[img-0]` 표식**을 실제 이미지로 연결한다. 따라서 raw 프롬프트에는 이 표식을 사용한다. [Qwen3-VL renderer](https://github.com/ollama/ollama/blob/v0.40.11/model/renderers/qwen3vl.go)의 메시지 구분 형식과 닫힌 think 구간을 참고했다. 이 소스 검토는 실제 시각적 이해나 지연 개선을 입증하지 않는다.

## 고정 비교

| 항목 | 기존 방식 | 실험 후보 |
|---|---|---|
| API | `/api/chat` | `/api/generate`, `raw=true` |
| 사고 설정 | `think=true` | `think=false`, 닫힌 `<think>` 접두사 |
| 이미지 | 같은 PNG 한 장 | 같은 PNG 한 장, `[img-0]` 연결 |
| 모델·지시문·스키마 | 동일 | 동일 |
| 출력/문맥 한도 | 4096 / 8192 | 4096 / 8192 |
| 온도/요청 제한 | 0 / 180초 | 0 / 180초 |

API·템플릿·사고 접두사를 함께 바꾸는 **실험적 요청 방식 비교**다. 각각의 요소가 결과를 바꾼 정도를 분리하는 실험은 아니다. 코드가 현재 어댑터에 자동 적용되는 경로는 없다.

캘리브레이션 이미지는 기존 readiness 폴더의 다음 4개 RGB `body.png`로 고정한다. 분류명·경로·마스크·시뮬레이터 정답은 모델 요청에 넣지 않는다. 입력 메타데이터는 불투명한 `calibration-00` 등 ID와 고정 캘리브레이션 시각 0뿐이다.

1. `entrance_west_adjusted_standing/body.png`
2. `entrance_west_adjusted_lying_reversed/body.png`
3. `west_west_standing/body.png`
4. `door_north2_lying/body.png`

4장 × 2방식 = **최대 8회**, 이미지별 AB/BA 순서를 번갈아 배치한다. 자동 재시도·재개·워밍업 호출은 없다. 네트워크/시간 초과는 전체 점검을 중단한다. 각 요청은 소켓 시간 제한과 별도의 Linux wall-clock 180초 제한을 사용한다. 서버 작업이 취소되었다고 가정하지 않는다. 진행 중인 비교 runner가 보이면 실행을 거부한다. 다른 추론이 없다는 확인은 실행자의 책임이므로 `--exclusive-server`를 명시한다.

## 기록과 해석

- 등록: 이미지·요청·코드·기존 설정 SHA-256, 모델 digest, 버전/템플릿/모델 정보, 순서·호출 한도.
- 호출별: 전체 wall 지연, 서버 duration, 토큰 수, `done_reason`, 비어 있는 내용 여부, JSON 문법 및 기존 strict schema 통과 여부, 검증된 관측 내용.
- 사고 텍스트는 저장·출력하지 않는다. 길이와 원 응답 해시만 기록한다. 잘못된 비-JSON 본문도 그대로 저장하지 않는다.
- 이미지별 설명을 사람이 원본 RGB와 대조해야 한다. 유효 JSON은 올바른 인식 또는 실제 이미지 사용의 증거가 아니다. 이 작은 점검에서는 정확도나 안전 개선 수치를 만들지 않는다.
- 반복 입력·캐시·로드·발열 영향이 남는다. 캘리브레이션 4장은 독립적인 정책 평가 사례가 아니다.
- 실제 simulator clock이 없으므로 wall 지연을 기존 **45초 sim-time 증거 TTL**과 동일시하지 않는다.
- 후보가 정상 작동해도 다음 코호트에 별도로 등록하고, 모든 비교 정책에 같은 VLM을 적용해야 한다. 현재 파일럿을 중간에 변경하거나 결과를 섞지 않는다.

## 실행

작업 위치: `/home/jude/Documents/ChatGPT/ROSCLAW/TRACE`.

아래 등록은 메타데이터 조회만 하며 추론하지 않는다. 출력 디렉터리가 이미 존재하면 덮어쓰지 않는다.

```bash
PYTHONPATH=src .venv/bin/python scripts/probe_qwen_vision.py freeze \
  --output artifacts/qwen_vision_probe/20261107_calibration_01
PYTHONPATH=src .venv/bin/python scripts/probe_qwen_vision.py verify \
  --output artifacts/qwen_vision_probe/20261107_calibration_01
```

**파일럿 종료 및 추론 자원 인계 후에만** 다음 명령을 실행한다. 이 등록 디렉터리의 실행은 이미 완료됐으므로 재실행하지 않는다. 새로운 점검에는 새 등록 디렉터리가 필요하다.

```bash
PYTHONPATH=src .venv/bin/python scripts/probe_qwen_vision.py run \
  --output artifacts/qwen_vision_probe/20261107_calibration_01 --exclusive-server
```

모의 검증 명령:

```bash
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -p test_qwen_vision_probe.py
```

11개 모의 테스트가 통과했다. 기존 어댑터와 baseline 요청의 정확한 일치, raw 이미지 표식/동일 제어값, 빈 응답·잘못된 스키마·근거 ID 오류, 실행 중인 비교 runner 차단, 무추론 등록/해시 검사, 시간 초과 후 무재시도, 정확히 8회인 모의 완료를 포함한다. 테스트는 모델·GPU·시뮬레이터를 호출하지 않았다.
