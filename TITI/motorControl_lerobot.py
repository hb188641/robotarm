"""
motorControl.py를 LeRobot의 FeetechMotorsBus API로 마이그레이션한 버전.

원본(motorControl.py)의 커스텀 시리얼 패킷 코드(checksum, write_position, read_position 등)는
LeRobot의 FeetechMotorsBus가 내부적으로 동일한 제어 테이블 주소(Torque_Enable=40,
Goal_Position=42, Present_Position=56)를 사용해 대체한다. 원본은 raw tick 값(0~4095)을
그대로 다뤘으므로 calibration 없이 normalize=False로 동일하게 동작시킨다.

필요 패키지: pip install -e ".[feetech]"  (lerobot 저장소 기준) 또는 `pip install lerobot feetech-servo-sdk`
"""

import time

from lerobot.motors import Motor, MotorNormMode
from lerobot.motors.feetech import FeetechMotorsBus

PORT = "COM4"
MOTOR_ID = 15
MOTOR_MODEL = "sts3215"  # 원본 제어 테이블 주소(40/42/56)와 baudrate(1e6)가 STS/SMS 시리즈와 일치

bus = FeetechMotorsBus(
    port=PORT,
    motors={
        "motor_1": Motor(MOTOR_ID, MOTOR_MODEL, MotorNormMode.RANGE_M100_100),
    },
)


def write_position(bus: FeetechMotorsBus, motor: str, position: int) -> None:
    position = min(max(position, 0), 4095)
    bus.write("Goal_Position", motor, position, normalize=False)


def read_position(bus: FeetechMotorsBus, motor: str) -> int:
    return bus.read("Present_Position", motor, normalize=False)


bus.connect()
print("Connected")
print("PORT = ", PORT)

motor = "motor_1"
start = 865

try:
    write_position(bus, motor, start)
    bus.enable_torque(motor)
    while True:
        write_position(bus, motor, start + 30)
        start = start + 1
        time.sleep(0.001)
        print(read_position(bus, motor))
finally:
    bus.disable_torque(motor)
    print("done!")
    bus.disconnect()
    print("Closed")
