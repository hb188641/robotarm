"""Strict boundary between model output and physical motor targets."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Target:
    motor: int
    position: int


@dataclass(frozen=True)
class Command:
    action: str
    targets: tuple[Target, ...]

    def to_dict(self) -> dict:
        return {
            "action": self.action,
            "targets": [
                {"motor": t.motor, "position": t.position} for t in self.targets
            ],
        }


def parse_command(data: object) -> Command:
    if not isinstance(data, dict) or set(data) != {"action", "targets"}:
        raise ValueError("명령에는 action, targets만 있어야 합니다.")
    action, targets = data["action"], data["targets"]
    if action not in ("move", "unknown") or not isinstance(targets, list):
        raise ValueError("잘못된 action 또는 targets입니다.")
    if (action == "unknown" and targets) or (
        action == "move" and not 1 <= len(targets) <= 6
    ):
        raise ValueError("명령의 모터 개수가 올바르지 않습니다.")
    parsed, seen = [], set()
    for item in targets:
        if not isinstance(item, dict) or set(item) != {"motor", "position"}:
            raise ValueError("모터 명령에는 motor, position만 허용합니다.")
        motor, position = item["motor"], item["position"]
        if type(motor) is not int or not 1 <= motor <= 6:
            raise ValueError("모터 번호는 정수 1~6이어야 합니다.")
        if type(position) is not int or not 0 <= position <= 4095:
            raise ValueError("위치는 정수 raw tick 0~4095여야 합니다.")
        if motor in seen:
            raise ValueError("중복된 모터 번호입니다.")
        seen.add(motor)
        parsed.append(Target(motor, position))
    return Command(action, tuple(parsed))


def command_schema() -> dict:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["action", "targets"],
        "properties": {
            "action": {"type": "string", "enum": ["move", "unknown"]},
            "targets": {
                "type": "array",
                "maxItems": 6,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["motor", "position"],
                    "properties": {
                        "motor": {"type": "integer", "minimum": 1, "maximum": 6},
                        "position": {"type": "integer", "minimum": 0, "maximum": 4095},
                    },
                },
            },
        },
    }
