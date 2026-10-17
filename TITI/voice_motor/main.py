"""CLI entrypoint. Default operation interprets commands without motor access."""

import argparse
import importlib
import json
from pathlib import Path
import sys

from .audio import AudioError, AudioSettings, Microphone, capture_utterance
from .commands import Command, parse_command
from .config import load_api_key, load_limits
from .executor import ExecutionError, Executor
from .intent import IntentClient, IntentError


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="로컬 호출어 → OpenAI 음성 인식 → JSON → 모터 제어 (기본 dry-run)"
    )
    mode = p.add_mutually_exclusive_group()
    mode.add_argument(
        "--execute", action="store_true", help="실제 모터 이동 (--limits 필수)"
    )
    mode.add_argument(
        "--dry-run", action="store_true", help="JSON만 출력, 모터 요청 없음 (기본값)"
    )
    source = p.add_mutually_exclusive_group()
    source.add_argument("--text", help="호출어·녹음 없이 텍스트 명령 검증")
    source.add_argument(
        "--audio-file", type=Path, help="호출어 없이 mono PCM16 WAV 검증"
    )
    p.add_argument("--env-file", type=Path, help="키를 읽을 기존 env 파일")
    p.add_argument("--limits", type=Path, help="실측한 관절 min/max/max_delta JSON")
    p.add_argument("--base-url", default="http://localhost:6000")
    p.add_argument(
        "--transcription-model",
        default="gpt-4o-mini-transcribe",
        help="1번: 음성 인식 모델",
    )
    p.add_argument("--llm-model", default="gpt-4o-mini", help="2번: JSON 변환 모델")
    p.add_argument(
        "--wake-model", default="small", help="로컬 Whisper 다국어 모델 또는 로컬 경로"
    )
    p.add_argument("--wake-phrase", default="로봇")
    p.add_argument("--device", help="마이크 장치 번호 또는 이름")
    p.add_argument(
        "--list-devices",
        action="store_true",
        help="API 연결 없이 오디오 장치 목록 출력",
    )
    p.add_argument("--rms-threshold", type=float, default=0.015)
    p.add_argument("--silence-seconds", type=float, default=0.8)
    p.add_argument("--max-record-seconds", type=float, default=10)
    return p


def build_intent(args):
    from openai import OpenAI

    client = OpenAI(api_key=load_api_key(args.env_file), timeout=20, max_retries=0)
    return IntentClient(client, args.transcription_model, args.llm_model)


def build_executor(args, limits):
    module = importlib.import_module("TITI.robot_arm_app.클라이언트")
    arm = module.로봇팔(base_url=args.base_url, timeout=2.0)
    return Executor(arm, limits)


def handle_command(command: Command, executor: Executor | None) -> dict:
    command = parse_command(command.to_dict())
    if command.action == "unknown":
        return {
            "status": "unknown",
            "message": "모터 번호와 절대 위치를 명확히 말씀해 주세요.",
        }
    if executor is None:
        return {
            "status": "dry_run",
            "command": command.to_dict(),
            "targets": {f"motor_{t.motor}": t.position for t in command.targets},
        }
    positions = executor.execute(command)
    return {"status": "completed", "positions": positions, "command": command.to_dict()}


def show_result(command, executor):
    result = handle_command(command, executor)
    print(json.dumps(result, ensure_ascii=False), flush=True)
    return result


def load_wake_model(name):
    from faster_whisper import WhisperModel

    return WhisperModel(name, device="cpu", compute_type="int8", cpu_threads=4)


