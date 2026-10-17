import pytest
from TITI.voice_motor.commands import parse_command
from TITI.voice_motor.executor import Executor, ExecutionError


class Arm:
    def __init__(self, arrived=True, broken_write=False):
        self.positions = {f"motor_{i}": 2100 for i in range(1, 7)}
        self.writes = []
        self.arrived, self.broken_write = arrived, broken_write

    def 위치목록(self):
        return self.positions.copy()

    def 여러개이동(self, targets):
        self.writes.append(targets.copy())
        if self.broken_write:
            raise TimeoutError("provider private detail")
        if self.arrived:
            self.positions.update(targets)

    def 토크켜기(self):
        pytest.fail("must not change torque")

    토크끄기 = 토크켜기


def limits():
    return {
        f"motor_{i}": {"min": 1800, "max": 2400, "max_delta": 200} for i in range(1, 7)
    }


def command(*targets):
    return parse_command(
        {"action": "move", "targets": [{"motor": m, "position": p} for m, p in targets]}
    )


def test_moves_once_and_confirms_actual_position():
    arm = Arm()
    assert Executor(arm, limits()).execute(command((3, 2200))) == {"motor_3": 2200}
    assert arm.writes == [{"motor_3": 2200}]


@pytest.mark.parametrize("targets", [((3, 2500),), ((3, 2200), (2, 2400))])
def test_entire_batch_rejected_before_writing(targets):
    arm = Arm()
    with pytest.raises(ExecutionError):
        Executor(arm, limits()).execute(command(*targets))
    assert arm.writes == []


@pytest.mark.parametrize("value", [None, True, float("nan"), 5000, 2100.0])
def test_invalid_current_state_never_writes(value):
    arm = Arm()
    if value is None:
        del arm.positions["motor_3"]
    else:
        arm.positions["motor_3"] = value
    with pytest.raises(ExecutionError):
        Executor(arm, limits()).execute(command((3, 2200)))
    assert arm.writes == []


def test_unknown_never_writes():
    arm = Arm()
    with pytest.raises(ExecutionError):
        Executor(arm, limits()).execute(
            parse_command({"action": "unknown", "targets": []})
        )
    assert arm.writes == []


def test_ambiguous_write_is_not_retried():
    arm = Arm(broken_write=True)
    with pytest.raises(ExecutionError, match="불명확") as exc:
        Executor(arm, limits()).execute(command((3, 2200)))
    assert "provider private" not in str(exc.value)
    assert len(arm.writes) == 1


def test_accepted_but_not_arrived_is_failure():
    arm = Arm(arrived=False)
    with pytest.raises(ExecutionError, match="도달"):
        Executor(arm, limits(), timeout_s=0.001, poll_s=0.001).execute(
            command((3, 2200))
        )
    assert len(arm.writes) == 1


def test_keyboard_interrupt_does_not_send_more_goals():
    arm = Arm()

    def interrupted(targets):
        arm.writes.append(targets)
        raise KeyboardInterrupt

    arm.여러개이동 = interrupted
    with pytest.raises(KeyboardInterrupt):
        Executor(arm, limits()).execute(command((3, 2200)))
    assert len(arm.writes) == 1
