# 5090 PC에서 Spark의 Qwen 사용

Spark는 Ollama/Qwen 추론 서버, 5090 PC는 TRACE/Isaac/ROS 실행 호스트로 분리할 수 있다. 이 문서는 모델 API 연결만 검증하며, 5090의 Isaac/ROS 설치와 전체 통합은 별도다.

## 연결

Spark에서 `bash scripts/start_ollama.sh`로 서버를 시작한다. 이미 127.0.0.1:11434에서 서버가 실행 중이면 중복 실행하지 않는다. 모델은 `qwen3-vl:8b`다.

5090 PC의 PowerShell 또는 터미널에서 아래 명령을 실행하고 창을 유지한다. SPARK_IP를 Spark의 LAN IP로 바꾼다. SSH 계정 인증이 필요하다.

```bash
ssh -N -o ExitOnForwardFailure=yes -o ServerAliveInterval=30 -L 127.0.0.1:11435:127.0.0.1:11434 juhwan@SPARK_IP
```

5090 PC의 다른 터미널에서 확인한다. Windows에서는 `curl.exe`, Linux에서는 `curl`을 사용한다.

```bash
curl http://127.0.0.1:11435/api/tags
```

TRACE의 VLM config에서 endpoint만 아래 값으로 바꾼다. 동일 설정을 사용하는 planner는 `/api/generate`를 자동으로 사용한다.

```json
{
  "provider": "ollama",
  "endpoint": "http://127.0.0.1:11435/api/chat",
  "model": "qwen3-vl:8b",
  "timeout_seconds": 180,
  "safe_closure_from_single_frame": false
}
```

SSH 터널을 사용하는 동안 Spark의 11434를 LAN에 공개할 필요가 없다. 다른 네트워크에서는 별도 VPN/SSH 경로가 필요하며, 이 문서는 인터넷 포트 포워딩을 설정하지 않는다. DHCP 환경에서는 Spark IP가 바뀔 수 있다.

## 검증 범위

2026-10-27: Spark에서 Ollama `/api/tags` 응답, qwen3-vl:8b 모델 존재, 로컬 11434 listener와 SSH 22 listener 확인. 5090 PC에서의 SSH 인증/접속 및 이미지 추론은 아직 직접 검증하지 않았다. `/api/ps`가 빈 배열이면 서버는 살아 있지만 모델은 아직 GPU에 적재되지 않은 상태다. 첫 요청에는 모델 적재 시간이 추가된다.

기존 Spark simulator/desktop 세션은 자동 종료하지 않았다. 저장하지 않은 장면을 보존하기 위해, Spark를 추론 전용으로 운영할 때는 필요한 장면 저장 후 Isaac Sim과 대시보드를 종료한다.
