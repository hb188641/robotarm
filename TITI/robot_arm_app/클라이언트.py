"""
robot_arm_app(app.py)의 REST API를 감싸는 사용자 친화적인 파이썬 클라이언트.

lerobot/시리얼 포트를 직접 다루지 않고, Flask 서버(app.py)가 떠 있는 주소로 HTTP 요청만
보내면 되므로 다른 PC/스크립트에서도 하드웨어 세부사항 없이 바로 팔을 조종할 수 있다.

사용 예:
    from client import 로봇팔

    arm = 로봇팔()                          # 기본: http://localhost:5000
    arm.이동("motor_2", 2500)               # 모터 하나만 raw tick으로 이동
    arm.각도이동("motor_3", -30)            # 중앙(2048=0도) 기준 각도로 이동
    arm.여러개이동({"motor_3": 1600, "motor_4": 2300})  # 여러 모터 동시 이동
    arm.잡기()                              # 그리퍼 닫기
    arm.놓기()                              # 그리퍼 열기
    print(arm.위치목록())                    # 전체 모터 현재 위치
    arm.도달할때까지대기("motor_2", 2500)
"""

import time

import requests

MOTOR_NAMES = ["motor_1", "motor_2", "motor_3", "motor_4", "motor_5", "motor_6"]

RAW_MAX = 4095
CENTER = 2048
TICKS_PER_DEG = 4096 / 360

GRAB_POSITION = 1500
RELEASE_POSITION = 2300


class 로봇팔:
    def __init__(self, base_url: str = "http://localhost:5000", timeout: float = 2.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def _조회(self, path: str):
        r = requests.get(f"{self.base_url}{path}", timeout=self.timeout)
        r.raise_for_status()
        return r.json()

    def _전송(self, path: str, body: dict):
        r = requests.post(f"{self.base_url}{path}", json=body, timeout=self.timeout)
        r.raise_for_status()
        return r.json()

    # ---- 조회 ----

    def 위치목록(self) -> dict:
        """전체 모터의 현재 raw position(0~4095)을 dict로 반환."""
        return self._조회("/api/state")

    def 위치(self, motor: str) -> int:
        """모터 하나의 현재 raw position."""
        self._모터확인(motor)
        return self.위치목록()[motor]

    def 각도(self, motor: str) -> float:
        """중앙(2048)을 0도로 하는 상대 각도로 현재 위치를 반환."""
        return self._raw를각도로(self.위치(motor))

    # ---- 이동 ----

    def 이동(self, motor: str, position: int) -> None:
        """모터 하나를 raw tick(0~4095)으로 독립적으로 이동."""
        self._모터확인(motor)
        position = int(min(max(position, 0), RAW_MAX))
        self._전송(f"/api/motor/{motor}/goal", {"position": position})

    def 각도이동(self, motor: str, degrees: float) -> None:
        """중앙(2048=0도) 기준 각도로 모터 하나를 이동."""
        self.이동(motor, self._각도를raw로(degrees))

    def 여러개이동(self, targets: dict) -> None:
        """여러 모터를 한 번의 요청으로 동시에 이동. 예: {"motor_2": 2500, "motor_3": 1600}"""
        for motor in targets:
            self._모터확인(motor)
        clamped = {m: int(min(max(p, 0), RAW_MAX)) for m, p in targets.items()}
        self._전송("/api/motors/goal", clamped)

    def 도달할때까지대기(self, motor: str, target: int, tolerance: int = 20, timeout: float = 5.0) -> bool:
        """모터가 목표 위치 근처(오차범위 tolerance)에 도달할 때까지 대기. 도달하면 True, 타임아웃되면 False."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            if abs(self.위치(motor) - target) <= tolerance:
                return True
            time.sleep(0.05)
        return False

    # ---- 그리퍼 편의 메서드 ----

    def 잡기(self) -> None:
        self.이동("motor_6", GRAB_POSITION)

    def 놓기(self) -> None:
        self.이동("motor_6", RELEASE_POSITION)

    # ---- 토크 ----

    def 토크켜기(self) -> None:
        self._전송("/api/torque", {"enabled": True})

    def 토크끄기(self) -> None:
        self._전송("/api/torque", {"enabled": False})

    # ---- 내부 유틸 ----

    @staticmethod
    def _모터확인(motor: str) -> None:
        if motor not in MOTOR_NAMES:
            raise ValueError(f"알 수 없는 모터 '{motor}', 다음 중 하나여야 함: {MOTOR_NAMES}")

    @staticmethod
    def _raw를각도로(raw: int) -> float:
        return (raw - CENTER) / TICKS_PER_DEG

    @staticmethod
    def _각도를raw로(deg: float) -> int:
        return round(CENTER + deg * TICKS_PER_DEG)


if __name__ == "__main__":
    arm = 로봇팔()
    print("현재 위치:", arm.위치목록())
