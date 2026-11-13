# Real2Sim: 관측 소실 후 Spot 확인

기존 고정 카메라에서 확인한 작업자가 사각지대에 들어간 뒤, 시간과 프레임 근거를 보존하고 Spot의 추가 관측으로 현재 자세를 확인하는 개발 시나리오다. 시스템 패키지, Isaac 버전, Qwen 모델, 원본 장면 파일은 변경하지 않는다.

## 구성

- `scripts/real2sim_worker_scene.py`: 기존 사람의 스킨 포즈와 충돌체를 함께 배치한다. 원본 애니메이션은 유지하고 별도의 익명 USD 레이어로 덮어쓴다. `restore()`는 이 레이어만 제거하고 원래 충돌체 움직임을 복구한다.
- `scripts/real2sim_worker.py`: 배치·복구·카메라 캡처 CLI. `--measure`의 인물 픽셀 수는 평가 전용이며 에이전트에 전달하지 않는다.
- `scripts/run_real2sim_loss_inspection.py`: 실제 고정 카메라 영상을 Qwen으로 해석한다. 같은 스트림에서 먼저 `yes`, 이후 `no`가 확인되고 관측 시각 차이가 grace 이상일 때 기존 harness를 실행한다. 불확실·센서 실패는 사람 소실로 위장하지 않는다.
- `configs/harness_occlusion_real2sim.json`: 기존 기본 설정과 분리한 실험 설정. 기존 A* 경로의 `west` 지점에서 남쪽을 보는 관측 후보를 추가한다. 위치 설명에는 작업자 위치나 정답을 넣지 않는다.

이전 프레임 ID·관측 시각·해석은 과거 기록으로 전달한다. 현재 존재·자세 판정에는 검사 시작 이후 확보한 새 근거가 필요하다. 사람이 안 보인다는 이유만으로 안전 판정을 만들지 않는다.

## 직접 재현

아래 한 명령은 입구 이동, 초기 가시 관측 확인, 사각지대 배치, 소실 감시와 검사를 순서대로 실행한다. 원래 장면을 초기화하지 않는다. 작업자 이동은 실제 보행이 아닌 평가 시나리오의 배치 변경이다.

```bash
cd /home/jude/Documents/ChatGPT/ROSCLAW/TRACE
PYTHONPATH=src .venv/bin/python scripts/demo_real2sim_occlusion.py
```

데모 전체가 실행 잠금을 보유하고 검사 자식 프로세스에 같은 잠금 FD를 상속한다. 평가 기록은 `artifacts/occlusion_demo/<id>/evaluator.json`에 저장한다. `--condition standing`은 대조 조건용이며 별도 실검증이 필요하다.

다음은 각 단계를 직접 실행하는 방법이다.

TRACE 모니터와 Spark 터널이 켜져 있고, 다른 검사나 수동 이동이 진행 중이지 않은 상태에서 실행한다. Spot은 입구에서 시작한다. 기존 이동이 있다면 사용자가 먼저 종료한다.

```bash
cd /home/jude/Documents/ChatGPT/ROSCLAW/TRACE

# 고정 카메라에 보이는 초기 작업자. XYZ는 바운딩 박스 중심 X/Y와 최저 Z.
python3 scripts/real2sim_worker.py apply \
  --position -1.05 -0.45 0.03 --rotation 0 0 0

# 실제 카메라 관측 소실 감시 후 검사.
PYTHONPATH=src .venv/bin/python scripts/run_real2sim_loss_inspection.py \
  --config configs/harness_occlusion_real2sim.json
```

출력에 `monitor_observation`의 `visibility_status: visible`이 나온 뒤 다른 터미널에서:

```bash
cd /home/jude/Documents/ChatGPT/ROSCLAW/TRACE
python3 scripts/real2sim_worker.py apply \
  --position -5.5 -0.3 0.03 --rotation 0 90 90
```

작업자 배치 변경은 Spot 이동 중 거부된다. 검사 중 수동 이동을 보내면 실험에 개입하게 된다. CLI 검사에서 Ctrl+C는 기존 harness의 요청 단위 중단을 이용한다.

```bash
# 작업자 원상복구. Spot이 멈춘 상태에서 실행.
python3 scripts/real2sim_worker.py restore

# 세 카메라 원본 PNG, 시각, 평가용 인물 픽셀 수 저장.
python3 scripts/real2sim_worker.py capture --measure \
  --output artifacts/worker_scenario/manual-capture
```

복구는 원래 사람 애니메이션을 현재 타임라인 시각에서 다시 재생한다. Spot 위치나 전체 시뮬레이션 시각은 초기화하지 않는다. 장면을 새로 열면 익명 레이어는 사라지므로, 다시 배치 명령을 실행해야 한다.

