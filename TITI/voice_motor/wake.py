"""Local Korean wake phrase detection; never uploads waiting audio."""
import re

import numpy as np


class WakeDetector:
    def __init__(self, model, phrase: str = '로봇', rms_threshold: float = 0.015):
        phrase = phrase.strip()
        if not phrase:
            raise ValueError('호출어가 비어 있습니다.')
        self.model = model
        self.pattern = re.compile(r'(?<![가-힣A-Za-z0-9_])' + re.escape(phrase) + r'(?![가-힣A-Za-z0-9_])')
        self.rms_threshold = rms_threshold

    def detect(self, samples: np.ndarray) -> bool:
        if not samples.size or not np.isfinite(samples).all():
            return False
        if float(np.sqrt(np.mean(samples * samples))) < self.rms_threshold:
            return False
        segments, _ = self.model.transcribe(
            samples, language='ko', beam_size=1, vad_filter=True,
            condition_on_previous_text=False,
        )
        text = ' '.join(segment.text for segment in segments
                        if segment.no_speech_prob < 0.6 and segment.avg_logprob >= -1)
        return self.pattern.search(text) is not None
