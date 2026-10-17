# “로봇” 호출어로 모터 제어

호출어는 **로컬 faster-whisper**가 감지합니다. 준비 신호 이후의 명령 음성만
OpenAI로 보내며, 1번 모델이 전사하고 2번 모델이 모터 명령 JSON으로 변환합니다.
기본 실행은 JSON만 출력하는 **dry-run**입니다.

```text
“로봇” → 준비 신호 → “3번 모터 위치 2200으로 이동”
→ gpt-4o-mini-transcribe → gpt-4o-mini
→ {"action":"move","targets":[{"motor":3,"position":2200}]}
→ 검증 → {"motor_3":2200} → 기존 REST 서버
```

호출어와 명령은 **두 번 나누어** 말합니다. 화면에 `준비됐습니다`가 나온 뒤 명령을 말하세요.
준비 시 터미널 벨도 출력하지만 소리는 터미널 설정에 따라 다릅니다.
“로봇 3번 모터…”처럼 한 번에 말하는 방식은 지원하지 않습니다.

## 설치 및 키

저장소 루트에서 Python 3.12 가상환경을 활성화한 뒤 설치합니다.

```bash
source .venv/bin/activate
pip install -r TITI/voice_motor/requirements.txt
```

키는 프로세스의 `OPENAI_API_KEY`, `--env-file`, 저장소 루트 `.env`, 상위 폴더 `.env`
순으로 읽습니다. `--env-file`을 지정하면 기본 env 파일로 돌아가지 않습니다.
키는 출력하거나 다른 파일로 복사하지 않습니다. `.env.local`은 `--env-file`로 지정합니다.

현재 사용자 설정 파일은 `/Users/hwangboyun/robot/.env`입니다. 다른 체크아웃에서 실행할 때는
`--env-file /Users/hwangboyun/robot/.env`를 지정할 수 있습니다.

## 모터 없이 먼저 확인

```bash
# 2번 LLM만 호출: 텍스트 → JSON (마이크와 로컬 모델 불필요)
python -m TITI.voice_motor.main --text '3번 모터 위치 2200으로 이동' --dry-run

# 1번 음성 인식 → 2번 LLM (0.2~30초, mono PCM16 WAV)
python -m TITI.voice_motor.main --audio-file command.wav --dry-run

# 마이크 장치 목록 (API 키 불필요)
python -m TITI.voice_motor.main --list-devices

# 실제 호출어 대기와 음성 해석. 모터에는 접근하지 않음
python -m TITI.voice_motor.main --dry-run
```

예상 결과:

```json
{"status":"dry_run","command":{"action":"move","targets":[{"motor":3,"position":2200}]},"targets":{"motor_3":2200}}
```

“1번 모터 위치 2100, 3번 모터 위치 2200으로 이동” 같은 동시 이동도 지원합니다.
모터 번호는 1~6, 목표는 정수 raw tick 0~4095입니다. 각도·상대 이동은 지원하지 않습니다.
“3번 모터”처럼 위치가 없거나 모호한 요청은 `unknown`으로 출력하고 실행하지 않습니다.

## 실제 모터 실행

1. 기존 `TITI/robot_arm_app/app.py`의 시리얼 포트를 확인하고 REST 서버를 실행합니다.
   **기존 서버는 시작할 때 토크를 켭니다.** 음성 CLI 자체는 토크를 변경하지 않습니다.
2. `limits.example.json`을 `TITI/voice_motor/limits.json`으로 복사합니다.
3. 각 모터의 `min`, `max`, `max_delta`를 실제 기구에서 확인한 정수로 채웁니다.
   템플릿의 `null`은 실측 전 실행을 막기 위한 값이므로 그대로는 실행되지 않습니다.
   `min/max`는 기계적으로 허용하는 위치 범위, `max_delta`는 명령당 최대 위치 변화입니다.
   예를 들어 현재 위치 2100, max_delta=100이면 2200까지 허용하고 2300은 거부합니다.
   raw tick 전체 범위가 해당 관절의 안전 범위를 의미하지 않습니다.
4. 실행합니다.