## 결과와 해석

각 검사는 `artifacts/loss_inspection/<episode>/`에 원본 프레임, 전체 모델 응답, 시각이 있는 이벤트, 설정과 소스 사본, 최종 결과를 저장한다. 최신 경로는 `artifacts/live_real2sim/latest_loss_inspection.json`에서 확인한다. 작업자의 숨겨진 실제 상태·위치는 `artifacts/worker_scenario/`의 평가 자료에만 둔다.

현재 인식기는 **Qwen**이다. YOLO 기준선을 실행했다거나 기존 고정 순찰보다 빨라졌다고 주장하지 않는다. 비교 실험에는 같은 사건 시각·센서·모델·시작 위치와 순찰 주기가 필요하다.

관측 소실 조건은 최소 구현인 **마지막 실제 가시 관측 이후 설정 시간 경과 + 실제 비가시 관측**이다. 지속적으로 모든 프레임에서 사라졌다는 증명이 아니며, 모델 지연 동안 관측 공백이 생길 수 있다. 다중 인물 추적이나 cross-camera re-ID는 구현하지 않았다.

작업자는 기존 스킨 애니메이션의 한 프레임을 정지하고 회전·이동한 **합성 정적 포즈**다. 이동 경로·물리 낙상·부상 진단을 검증하지 않는다. `lying`은 영상상의 누운 자세 확인이다. 원래 인물의 충돌체는 새 포즈와 함께 배치하며, 원래 문 애니메이션은 계속 재생된다.

첫 후보 `(-4.3,-0.9)`는 고정 카메라에 103개 인물 픽셀이 남고 몸체 영상에서 설비가 많이 가려 제외했다. 최종 후보 `(-5.5,-0.3)`는 고정·전체 보기에서 인물 픽셀 0, 서쪽 몸체 영상에서 수천 픽셀을 확인했다. 평가용 세그멘테이션은 배치 검증에만 사용했다.

## 2026-11-03 첫 실실행 결과

Episode `22b5f9d2-408b-41ec-ad06-ebeea4caeb1a`:

- 실제 고정 카메라 가시 관측 → 비가시 관측 → 자동 검사 → `inspect(west)` 실제 보행 → 새 몸체 영상 → `danger_confirmed`, 로컬 모의 경보.
- 행동 5회: 입구 몸체 관측 2회, 서쪽 이동 1회, 서쪽 몸체 관측 2회.
- 검사 harness 시작 후 실제 시간 273.33초. 사각지대 전환부터의 전체 지연과 구분해야 한다.
- 사각지대 첫 캡처 시뮬레이션 시각 1262.404, 소실 감지 1306.554, 서쪽 도착 1387.370, 최종 확인 1436.504. 시뮬레이션 시각은 wall time이 아니다.
- 렌더러 인물 픽셀: 초기 fixed 6136 → 사각지대 fixed 0 / 입구 body 0 → 서쪽 body 6860. 카메라 설정과 환경 설비는 변경하지 않았다.
- 오류도 보존했다: 빈 고정 영상의 형상을 사람으로 오인한 응답 1회, 입구 몸체 영상에서 서 있는 사람으로 오인한 응답 1회. 후자는 가림·흐림 한계 때문에 현재 상태 확정에 사용되지 않았다.
- 서쪽 첫 `lying` 응답도 낮은 각도라는 제한을 포함해 채택되지 않았고, 다음 새 프레임의 제한 없는 `lying` 응답에서 종료했다. 이 변동은 인식기 신뢰성과 제한 표현의 일관성에 남은 문제다. 성공 프레임을 정답으로 주입하거나 판단 가드를 완화하지 않았다.

검증 범위: 실제 Isaac Sim 6.2 렌더링, 실제 Spot 보행, Spark Qwen 이미지 추론과 선택, 기존 host 판정. 로컬 모의 경보이며 실물 로봇·신고 서비스는 연결하지 않는다.

한 명령 재현 `PYTHONPATH=src .venv/bin/python -u scripts/demo_real2sim_occlusion.py`도 실실행했다. Episode `9578103e-e5ff-4516-943f-a7af2f27418f`, evaluator `artifacts/occlusion_demo/dc2bf2d2-2046-4c28-8c0b-e692083d69f8/evaluator.json`에서 `completed=true`, 자식 exit 0, `danger_confirmed`를 확인했다. 행동 6회, 검사 harness wall time 334.28초. 작업자 보임/안 보임 전환과 서쪽 이동이 자동으로 연결됐다. 첫 실행과 같은 이유로 서쪽 영상 두 번을 사용했다. 두 개발 실행의 성공은 정확도나 속도 개선을 입증하는 통계가 아니다.
