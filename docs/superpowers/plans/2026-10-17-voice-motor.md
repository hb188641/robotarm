# Voice Motor Control Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** 로컬 호출어 “로봇” → OpenAI 음성 인식 → LLM JSON → 지정 모터 실행.

**Architecture:** `TITI/voice_motor/`에 오디오 입력, 로컬 호출어, OpenAI 해석,
명령 검증, REST 실행을 나누고 CLI에서 연결한다. 기존 REST 서버와
`TITI/robot_arm_app/클라이언트.py`를 재사용하며 기존 음성 집기 초안은 수정하지 않는다.

**Tech Stack:** Python 3.12, faster-whisper, sounddevice, numpy, openai,
python-dotenv, 기존 requests 클라이언트, pytest.

**Spec:** `docs/superpowers/specs/2026-10-17-voice-motor-design.md`

## Global Constraints

- 호출어는 로컬에서 처리하며 호출어 대기 오디오는 클라우드로 전송하지 않는다.
- 로컬 기본 모델 small / CPU int8, API 기본 모델 gpt-4o-mini-transcribe / gpt-4o-mini.
- 명령 단위는 절대 raw tick 0~4095, 모터 번호 1~6, 모호한 수치는 추정하지 않는다.
- 기본 dry-run, 명시적 --execute와 관절 제한 파일이 있어야 실제 모터 요청 허용.
- OPENAI_API_KEY는 값 출력 없이 프로세스 → --env-file → 루트 .env → 상위 .env에서 선택.
- 마이크, 모델, 네트워크, 모터에 import 부작용이 없어야 한다.
- 모터 쓰기 자동 재시도와 자동 토크 변경은 하지 않는다.
- 다른 작업의 미추적 문서와 student-red-cube-lab 변경을 포함하지 않는다.

## Review Focus

1. true, 3.0, "3" 같은 수치 타입 혼동을 거부한다(Task 1).
2. 느린 로컬 추론 중 쌓인 오디오를 다음 명령으로 실행하지 않는다(Task 3).
3. API 거절·출력 잘림·unknown에서 모터 요청이 없어야 한다(Task 2, 5).
4. 일부 목표만 허용되는 다중 명령도 전체 거부하고 쓰기는 0회다(Task 4).
5. 서버가 목표를 접수했어도 실제 위치 미도달이면 완료로 보고하지 않는다(Task 4).

## Files

- Create `TITI/voice_motor/{__init__,config,commands,intent,audio,wake,executor,main}.py`.
- Create `TITI/voice_motor/requirements.txt`, `limits.example.json`, `README.md`.
- Create `tests/test_voice_motor_{commands,config,intent,audio,executor,main}.py`.
- Modify root `README.md`(진입점 소개), `.gitignore`(비밀 env와 실제 제한 설정).

### Task 1: 명령 계약과 설정

**Interfaces:**
- `commands.py`: frozen `Target(motor: int, position: int)`;
  `Command(action: str, targets: tuple[Target, ...])`;
  `parse_command(data: object) -> Command`; `command_schema() -> dict`.
- `config.py`: `load_api_key(env_file: Path | None = None) -> str`;
  `load_limits(path: Path) -> dict[str, dict[str, int]]`.
  제한 파일은 motor_1~motor_6 각각 `{min, max, max_delta}` 정수 필드.
  `0 <= min < max <= 4095`, `1 <= max_delta <= 4095`를 검증한다.

- [ ] 실패 테스트: move 1~6개, unknown 빈 목록 허용; 중복, bool/float/str 수치,
  범위 초과, extra 필드, unknown의 targets, move 빈 목록은 ValueError.
  key 우선순위·명시 파일 누락·키 없음·설정 누락·잘못된 제한 파일 검증.
- [ ] `.venv/bin/python -m pytest tests/test_voice_motor_commands.py tests/test_voice_motor_config.py -q` → FAIL 확인.
- [ ] 계약 구현. JSON 스키마는 additionalProperties=false, 모든 속성 required.
  env 로드는 기존 프로세스 값을 바꾸지 않고 후보별 값을 읽으며 키 값은 로그 금지.
  example 제한은 설명용이며 실제 측정을 대신하지 않는다고 문서화.
- [ ] 같은 테스트 → PASS.
- [ ] 해당 파일만 stage하고 `feat: add validated voice motor command and configuration` 커밋.

### Task 2: OpenAI 두 모델 연결

**Interfaces:** `IntentClient(client, transcription_model: str, llm_model: str)`;
`transcribe(wav: bytes) -> str`; `from_text(text: str) -> Command`;
`from_audio(wav: bytes) -> tuple[str, Command]`; `IntentError`.

- [ ] 실패 테스트: 가짜 SDK로 audio.transcriptions.create(language="ko") 이후
  responses.create가 호출되는 순서, 지정된 두 모델, strict JSON schema 확인.
  공백 전사는 두 번째 API 생략. API 오류·refusal·incomplete·불량 JSON은 IntentError.
  “3번 모터”처럼 위치 없는 요청은 unknown을 출력하도록 프롬프트 확인.
- [ ] `.venv/bin/python -m pytest tests/test_voice_motor_intent.py -q` → FAIL.
- [ ] 공식 OpenAI 문서의 현재 Python SDK 규격을 확인하고 구현.
  파일은 메모리 WAV tuple로 전달. client는 timeout=20, max_retries=0으로 CLI에서 생성.
  모델 출력은 `parse_command`로 다시 검사. 임의 코드 실행·eval은 사용하지 않는다.
- [ ] 해당 테스트 → PASS.
- [ ] `feat: add two stage OpenAI voice command interpretation` 커밋.

