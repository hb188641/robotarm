import io
import wave
from types import SimpleNamespace as NS
import numpy as np
import pytest
from TITI.voice_motor.audio import (
    AudioSettings,
    AudioError,
    Microphone,
    capture_utterance,
)
from TITI.voice_motor.wake import WakeDetector


def frames(speech=10, leading=0, trailing=40):
    return iter(
        [np.zeros(480, dtype=np.float32) for _ in range(leading)]
        + [np.full(480, 0.1, dtype=np.float32) for _ in range(speech)]
        + [np.zeros(480, dtype=np.float32) for _ in range(trailing)]
    )


def test_recording_stops_at_silence_and_produces_pcm16():
    source = frames(10, leading=2)
    result = capture_utterance(lambda: next(source), AudioSettings())
    with wave.open(io.BytesIO(result)) as audio:
        assert (audio.getnchannels(), audio.getsampwidth(), audio.getframerate()) == (
            1,
            2,
            16000,
        )
        assert 0.3 <= audio.getnframes() / 16000 < 1.5


@pytest.mark.parametrize("speech", [0, 2])
def test_silence_or_short_speech_not_sent(speech):
    source = frames(speech, trailing=200)
    assert capture_utterance(lambda: next(source), AudioSettings()) is None


def test_maximum_duration_and_source_exhaustion():
    source = frames(100)
    result = capture_utterance(lambda: next(source), AudioSettings(max_record_s=0.6))
    with wave.open(io.BytesIO(result)) as audio:
        assert audio.getnframes() <= 9600
    empty = iter([])
    assert capture_utterance(lambda: next(empty), AudioSettings()) is None


def test_microphone_queue_discards_old_audio_and_flushes():
    mic = Microphone(None, AudioSettings())
    for i in range(100):
        mic._callback(np.full((480, 1), i, dtype=np.float32), 480, None, None)
    assert mic.discontinuities > 0
    assert mic.read_frame()[0] > 0
    mic.flush()
    assert mic.pending_frames == 0


def test_invalid_frames_and_settings_fail():
    with pytest.raises(ValueError):
        AudioSettings(rms_threshold=float("nan"))
    with pytest.raises(AudioError):
        capture_utterance(lambda: np.full(480, float("nan")), AudioSettings())


@pytest.mark.parametrize(
    "text,want",
    [
        ("로봇.", True),
        ("로봇", True),
        ("로봇 공학", True),
        ("로봇팔", False),
        ("로봇입니다", False),
        ("", False),
    ],
)
def test_wake_word_boundaries(text, want):
    class Model:
        def transcribe(self, samples, **kwargs):
            assert kwargs["language"] == "ko"
            assert kwargs["vad_filter"] is True
            return iter([NS(text=text, no_speech_prob=0.01, avg_logprob=-0.1)]), NS()

    assert WakeDetector(Model()).detect(np.ones(32000, dtype=np.float32) * 0.1) is want


def test_silence_and_hallucinated_wake_are_ignored():
    class Model:
        def transcribe(self, *args, **kwargs):
            return iter([NS(text="로봇", no_speech_prob=0.99, avg_logprob=-2)]), NS()

    detector = WakeDetector(Model())
    assert not detector.detect(np.ones(32000, dtype=np.float32) * 0.1)
    assert not detector.detect(np.zeros(32000, dtype=np.float32))
