# TRACE 방법론 구현과 연구 결정 사항

작성: 2026-10-27. 이름: **Task-Relevant Active Context and Evidence**.

## 이번 구현의 범위

첫 버전은 단일 작업 구역·단일 대상·등록된 두 질문 유형으로 제한한다. 일반적인 산업안전 질문을 LLM이 자유롭게 생성하는 완성형 시스템은 아니다.

- `src/haiclaw/context.py`: presence / lying 질문, 근거별 관측 해석과 조건 검사, unresolved / resolved / conflicted, 근거 만료·명시적 철회·충돌, 의존 판단 risk의 재계산, 변경 이력, canonical JSON SHA256 스냅샷.
- `src/haiclaw/harness.py`: planner context에 질문과 부족한 조건 노출, action의 question_id 검사, tool 결과와 질문 연결, 유효 관측으로 context 갱신. context가 visible-lying을 지지해야 기존 사건 위험 판정을 허용한다.
- `src/haiclaw/providers/harness_planner.py`: 등록된 질문 ID를 선택하는 출력 schema와 prompt. LLM이 해소 조건을 새로 작성하거나 승인하지 않는다.
- `scripts/demo_context_resolution.py`: CPU fixture로 해소 → 충돌 → 철회 → 만료 → 재관측·재해소 시연.
- `tests/test_context.py`: 질문 수명주기와 기존 하네스 연결 검증.

`risk=true`는 **현재 관측이 visible lying을 지지한다**는 제한된 명제다. 사고·응급 상황의 진단이나 산업안전 전체 판정이 아니다. standing이나 사람 미검출을 safe로 바꾸지 않는다. 사건 알림 기록과 현재 질문의 유효성을 분리한다.

## 실제로 구현한 규칙

1. 근거는 episode/subject/generation/time/reference를 검사한다. 신선도 경계는 `now < capture_time + max_age`다. 같은 근거 ID를 다시 넣어 유효기간을 늘릴 수 없다.
2. 관측 제한, 추가 관측 필요, 낮은 품질 또는 오류 이유가 있으면 해소 근거로 인정하지 않는다.
3. 명확히 사람을 관측하면 presence=true. 명확한 lying/standing/seated에서만 lying 질문을 판정한다. `not visible`만으로 presence=false가 되지 않는다.
4. 부재 판정은 별도 host의 `complete_coverage=True`가 필요하다. **현재 live adapter에는 이를 입증하는 coverage provider가 없으므로 부재 해소를 활성화하지 않는다.**
5. 유효기간 내 상반된 근거는 conflicted로 보존한다. 최신 프레임 하나로 이전 결론을 조용히 덮지 않는다. 만료·철회 뒤 남은 근거로 재계산한다.
6. presence=true와 lying=true가 둘 다 해소되어야 파생 판단이 해소된다. 하위 질문이 열리거나 충돌하면 상위도 다시 열린다.
7. snapshot은 질문/근거 참조·해석·시각·규칙 버전·이력·철회를 묶는다. 해시는 이 JSON의 동일성을 검증하며 **원본 이미지 바이트의 해시·진실성·진본성을 보증하지 않는다.**
8. 기존 planner의 3필드 출력은 host가 질문에 연결하고 `host_legacy_fallback`으로 기록한다. 새 schema는 question_id를 요구한다. fixture fallback을 모델의 의미 이해로 보고하지 않는다.

## 당신의 창의력과 연구 선택이 필요한 부분

| 결정할 문제 | 현재 임시 선택 | 왜 연구 결정인가 / 실험 방법 |
|---|---|---|
| 어떤 질문이 과제에 충분한가? | 사람이 정한 presence, lying 두 유형 | 산업 공정 상태·노출·보호장치 관계 중 무엇을 최소 질문 집합에 포함할지 정해야 한다. 고정 질문/LLM template 선택/자유 제안 후 검증 비교. 질문 누락률과 불필요 관측률 측정. |
| 무엇을 논문 기여로 삼을까? | 조건·재개방·행동 연결을 구현 단위로 분리 | 단순한 graph+LLM 조합을 신규성으로 주장하기 어렵다. '기한 아래 유효한 근거를 유지하며 질문을 해소하는 정책' 등 검증 가능한 주장을 선택해야 한다. |
| 변화와 모순을 어떻게 구별할까? | 만료 전 반대 관측은 모두 충돌 | 사람이 실제로 일어난 경우도 충돌로 남는다. 변화 사건을 인정하는 시간 규칙, 신뢰도, 다중 카메라 모순을 분리할 설계가 필요하다. |
| 어떤 관측을 먼저 할까? | LLM에 질문·도구·이력을 제공 | 예상 해소 가능성/소요 시간/실패 확률/위험 비용을 어떻게 결합할지 선택해야 한다. 현재 시간 추정치는 None이며 임의 수치를 넣지 않았다. 고정 순서·비용 heuristic·모델 선택을 비교. |
| 위험 알림과 질문의 생명주기 | 알림은 보존, 질문은 재개방 가능 | 이미 신고한 사건의 현재 맥락을 누가 얼마나 오래 관리할지 정해야 한다. 재개방은 경보 취소가 아니며 재알림 조건도 별도로 필요하다. |
| 해소의 정답은 무엇인가? | visible lying이라는 좁은 명제 | '안전', '사고', '관측으로 확인 가능'의 operational definition이 필요하다. 정답은 평가기에만 제공하고 모델 입력과 분리해야 한다. |

