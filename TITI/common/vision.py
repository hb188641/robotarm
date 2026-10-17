from __future__ import annotations

from pathlib import Path
from typing import Dict, Iterable, Tuple

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

# cv2.putText는 한글 글리프가 없는 Hershey 폰트만 지원해서 화면에 "?"로 깨진다.
# OS별 한글 지원 폰트 후보 중 존재하는 첫 번째를 사용해 PIL로 텍스트를 그린다.
_KOREAN_FONT_CANDIDATES = [
    "/System/Library/Fonts/AppleSDGothicNeo.ttc",  # macOS
    "C:/Windows/Fonts/malgun.ttf",  # Windows
    "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",  # Linux
]
_FONT_CACHE: Dict[int, ImageFont.ImageFont] = {}


def _get_korean_font(size: int) -> ImageFont.ImageFont:
    font = _FONT_CACHE.get(size)
    if font is not None:
        return font
    for candidate in _KOREAN_FONT_CANDIDATES:
        if Path(candidate).exists():
            font = ImageFont.truetype(candidate, size)
            break
    else:
        font = ImageFont.load_default()
    _FONT_CACHE[size] = font
    return font


def open_camera(
    camera_index: int, width: int, height: int, fps: int
) -> cv2.VideoCapture:
    cap = cv2.VideoCapture(camera_index)
    if not cap.isOpened():
        raise RuntimeError(f"Camera index {camera_index} could not be opened.")

    if width > 0:
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
    if height > 0:
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
    if fps > 0:
        cap.set(cv2.CAP_PROP_FPS, fps)

    ok, frame = cap.read()
    if not ok or frame is None:
        cap.release()
        raise RuntimeError(
            f"Camera index {camera_index} opened, but no frame was received."
        )

    return cap


def draw_text_panel(
    frame: np.ndarray,
    lines: Iterable[str],
    origin: Tuple[int, int] = (16, 28),
    line_height: int = 24,
) -> None:
    lines = list(lines)
    if not lines:
        return

    x, y = origin
    width = max(260, max(len(line) for line in lines) * 20 + 24)
    height = line_height * len(lines) + 16
    overlay = frame.copy()
    cv2.rectangle(
        overlay, (x - 8, y - 24), (x - 8 + width, y - 24 + height), (0, 0, 0), -1
    )
    cv2.addWeighted(overlay, 0.55, frame, 0.45, 0.0, frame)

    image = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
    draw = ImageDraw.Draw(image)
    font = _get_korean_font(20)
    for idx, line in enumerate(lines):
        draw.text(
            (x, y + idx * line_height - 20), line, font=font, fill=(255, 255, 255)
        )
    frame[:] = cv2.cvtColor(np.array(image), cv2.COLOR_RGB2BGR)


def resize_for_display(frame: np.ndarray, display_width: int) -> np.ndarray:
    if display_width <= 0 or frame.shape[1] <= display_width:
        return frame
    scale = display_width / float(frame.shape[1])
    display_height = int(frame.shape[0] * scale)
    return cv2.resize(
        frame, (display_width, display_height), interpolation=cv2.INTER_AREA
    )
