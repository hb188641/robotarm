"""Validate a whole batch before writing once, then confirm actual positions."""
import math
import time

from .commands import Command, parse_command
from .config import validate_limits


class ExecutionError(Exception):
    pass


class Executor:
    def __init__(self, arm, limits: dict, timeout_s=5.0, tolerance=20, poll_s=0.05):
        checked = validate_limits(limits)
        self.limits = {name: values.copy() for name, values in checked.items()}
        if not all(math.isfinite(v) and v > 0 for v in (timeout_s, poll_s)):
            raise ValueError('실행 타임아웃과 조회 간격은 양수여야 합니다.')
        if type(tolerance) is not int or not 0 <= tolerance <= 100:
            raise ValueError('도달 허용 오차는 정수 0~100이어야 합니다.')
        self.arm, self.timeout_s = arm, timeout_s
        self.tolerance, self.poll_s = tolerance, poll_s

    def _positions(self, names):
        try:
            positions = self.arm.위치목록()
        except Exception:
            raise ExecutionError('현재 모터 위치를 읽지 못했습니다.') from None
        if not isinstance(positions, dict):
            raise ExecutionError('서버의 모터 위치 형식이 올바르지 않습니다.')
        checked = {}
        for name in names:
            value = positions.get(name)
            if type(value) is not int or not 0 <= value <= 4095:
                raise ExecutionError('서버의 모터 위치가 없거나 올바르지 않습니다.')
            checked[name] = value
        return checked

    def execute(self, command: Command) -> dict[str, int]:
        try:
            command = parse_command(command.to_dict())
        except (ValueError, AttributeError):
            raise ExecutionError('잘못된 모터 명령입니다.') from None
        if command.action != 'move':
            raise ExecutionError('실행할 수 있는 이동 명령이 아닙니다.')
        targets = {f'motor_{t.motor}': t.position for t in command.targets}
        current = self._positions(targets)
        for name, goal in targets.items():
            limit = self.limits[name]
            if not limit['min'] <= goal <= limit['max']:
                raise ExecutionError(f'{name}: 관절 위치 제한을 초과했습니다.')
            if abs(goal - current[name]) > limit['max_delta']:
                raise ExecutionError(f'{name}: 명령당 최대 변화량을 초과했습니다.')
        try:
            self.arm.여러개이동(targets)
        except Exception:
            raise ExecutionError('모터 요청 결과가 불명확합니다. 자동 재시도하지 않습니다. 실제 위치를 확인하세요.') from None
        deadline = time.monotonic() + self.timeout_s
        while time.monotonic() < deadline:
            positions = self._positions(targets)
            if all(abs(positions[name] - goal) <= self.tolerance for name, goal in targets.items()):
                return positions
            time.sleep(self.poll_s)
        raise ExecutionError('시간 내 목표 위치에 도달하지 못했습니다. 현재 위치를 확인하세요.')
