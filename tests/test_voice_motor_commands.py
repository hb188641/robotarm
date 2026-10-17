"""Reject untrusted model values before they reach a motor."""

import pytest
from TITI.voice_motor.commands import parse_command


def test_valid_move_and_unknown():
    command = parse_command(
        {"action": "move", "targets": [{"motor": 3, "position": 2200}]}
    )
    assert [(t.motor, t.position) for t in command.targets] == [(3, 2200)]
    assert parse_command({"action": "unknown", "targets": []}).targets == ()


@pytest.mark.parametrize(
    "data",
    [
        None,
        [],
        {},
        {"action": "stop", "targets": []},
        {"action": "move", "targets": []},
        {"action": "unknown", "targets": [{"motor": 1, "position": 100}]},
        {"action": "move", "targets": [{"motor": 1, "position": 100}] * 2},
        {"action": "move", "targets": [{"motor": 1, "position": 100}], "code": "bad"},
        *[
            {"action": "move", "targets": [{"motor": n, "position": 100}]}
            for n in [0, 7, True, 3.0, "3"]
        ],
        *[
            {"action": "move", "targets": [{"motor": 1, "position": n}]}
            for n in [-1, 4096, True, 1.0, "1"]
        ],
        {"action": "move", "targets": [{"motor": 1, "position": 100, "speed": 1}]},
    ],
)
def test_invalid_command_rejected(data):
    with pytest.raises(ValueError):
        parse_command(data)