```bash
# 별도 터미널
python TITI/robot_arm_app/app.py

# 호출어 → 녹음 → API 2회 → 실제 모터 이동
python -m TITI.voice_motor.main --execute --limits TITI/voice_motor/limits.json
```

모든 목표를 사전 검증한 뒤 batch 요청을 한 번 보냅니다. 일부만 허용되는 명령도 전체 거부합니다.
실제 위치가 목표의 20 tick 이내에 들어와야 `completed`를 표시합니다(기본 도달 제한 5초).
실행 통신 오류나 도달 실패 시 CLI를 종료하며, 모터 쓰기를 자동 재시도하지 않습니다.

`Ctrl-C`는 프로그램을 종료하지만 이미 전송한 모터 위치 명령을 취소하지 않습니다.
음성 비상 정지 기능은 없습니다. 종료 시 토크를 임의로 해제하지 않습니다.
다른 제어 프로그램이 같은 모터를 동시에 움직이지 않는 상태에서 사용하세요.

## 설정

```bash
python -m TITI.voice_motor.main --help
python -m TITI.voice_motor.main --device 0 --rms-threshold 0.01 --dry-run
python -m TITI.voice_motor.main --wake-model tiny --dry-run
python -m TITI.voice_motor.main \
  --transcription-model gpt-4o-mini-transcribe \
  --llm-model gpt-4o-mini --dry-run
```

로컬 기본값은 다국어 `small`, CPU `int8`입니다. 최초 실행 때 모델을 내려받습니다.
다운로드 이후에는 로컬 추론이며 `--wake-model`에 캐시된 로컬 모델 경로도 지정할 수 있습니다.
영어 전용 `.en` 모델은 한국어 호출어용으로 사용하지 마세요.
CPU 성능에 따라 호출어 판정이 늦어질 수 있습니다. 호출어는 2초 입력 창과 0.5초 겹침으로
처리하며, 모델 추론 중 발생하는 음성은 일부 놓칠 수 있습니다. “호출어 대기” 상태에서 다시 말하세요.
전용 키워드 모델보다 계산량이 크며 실제 사용자 음성의 인식률은 환경에서 확인해야 합니다.

macOS의 시스템 설정 → 개인정보 보호 및 보안 → 마이크에서 실행 앱의 권한을 허용하세요.
권한이 없거나 16 kHz 입력을 열지 못하면 오류를 출력합니다.

무음 0.8초 후 명령 녹음을 종료하고, 발화 시작 대기는 최대 5초, 녹음은 최대 10초입니다.
`--silence-seconds`, `--max-record-seconds`, `--rms-threshold`로 조절할 수 있습니다.
말이 없거나 0.2초보다 짧거나, 종료 무음 없이 최대 녹음 길이에 도달하면 전체 녹음을 취소하고 API를 호출하지 않습니다. 소음이 크면 RMS 임계값을 올리세요.
녹음 중 입력 손실을 감지하면 명령을 취소합니다. 호출어 추론·API 처리 중 쌓인 입력은 버립니다.

두 API 모델은 각각 설정할 수 있지만 음성 인식/Responses의 strict JSON schema를 지원하고
현재 API 프로젝트에서 접근할 수 있는 모델이어야 합니다.

## 검증

```bash
python -m pytest tests/test_voice_motor_*.py -q
```

단위 테스트는 실제 마이크나 모터를 움직이지 않습니다. 실제 API 요청, 합성 WAV 전사,
로컬 모델 호출어 시험, 실제 사용자 마이크 발화, 실제 모터 이동은 서로 별도의 검증입니다.

사용한 API 형식: [음성 전사](https://developers.openai.com/api/docs/guides/speech-to-text),
[구조화 출력](https://developers.openai.com/api/docs/guides/structured-outputs).
로컬 엔진: [faster-whisper](https://github.com/SYSTRAN/faster-whisper).

모델 다운로드가 멈추는 환경에서는 `HF_HUB_DISABLE_XET=1 python -m TITI.voice_motor.main --dry-run`으로 표준 HTTPS 전송을 사용할 수 있습니다.