우선 당신이 정하면 좋은 두 가지: **논문의 주된 장면/위험 유형**, 그리고 **주요 실패를 오래된 판단 유지와 불필요 관측 중 어디에 둘 것인가**. 현재 개발을 막는 필수 응답은 아니며 코드에는 제한된 기본값을 사용했다.

## 문헌에서 먼저 확인할 부분

아래는 2026-10-27에 원 논문 초록/서지·공개 원문을 확인한 출발점이다. 체계적인 survey나 최신 방법 전체 비교를 완료했다는 뜻은 아니다. 보편적인 '모범답안'이 있다고 단정하지 않는다.

- **의존성·철회·모순 처리:** de Kleer, [An assumption-based TMS (1986)](https://www.sciencedirect.com/science/article/pii/0004370286900809). 가정과 일관성 관리에 관한 기존 체계를 먼저 검토해야 한다. 현재 코드는 ATMS 구현이 아니라 고정된 작은 의존 구조의 재평가다. '재개방 자체'를 새 기여로 주장하지 않는다.
- **시간에 따른 행동과 맥락 변화:** Morris & Nado, [Representing Actions with an Assumption-Based Truth Maintenance System (1986)](https://research.aimagazine.org/Library/AAAI/1986/aaai86-003.php). 행동 효과와 상태 변화를 truth maintenance에 어떻게 연결하는지 검토할 출발점. 현재의 보수적 충돌 처리가 실제 상태 전이를 과도하게 막는지 비교해야 한다.
- **능동 관측:** Bajcsy, [Active Perception (1988)](https://people.eecs.berkeley.edu/~yang/courses/cs294-6/papers/Bajcsy.active%20Perception.pdf). 지각을 위한 모델링·제어라는 관점이 이미 존재한다. TRACE에서는 질문 조건과 제한 시간에 연결한 관측 선택이 무엇을 더하는지 정량화해야 한다.
- **언어와 실행 가능성 결합:** Ahn et al., [Do As I Can, Not As I Say (2022)](https://arxiv.org/abs/2204.01691). 언어 기반 선택과 로봇 affordance를 결합하는 선행연구. 현재 도구 catalog는 학습된 성공 확률이나 affordance 모델이 아니며, 예상 정보 획득까지 구현됐다고 표현하면 안 된다.

추가 조사 항목: temporal truth maintenance / belief revision, runtime monitoring의 3값·4값 의미론, open-world 하의 부재 판단, active perception/POMDP/value of information, evidence provenance, embodied question answering, safety monitoring에서의 ground truth와 지연 지표. 각 분야에서 **문제 가정·규칙·baseline·평가 지표**를 추출한 뒤 TRACE에 맞는 부분만 도입한다. TRACE 명칭 중복 조사도 아직 별도 과제다.

## 아직 구현하거나 검증하지 않은 부분

- 자유로운 LLM 질문 분해·생성, 일반 DAG 구성, 공정/설비/보호구 질문. 현재 질문은 고정 template이고 risk 의존 관계도 고정이다.
- 공간 coverage, cross-camera identity, sensor calibration의 실제 증명. 현재 scope와 person-1은 단일 대상 장면의 **host 가정**이다.
- 질문별 상이한 TTL, 신뢰도 보정, 실제 변화와 센서 모순의 구별, 지속 모니터링 서비스.
- 기존 하네스는 사건이 종료되면 멈춘다. 그 이후에도 context 엔진은 별도 호출로 재개방 가능하지만, **종료 뒤 live 영상을 계속 받아 자동 재검증하는 서비스는 아직 없다.**
- 원본 이미지의 content digest, snapshot 영속 로드·migration, 대규모 history 압축. 현재 스냅샷은 하네스 결과 JSON에 저장된다.
- 도구별 예상 시간/관측 가능성/접근 성공률의 실측 모델. 카탈로그에는 unknown을 명시한다.
- 이번 schema의 실제 Qwen 재실행 및 Isaac 통합 재검증, UI의 질문 graph 표시. 이전 live 결과를 이번 버전 성능으로 재사용하지 않는다.
- 네 가지 제거 실험을 동일 조건에서 자동 수행하는 평가 runner. 기존 baseline은 남아 있으나 이번 graph의 성능 효과는 미측정이다.

## 실행과 검증

```bash
PYTHONPATH=src python3 -B -m unittest discover -s tests -v
python3 scripts/demo_context_resolution.py > /tmp/trace-context-demo.json
```

97개 CPU 테스트 통과(기존 86 + 신규 11). 데모에서 unresolved → resolved → conflicted → resolved → unresolved → resolved 확인. 해소·충돌·만료·철회·재해소, 해시/복사, stale/foreign 입력, 하네스 action/result 연결 검증이다. 실제 모델 추론·실제 로봇 이동·산업안전 성능 검증이 아니다.
