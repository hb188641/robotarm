"""
모터 토크 해제 스크립트.
motorControl_lerobot.py가 무한 루프에 빠졌을 때 사용.
"""

from lerobot.motors import Motor, MotorNormMode
from lerobot.motors.feetech import FeetechMotorsBus

PORT = "COM3"
MOTOR_ID = 1
MOTOR_MODEL = "sts3215"

bus = FeetechMotorsBus(
    port=PORT,
    motors={
        "motor_1": Motor(MOTOR_ID, MOTOR_MODEL, MotorNormMode.RANGE_M100_100),
    },
)

try:
    bus.connect()
    print("Connected")
    bus.disable_torque("motor_1")
    print("Torque disabled ✓")
finally:
    bus.disconnect()
