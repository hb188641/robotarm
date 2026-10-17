import importlib
import json
import subprocess
import sys
from types import SimpleNamespace as NS
import numpy as np
import pytest
from TITI.voice_motor import main as app
from TITI.voice_motor.audio import AudioSettings
from TITI.voice_motor.commands import parse_command
from TITI.voice_motor.intent import IntentError
from TITI.voice_motor.executor import ExecutionError


def move():
    return parse_command(
        {"action": "move", "targets": [{"motor": 3, "position": 2200}]}
    )


@pytest.mark.parametrize("flags", [[], ["--dry-run"]])
def test_text_dry_run_never_builds_motor_or_microphone(monkeypatch, capsys, flags):
    monkeypatch.setattr(
        app, "build_intent", lambda args: NS(from_text=lambda text: move())
    )
    monkeypatch.setattr(
        app, "build_executor", lambda *args: pytest.fail("motor created")
    )
    monkeypatch.setattr(
        app, "run_microphone", lambda *args: pytest.fail("microphone opened")
    )
    assert app.main(["--text", "3번 모터 위치 2200으로 이동", *flags]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["status"] == "dry_run"
    assert out["targets"] == {"motor_3": 2200}


def test_real_run_requires_limits_before_api(monkeypatch):
    monkeypatch.setattr(app, "build_intent", lambda args: pytest.fail("API created"))
    assert app.main(["--execute", "--text", "3번 모터 2200"]) == 2


def test_unknown_command_and_failure_never_execute():
    class FailExecutor:
        def execute(self, command):
            pytest.fail("unknown must not execute")

    unknown = parse_command({"action": "unknown", "targets": []})
    assert app.handle_command(unknown, FailExecutor())["status"] == "unknown"

    class BrokenExecutor:
        def execute(self, command):
            raise ExecutionError("not arrived")

    with pytest.raises(ExecutionError):
        app.handle_command(move(), BrokenExecutor())


def test_api_failure_returns_error_without_motor_build(monkeypatch, capsys):
    def fail(text):
        raise IntentError("API request failed")

    monkeypatch.setattr(app, "build_intent", lambda args: NS(from_text=fail))
    monkeypatch.setattr(
        app, "build_executor", lambda *args: pytest.fail("motor created")
    )
    assert app.main(["--text", "3번 모터 2200"]) == 1
    assert "completed" not in capsys.readouterr().out


def test_voice_loop_flushes_before_record_and_after_api(monkeypatch):
    events = []

    class Mic:
        discontinuities = 0

        def read_frame(self):
            return np.ones(480, dtype=np.float32) * 0.1

        def flush(self):
            events.append("flush")

    class Detector:
        calls = 0

        def detect(self, samples):
            self.calls += 1
            if self.calls == 2:
                raise KeyboardInterrupt
            events.append("wake")
            return True

    def record(read_frame, settings):
        events.append("record")
        return b"wav"

    def interpret(audio):
        events.append("api")
        return "3번 모터 위치 2200", move()

    monkeypatch.setattr(app, "capture_utterance", record)
    with pytest.raises(KeyboardInterrupt):
        app.run_voice(
            Mic(), Detector(), NS(from_audio=interpret), None, AudioSettings()
        )
    assert events[:5] == ["wake", "flush", "record", "api", "flush"]


def test_dropped_command_audio_skips_api(monkeypatch):
    class Mic:
        discontinuities = 0

        def read_frame(self):
            return np.ones(480, dtype=np.float32) * 0.1

        def flush(self):
            pass

    class Detector:
        calls = 0

        def detect(self, samples):
            self.calls += 1
            if self.calls > 1:
                raise KeyboardInterrupt
            return True

    mic = Mic()

    def record(*args):
        mic.discontinuities += 1
        return b"wav"

    monkeypatch.setattr(app, "capture_utterance", record)

    def fail(*args):
        pytest.fail("corrupt recording reached API")

    with pytest.raises(KeyboardInterrupt):
        app.run_voice(mic, Detector(), NS(from_audio=fail), None, AudioSettings())


def test_microphone_context_closed_on_interrupt(monkeypatch):
    events = []

    class Mic:
        def __init__(self, *args):
            pass

        def __enter__(self):
            events.append("opened")
            return self

        def __exit__(self, *args):
            events.append("closed")

    def interrupted(*args):
        raise KeyboardInterrupt

    monkeypatch.setattr(app, "Microphone", Mic)
    monkeypatch.setattr(app, "load_wake_model", lambda name: object())
    monkeypatch.setattr(app, "run_voice", interrupted)
    args = app.parser().parse_args([])
    with pytest.raises(KeyboardInterrupt):
        app.run_microphone(args, object(), None)
    assert events == ["opened", "closed"]


def test_imports_have_no_hardware_side_effects(monkeypatch):
    import requests
    import sounddevice
    import faster_whisper

    def fail(*args, **kwargs):
        pytest.fail("import opened external resource")

    monkeypatch.setattr(requests, "post", fail)
    monkeypatch.setattr(requests, "get", fail)
    monkeypatch.setattr(sounddevice, "InputStream", fail)
    monkeypatch.setattr(faster_whisper, "WhisperModel", fail)
    for name in ["commands", "config", "intent", "audio", "wake", "executor", "main"]:
        importlib.reload(importlib.import_module("TITI.voice_motor." + name))


def test_help_without_optional_dependencies():
    result = subprocess.run(
        [sys.executable, "-S", "-m", "TITI.voice_motor.main", "--help"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "--transcription-model" in result.stdout


def test_text_and_audio_file_mutually_exclusive():
    with pytest.raises(SystemExit) as error:
        app.parser().parse_args(["--text", "hello", "--audio-file", "a.wav"])
    assert error.value.code == 2


def test_incomplete_recording_skips_api_and_returns_to_wake():
    class Mic:
        discontinuities = 0

        def read_frame(self):
            return np.full(480, 0.1, dtype=np.float32)

        def flush(self):
            pass

    class Detector:
        calls = 0

        def detect(self, samples):
            self.calls += 1
            if self.calls > 1:
                raise KeyboardInterrupt
            return True

    def forbidden(*args):
        pytest.fail("An incomplete utterance must not reach API or motors")

    with pytest.raises(KeyboardInterrupt):
        app.run_voice(
            Mic(),
            Detector(),
            NS(from_audio=forbidden),
            NS(execute=forbidden),
            AudioSettings(max_record_s=0.6),
        )
