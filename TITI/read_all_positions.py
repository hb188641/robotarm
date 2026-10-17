"""
6개 모터의 현재 위치를 실시간으로 무한 루프 출력.
원본 motorControl.py의 주석 코드를 LeRobot으로 구현.
"""

import time

from lerobot.motors import Motor, MotorNormMode
from lerobot.motors.feetech import FeetechMotorsBus

PORT = "COM4"
MOTOR_MODEL = "sts3215"

bus = FeetechMotorsBus(
    port=PORT,
    motors={
        "motor_1": Motor(1, MOTOR_MODEL, MotorNormMode.RANGE_M100_100),
        "motor_2": Motor(2, MOTOR_MODEL, MotorNormMode.RANGE_M100_100),
        "motor_3": Motor(3, MOTOR_MODEL, MotorNormMode.RANGE_M100_100),
        "motor_4": Motor(4, MOTOR_MODEL, MotorNormMode.RANGE_M100_100),
        "motor_5": Motor(5, MOTOR_MODEL, MotorNormMode.RANGE_M100_100),
        "motor_6": Motor(6, MOTOR_MODEL, MotorNormMode.RANGE_M100_100),
    },
)


def main() -> None:
    bus.connect()
    print("Connected to 6 motors")

    try:
        while True:
            positions = bus.sync_read("Present_Position", normalize=False)
            pos_str = " | ".join(
                f"{m}: {positions[m]:.0f}" for m in [f"motor_{i}" for i in range(1, 7)]
            )
            print(pos_str)
            time.sleep(0.1)
    except KeyboardInterrupt:
        print("\nStopped")
    finally:
        bus.disconnect()


if __name__ == "__main__":
    main()
