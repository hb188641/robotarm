"""
방향키 홀드 + G 토글로 로봇 팔(6모터 중 1~4, 6번)을 제어.
토글이 아니라 홀드 방식 -> 키를 누르고 있는 동안만 계속 움직이고, 떼면 그 자리에서 멈춘다.

오른쪽 / 왼쪽: motor_1 위치를 계속 증가 / 감소

위: 기본은 motor_2 증가(<=2540), motor_3 감소(>=1300), motor_4 감소(>=2300)를 매 tick 동시에 적용
   단, motor_3 + motor_4 합이 4500을 넘으면 순서가 바뀜:
     1) motor_2를 1000까지 감소시킴 (motor_3/4는 정지)
     2) motor_2가 1000에 도달하면 그때부터 motor_3/4를 감소시킴 (motor_2는 정지)

아래: motor_3 증가, motor_4 증가는 조건 없이 매 tick마다 적용
     motor_2 감소는 motor_3(<=1300)와 motor_4(<=2300)가 둘 다 임계점에 도달했을 때만 적용
     (매 tick 하나의 sync_write로 적용 대상 모터들을 동시에 적용)

G: 그랩 토글 (홀드 아님, 누를 때마다 상태 전환)
   Activate: motor_6 -> 1500
   Release:  motor_6 -> 2300

필요 패키지: pip install keyboard
Windows에서 전역 키 후킹을 쓰므로 관리자 권한 터미널에서 실행해야 할 수 있음.
"""

import time

import keyboard

from lerobot.motors import Motor, MotorNormMode
from lerobot.motors.feetech import FeetechMotorsBus

PORT = "COM4"
MOTOR_MODEL = "sts3215"

TICK_INTERVAL = 0.02  # 50 Hz
STEP = 10  # tick당 이동량

# 각 모터의 임계점. 위쪽 키로는 이 값을 넘지 못하고, 아래쪽 키로 특수한 동작.
MOTOR_2_THRESHOLD = 2540  # 상한
MOTOR_3_THRESHOLD = 1300  # 하한
MOTOR_4_THRESHOLD = 2300  # 하한

SUM_THRESHOLD = 4500  # motor_3 + motor_4 합이 이 값을 넘으면 위쪽 키 동작 순서가 바뀜
MOTOR_2_LOWER = 1000  # 위 조건이 걸렸을 때 motor_2가 감소해서 도달해야 하는 하한

GRAB_ACTIVATE_POSITION = 1500  # G 토글 on 시 motor_6 목표
GRAB_RELEASE_POSITION = 2300  # G 토글 off 시 motor_6 목표

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


def clamp(pos: float) -> float:
    return min(max(pos, 0), 4095)


def main() -> None:
    bus.connect()
    print("Connected")
    bus.enable_torque()

    positions = bus.sync_read("Present_Position", normalize=False)
    grab_active = False
    g_was_pressed = False

    try:
        while True:
            right = keyboard.is_pressed("right")
            left = keyboard.is_pressed("left")
            up = keyboard.is_pressed("up")
            down = keyboard.is_pressed("down")
            g_pressed = keyboard.is_pressed("g")

            # G: 토글 (누르는 순간의 edge에서만 상태 전환)
            if g_pressed and not g_was_pressed:
                grab_active = not grab_active
                positions["motor_6"] = (
                    GRAB_ACTIVATE_POSITION if grab_active else GRAB_RELEASE_POSITION
                )
                bus.write(
                    "Goal_Position", "motor_6", positions["motor_6"], normalize=False
                )
            g_was_pressed = g_pressed

            # 좌우: motor_1 단독 이동
            if right or left:
                delta = STEP if right else -STEP
                positions["motor_1"] = clamp(positions["motor_1"] + delta)
                bus.write(
                    "Goal_Position", "motor_1", positions["motor_1"], normalize=False
                )

            # 위: 기본은 motor_2 증가 + motor_3/4 감소를 동시에 적용.
            # 단, motor_3 + motor_4 합이 임계값(4500)을 넘으면 순서가 바뀜:
            #   1) motor_2를 1000까지 감소
            #   2) motor_2가 1000에 도달하면 그때부터 motor_3/4를 감소
            if up:
                if positions["motor_3"] + positions["motor_4"] > SUM_THRESHOLD:
                    if positions["motor_2"] > MOTOR_2_LOWER:
                        positions["motor_2"] = max(
                            positions["motor_2"] - STEP, MOTOR_2_LOWER
                        )
                        bus.write(
                            "Goal_Position",
                            "motor_2",
                            positions["motor_2"],
                            normalize=False,
                        )
                    else:
                        positions["motor_3"] = max(
                            positions["motor_3"] - STEP, MOTOR_3_THRESHOLD
                        )
                        positions["motor_4"] = max(
                            positions["motor_4"] - STEP, MOTOR_4_THRESHOLD
                        )
                        bus.sync_write(
                            "Goal_Position",
                            {
                                "motor_3": positions["motor_3"],
                                "motor_4": positions["motor_4"],
                            },
                            normalize=False,
                        )
                else:
                    positions["motor_2"] = min(
                        positions["motor_2"] + STEP, MOTOR_2_THRESHOLD
                    )
                    positions["motor_3"] = max(
                        positions["motor_3"] - STEP, MOTOR_3_THRESHOLD
                    )
                    positions["motor_4"] = max(
                        positions["motor_4"] - STEP, MOTOR_4_THRESHOLD
                    )
                    bus.sync_write(
                        "Goal_Position",
                        {
                            "motor_2": positions["motor_2"],
                            "motor_3": positions["motor_3"],
                            "motor_4": positions["motor_4"],
                        },
                        normalize=False,
                    )

            # 아래: motor_3/4는 조건 없이 증가. motor_2는 motor_3와 motor_4가 모두
            # 임계점에 도달했을 때만 감소 가능
            if down:
                changed = {}

                positions["motor_3"] = clamp(positions["motor_3"] + STEP)
                changed["motor_3"] = positions["motor_3"]

                positions["motor_4"] = clamp(positions["motor_4"] + STEP)
                changed["motor_4"] = positions["motor_4"]

                if (
                    positions["motor_3"] <= MOTOR_3_THRESHOLD
                    and positions["motor_4"] <= MOTOR_4_THRESHOLD
                ):
                    positions["motor_2"] = clamp(positions["motor_2"] - STEP)
                    changed["motor_2"] = positions["motor_2"]

                bus.sync_write("Goal_Position", changed, normalize=False)

            time.sleep(TICK_INTERVAL)
    except KeyboardInterrupt:
        print("\nStopped")
    except ConnectionError:
        print("Motor had over-torqued")
    finally:
        bus.disable_torque()
        bus.disconnect()
        print("Closed")


if __name__ == "__main__":
    main()
