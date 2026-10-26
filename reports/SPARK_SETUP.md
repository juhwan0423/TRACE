# TRACE — DGX Spark 실행 환경

설치 위치: `/home/juhwan/문서/ChatGPT/ROSCLAW/TRACE`

각 터미널에서:

```bash
cd /home/juhwan/문서/ChatGPT/ROSCLAW/TRACE
source scripts/env_spark.sh
```

실행 환경은 `.venv`, Ollama 실행 파일과 모델은 `artifacts/ollama`에 둡니다.
`ISAAC_LAB_DIR`는 기존 실행기의 `.venv` 위치를 지정하는 호환 변수입니다. Isaac Lab 설치를 뜻하지 않습니다.

```bash
# 로컬 모델 서버 (127.0.0.1만 사용)
systemctl --user start trace-ollama.service
# 상태 확인
systemctl --user status trace-ollama.service
# 별도 터미널: 설치된 모델 확인
ollama list
ollama run qwen3-vl:8b
# Isaac Sim + 기존 Spot 데모 GUI
python scripts/spot_gui.py --scene flat
# Nav2: 별도 터미널
bash scripts/start_nav2.sh
# 코어 회귀 테스트
python -B -m unittest discover -s tests -v
```

Isaac Sim 첫 실행 시 NVIDIA EULA 동의가 필요할 수 있습니다. 설치 확인과 실제 시뮬레이션 검증은 `WORKLOG.md`에 구분해서 기록합니다.

기존 `configs/vlm.json`과 `scripts/vlm_run.py`는 Gemini 전용입니다. 로컬 Qwen 설치만으로 기존 영상 판단 루프가 연결되지는 않습니다. 저장된 과거 실행 결과는 이전 PC에서 만든 것이며 이 Spark에서의 검증 결과가 아닙니다.

## 저장 영상 로컬 판단

```bash
python scripts/vlm_local.py artifacts/occlusion/after_move_MovingCamera.png
```

`configs/vlm_local.json`의 Qwen3-VL 8B를 사용하며 응답은 `artifacts/vlm_local/`에 저장합니다. 외부 API 없이 숫자 loopback HTTP만 허용하는 기존 전송 계층과 엄격한 관측 schema를 재사용합니다. 이 명령은 저장 영상 평가이며 실시간 로봇 사건 루프를 실행하지 않습니다.

Ollama는 로그인 시 시작하는 사용자 서비스 `trace-ollama.service`로 설치했습니다. 수동 실행 시에는 서비스 중복 실행을 피하세요. 문맥 8192, 동시 요청 1로 Isaac Sim과 메모리를 공유합니다. 최초 유효 영상 추론은 `artifacts/vlm_local/spark-schema-verified.json`에 기록했습니다.

## 검증 결과

- Isaac Sim 6.2.0.0 설치, 공식 호환성 PASSED, 전용 서버 Health OK. 검증용 서버는 종료했습니다.
- PyTorch 2.11.0+cu130: GB10 GPU 연산 성공.
- Qwen3-VL 8B: GPU 100%, 문맥 8192, 약 6.6GB; 저장 인물 영상의 JSON schema 검증 통과.
- Nav2 ARM64 이미지 빌드 및 패키지 로딩 확인, 코어 테스트 56개 통과.
- 알려진 경고: NVIDIA cuSPARSELt 배포 wheel 내부의 `sbsa` 태그 때문에 pip check가 경고합니다. 실제 라이브러리 로딩과 GPU 연산은 통과했습니다. Isaac의 선택적 DLSS-RR 기능은 비활성화됩니다. 상세 로그는 WORKLOG.md에 있습니다.
- 새 장면 렌더링, 실제 Spot 보행, ROS transport, 온라인 사건 폐루프는 이 설치 작업에서 검증하지 않았습니다.

후속 작업에서 실제 폐루프 1회를 실행했습니다. 최신 상태는 [폐루프 기록](CLOSED_LOOP.md)을 참조하세요. 위 내용은 설치 시점의 검증 범위입니다.