### Task 3: 마이크 구간과 로컬 호출어

**Interfaces:** `AudioSettings(sample_rate=16000, block_ms=30, silence_s=0.8,
start_timeout_s=5.0, max_record_s=10.0, min_speech_s=0.2, rms_threshold=0.015)`;
`capture_utterance(read_frame, settings) -> bytes | None`(PCM float32 mono→WAV);
`Microphone(device, settings)` context manager with `read_frame() -> ndarray`, `flush()`;
`WakeDetector(model, phrase="로봇")`, `detect(samples: ndarray) -> bool`.

- [ ] 실패 테스트: 시작 무음·너무 짧은 발화→None, 종료 무음·최대 녹음 길이→WAV,
  WAV rate/mono/PCM16 확인. 독립 호출어와 문장 내 유사 단어의 구별 확인.
  유한 프레임 소진은 무한 대기하지 않음. bounded queue overflow 시 오래된 입력 제거,
  호출어 판정 후 flush가 다음 녹음 전에 실행되는지 확인.
- [ ] `.venv/bin/python -m pytest tests/test_voice_motor_audio.py -q` → FAIL.
- [ ] sounddevice는 진입 시 로드하고 callback에서 추론하지 않는다.
  입력 큐 크기를 제한하고 오래된 프레임을 버린다. 모델은 main에서 한 번 로드.
  2초 분량의 로컬 입력에서 language=ko, beam_size=1, VAD 사용.
  호출어 판정 후 준비 신호 전에 flush하고 명령 녹음을 시작한다.
- [ ] 해당 테스트 → PASS.
- [ ] `feat: add local Korean wake detection and bounded audio capture` 커밋.

### Task 4: 제한 검증과 REST 모터 실행

**Interfaces:** `Executor(arm, limits: dict, timeout_s=5.0, tolerance=20,
poll_s=0.05)`; `execute(command: Command) -> dict[str, int]`; `ExecutionError`.

- [ ] 실패 테스트: fake arm 현재 위치 2100에서 motor_3=2200 허용 →
  여러개이동 1회, 목표 도달까지 조회. 여러 목표 중 하나라도 제한/변화량 초과면 쓰기 0회.
  state 누락·bool·NaN·범위 초과는 쓰기 0회. unknown 실행 거부.
  write 오류는 재시도 0회, 응답 유실 메시지. 목표 미도달은 timeout 오류.
  Ctrl-C 후 추가 쓰기 없음. 토크 변경 메서드는 호출되면 실패하는 fake로 검증.
- [ ] `.venv/bin/python -m pytest tests/test_voice_motor_executor.py -q` → FAIL.
- [ ] 모든 목표를 현재 위치와 제한으로 먼저 검사하고 단 한 번의 batch write.
  monotonic deadline 내 실제 위치 조회로 완료 판정. 반환은 확인된 위치 dict.
- [ ] 해당 테스트 → PASS.
- [ ] `feat: execute validated voice targets through existing robot client` 커밋.

### Task 5: CLI 연결·문서·통합 검증

**Interfaces:** `main(argv: list[str] | None = None) -> int`;
`handle_command(command: Command, executor: Executor | None) -> dict`.
실행은 `python -m TITI.voice_motor.main`.

- [ ] 실패 테스트: 기본/--dry-run은 모터 클라이언트 생성 및 HTTP 접근 0회.
  --execute --limits 누락은 API 호출 전에 종료 코드 2.
  --text와 --audio-file은 상호 배타, 마이크와 로컬 모델 불필요.
  unknown/해석 실패→실행 0회, 실행 오류→완료 표시 없음.
  import 전체 모듈에서 모델·마이크·HTTP 접근 0회.
  호출어 대기→녹음→API→실행→대기 및 Ctrl-C 자원 해제를 fake로 검증.
- [ ] `.venv/bin/python -m pytest tests/test_voice_motor_main.py -q` → FAIL.
- [ ] CLI 조립: --env-file, --wake-model, --transcription-model, --llm-model,
  --device, --base-url, --limits, --execute/--dry-run, --text/--audio-file,
  --rms-threshold 지원. --help는 선택 의존성 없이 동작.
  .gitignore에 .env/.env.local 및 실제 limits.json 추가.
  독립 requirements에 openai>=2,<3, faster-whisper>=1.1,<2,
  sounddevice>=0.5,<1, python-dotenv>=1,<2, numpy>=1.26, requests>=2.32 지정.
  README에 두 발화 방식, 모델 다운로드, 마이크 권한, CPU 부하·지연,
  제한 측정, dry-run과 execute, 음성 비상 정지 부재를 명시.
- [ ] 해당 테스트 및 전체 `.venv/bin/python -m pytest -q` → PASS.
  `.venv/bin/ruff check --select E9,F63,F7,F82 TITI tests mediapipe_hand.py` → PASS.
  CLI --help와 --text "3번 모터 위치 2200으로 이동" --dry-run 검증.
  키는 이미 승인된 상위 .env에서 읽고 실제 요청 결과는 비밀 없이 기록.
  마이크/실제 모터 시험은 연결·권한·제한 측정 여부에 따라 증거를 분리한다.
- [ ] `feat: expose and document wake word voice motor CLI` 커밋.

## Self-review

설계의 호출어/두 발화/무음/최대 길이/입력 적체는 Task 3·5,
API 모델/키/JSON 계약은 Task 1·2, 제한/도달/불명확한 쓰기는 Task 4,
실행 모드/부작용/검증 증거는 Task 5가 담당한다.
명령 타입과 클라이언트 메서드명은 각 Task의 공개 인터페이스와 일치한다.
