"""Bounded microphone input and silence-delimited PCM16 recording."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import numpy as np

from dataclasses import dataclass
import io
import math
import queue
import wave


class AudioError(Exception):
    pass


@dataclass(frozen=True)
class AudioSettings:
    sample_rate: int = 16000
    block_ms: int = 30
    silence_s: float = 0.8
    start_timeout_s: float = 5.0
    max_record_s: float = 10.0
    min_speech_s: float = 0.2
    rms_threshold: float = 0.015

    def __post_init__(self):
        if self.sample_rate != 16000 or self.block_ms != 30:
            raise ValueError("오디오는 16000 Hz, 30 ms 프레임을 사용합니다.")
        for value in (
            self.silence_s,
            self.start_timeout_s,
            self.max_record_s,
            self.min_speech_s,
            self.rms_threshold,
        ):
            if not math.isfinite(value) or value <= 0:
                raise ValueError("오디오 설정은 양수여야 합니다.")
        if (
            self.max_record_s > 30
            or self.min_speech_s > self.max_record_s
            or self.rms_threshold > 1
        ):
            raise ValueError("오디오 설정 범위가 잘못되었습니다.")

    @property
    def block_size(self):
        return self.sample_rate * self.block_ms // 1000


def checked_frame(samples) -> np.ndarray:
    import numpy as np

    frame = np.asarray(samples, dtype=np.float32).reshape(-1)
    if frame.size != 480 or not np.isfinite(frame).all():
        raise AudioError("마이크 입력 프레임이 올바르지 않습니다.")
    return frame


def to_wav(samples: np.ndarray, sample_rate: int = 16000) -> bytes:
    import numpy as np

    data = (np.clip(samples, -1, 1) * 32767).astype("<i2").tobytes()
    output = io.BytesIO()
    with wave.open(output, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(sample_rate)
        audio.writeframes(data)
    return output.getvalue()


def capture_utterance(read_frame, settings: AudioSettings) -> bytes | None:
    import numpy as np

    recorded = []
    waiting_samples = speech_samples = silent_samples = 0
    recorded_samples = 0
    rate = settings.sample_rate
    while True:
        try:
            frame = checked_frame(read_frame())
        except StopIteration:
            break
        voiced = float(np.sqrt(np.mean(frame * frame))) >= settings.rms_threshold
        if not recorded and not voiced:
            waiting_samples += frame.size
            if waiting_samples >= settings.start_timeout_s * rate:
                return None
            continue
        remaining = max(0, int(settings.max_record_s * rate) - recorded_samples)
        frame = frame[:remaining]
        if not frame.size:
            break
        recorded.append(frame)
        recorded_samples += frame.size
        speech_samples += frame.size if voiced else 0
        silent_samples = 0 if voiced else silent_samples + frame.size
        if (
            recorded_samples >= settings.max_record_s * rate
            or silent_samples >= settings.silence_s * rate
        ):
            break
    if speech_samples < settings.min_speech_s * rate:
        return None
    return to_wav(np.concatenate(recorded), rate)


class Microphone:
    """The callback never runs inference. Pending audio is capped at 0.5 seconds."""

    def __init__(self, device, settings: AudioSettings):
        self.device, self.settings = device, settings
        self._frames = queue.Queue(maxsize=math.ceil(500 / settings.block_ms))
        self.discontinuities = 0
        self._stream = None

    @property
    def pending_frames(self):
        return self._frames.qsize()

    def _callback(self, indata, frames, time_info, status):
        if status:
            self.discontinuities += 1
        item = indata[:, 0].copy()
        try:
            self._frames.put_nowait(item)
        except queue.Full:
            self.discontinuities += 1
            try:
                self._frames.get_nowait()
            except queue.Empty:
                pass
            try:
                self._frames.put_nowait(item)
            except queue.Full:
                pass

    def __enter__(self):
        import sounddevice as sd

        try:
            self._stream = sd.InputStream(
                samplerate=self.settings.sample_rate,
                blocksize=self.settings.block_size,
                channels=1,
                dtype="float32",
                device=self.device,
                callback=self._callback,
            )
            self._stream.start()
        except Exception:
            if self._stream is not None:
                self._stream.close()
            raise AudioError(
                "마이크를 열 수 없습니다. 장치·권한·16000 Hz 지원을 확인하세요."
            ) from None
        return self

    def __exit__(self, *args):
        if self._stream is not None:
            try:
                self._stream.stop()
            finally:
                self._stream.close()

    def read_frame(self):
        try:
            return self._frames.get(timeout=2.0)
        except queue.Empty:
            raise AudioError("마이크 입력이 중단되었습니다.") from None

    def flush(self):
        while True:
            try:
                self._frames.get_nowait()
            except queue.Empty:
                return