def run_voice(mic, detector, intent, executor, settings):
    import numpy as np

    buffer = np.empty(0, dtype=np.float32)
    print("호출어 대기: “로봇”이라고 말한 뒤 준비 신호를 기다리세요.", flush=True)
    while True:
        buffer = np.concatenate((buffer, mic.read_frame()))
        if len(buffer) < 2 * settings.sample_rate:
            continue
        found = detector.detect(buffer)
        buffer = buffer[-settings.sample_rate // 2 :]
        if not found:
            continue
        # Inference can be slower than real time; discard everything captured during it.
        mic.flush()
        buffer = np.empty(0, dtype=np.float32)
        print("\a준비됐습니다. 모터 번호와 목표 위치를 말씀해 주세요.", flush=True)
        before = mic.discontinuities
        try:
            wav = capture_utterance(mic.read_frame, settings)
            if mic.discontinuities != before:
                print(
                    "녹음 입력이 끊겨 명령을 취소했습니다. 다시 호출해 주세요.",
                    flush=True,
                )
                continue
            if wav is None:
                print("명령 음성이 없습니다. 다시 호출해 주세요.", flush=True)
                continue
            print("음성 인식 및 JSON 변환 중…", flush=True)
            text, command = intent.from_audio(wav)
            print("인식:", text, flush=True)
            show_result(command, executor)
        except IntentError as exc:
            print(str(exc), file=sys.stderr, flush=True)
        finally:
            mic.flush()
            print("호출어 대기: “로봇”", flush=True)


def run_microphone(args, intent, executor):
    from .wake import WakeDetector

    settings = AudioSettings(
        rms_threshold=args.rms_threshold,
        silence_s=args.silence_seconds,
        max_record_s=args.max_record_seconds,
    )
    print(
        f"로컬 호출어 모델 로딩: {args.wake_model} (최초 실행은 다운로드가 필요합니다)",
        flush=True,
    )
    model = load_wake_model(args.wake_model)
    detector = WakeDetector(model, args.wake_phrase, settings.rms_threshold)
    device = args.device
    if device is not None and device.isdecimal():
        device = int(device)
    with Microphone(device, settings) as mic:
        run_voice(mic, detector, intent, executor, settings)


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if args.list_devices:
        try:
            import sounddevice as sd

            print(sd.query_devices())
            return 0
        except Exception:
            print("오디오 장치 목록을 읽을 수 없습니다.", file=sys.stderr)
            return 1
    if args.execute and args.limits is None:
        print("--execute에는 실측한 --limits 파일이 필요합니다.", file=sys.stderr)
        return 2
    try:
        limits = load_limits(args.limits) if args.limits is not None else None
        AudioSettings(
            rms_threshold=args.rms_threshold,
            silence_s=args.silence_seconds,
            max_record_s=args.max_record_seconds,
        )
        if not args.wake_phrase.strip():
            raise ValueError("호출어가 비어 있습니다.")
        intent = build_intent(args)
        executor = build_executor(args, limits) if args.execute else None
        if args.text is not None:
            show_result(intent.from_text(args.text), executor)
        elif args.audio_file is not None:
            # Bound file input before allocating or uploading it.
            if args.audio_file.stat().st_size > 2_000_000:
                raise ValueError("WAV 파일은 2 MB 이하여야 합니다.")
            text, command = intent.from_audio(args.audio_file.read_bytes())
            print("인식:", text, flush=True)
            show_result(command, executor)
        else:
            run_microphone(args, intent, executor)
        return 0
    except KeyboardInterrupt:
        print(
            "\n종료했습니다. 이미 보낸 모터 목표는 취소되지 않습니다.", file=sys.stderr
        )
        return 130
    except (IntentError, ExecutionError, AudioError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except OSError:
        print(
            "파일 또는 장치에 접근할 수 없습니다. 경로와 권한을 확인하세요.",
            file=sys.stderr,
        )
        return 1
    except ImportError:
        print(
            "음성 제어 의존성을 설치하세요: pip install -r TITI/voice_motor/requirements.txt",
            file=sys.stderr,
        )
        return 1
    except Exception as exc:
        # Model/download/device library exceptions may contain credentials or URLs.
        print(
            f"음성 제어 초기화·처리에 실패했습니다 ({type(exc).__name__}). 모델·장치·연결을 확인하세요.",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
