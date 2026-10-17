"""Read local settings without copying or logging credentials."""

import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MOTOR_NAMES = tuple(f"motor_{i}" for i in range(1, 7))


def load_api_key(env_file: Path | None = None) -> str:
    if env_file is not None and not Path(env_file).is_file():
        raise ValueError("지정한 --env-file이 없습니다.")
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if key:
        return key
    from dotenv import dotenv_values

    candidates = (
        [Path(env_file)]
        if env_file is not None
        else [ROOT / ".env", ROOT.parent / ".env"]
    )
    for path in candidates:
        if path.is_file():
            value = dotenv_values(path, interpolate=False).get("OPENAI_API_KEY")
            if value and value.strip():
                return value.strip()
    raise ValueError("OPENAI_API_KEY가 설정되지 않았습니다.")


def validate_limits(data: object) -> dict[str, dict[str, int]]:
    if not isinstance(data, dict) or set(data) != set(MOTOR_NAMES):
        raise ValueError("제한 파일에 motor_1~motor_6 모두 필요합니다.")
    for values in data.values():
        if not isinstance(values, dict) or set(values) != {"min", "max", "max_delta"}:
            raise ValueError("각 모터에 min, max, max_delta가 필요합니다.")
        if any(type(value) is not int for value in values.values()):
            raise ValueError("관절 제한값은 정수여야 합니다.")
        if not (
            0 <= values["min"] < values["max"] <= 4095
            and 1 <= values["max_delta"] <= 4095
        ):
            raise ValueError("관절 제한값 범위가 잘못되었습니다.")
    return data


def load_limits(path: Path) -> dict[str, dict[str, int]]:
    try:
        return validate_limits(json.loads(Path(path).read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("관절 제한 파일을 읽을 수 없습니다.") from exc
