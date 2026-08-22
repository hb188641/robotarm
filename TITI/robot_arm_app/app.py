"""
LeRobot FeetechMotorsBus 기반 6모터 로봇팔을 REST API로 제어하는 Flask 서버.

templates/index.html의 브라우저 화면에서 마우스로 조작한 각도를 raw tick 값(0~4095)으로
변환해 POST로 보내면, 여기서 bus.write("Goal_Position", motor, value, normalize=False)로
해당 모터 하나만 독립적으로 움직인다.

필요 패키지: pip install flask lerobot feetech-servo-sdk
"""

import threading
import time

from flask import Flask, jsonify, render_template, request

from lerobot.motors import Motor, MotorNormMode
from lerobot.motors.feetech import FeetechMotorsBus

PORT = "/dev/cu.usbmodem5B421385261"
MOTOR_MODEL = "sts3215"
MOTOR_NAMES = ["motor_1", "motor_2", "motor_3", "motor_4", "motor_5", "motor_6"]

app = Flask(__name__)

bus = FeetechMotorsBus(
    port=PORT,
    motors={
        name: Motor(i + 1, MOTOR_MODEL, MotorNormMode.RANGE_M100_100)
        for i, name in enumerate(MOTOR_NAMES)
    },
)

# Flask 개발 서버는 요청을 여러 스레드에서 처리할 수 있어 시리얼 버스 접근을 직렬화해야 함
bus_lock = threading.Lock()


def connect_bus() -> None:
    with bus_lock:
        bus.connect()
        time.sleep(0.2)  # 포트를 연 직후 버스가 안정화될 시간을 줌 (원본 motorControl.py와 동일한 지연)
        bus.enable_torque(num_retry=3)


@app.route("/")
def index():
    return render_template("index.html", motor_names=MOTOR_NAMES)


@app.route("/api/state")
def get_state():
    with bus_lock:
        positions = bus.sync_read("Present_Position", normalize=False)
    return jsonify(positions)


@app.route("/api/motor/<motor_name>/goal", methods=["POST"])
def set_goal(motor_name):
    if motor_name not in MOTOR_NAMES:
        return jsonify({"error": f"unknown motor '{motor_name}'"}), 404

    data = request.get_json(silent=True) or {}
    position = data.get("position")
    if position is None:
        return jsonify({"error": "missing 'position'"}), 400

    position = int(min(max(position, 0), 4095))
    with bus_lock:
        bus.write("Goal_Position", motor_name, position, normalize=False)

    return jsonify({"motor": motor_name, "position": position})


@app.route("/api/motors/goal", methods=["POST"])
def set_goals():
    """여러 모터를 한 번의 요청으로 동시에 이동 (sync_write). body: {"motor_2": 2500, "motor_3": 1600}"""
    data = request.get_json(silent=True) or {}
    unknown = [name for name in data if name not in MOTOR_NAMES]
    if unknown:
        return jsonify({"error": f"unknown motor(s) {unknown}"}), 404

    values = {name: int(min(max(pos, 0), 4095)) for name, pos in data.items()}
    if values:
        with bus_lock:
            bus.sync_write("Goal_Position", values, normalize=False)

    return jsonify(values)


@app.route("/api/torque", methods=["POST"])
def set_torque():
    data = request.get_json(silent=True) or {}
    enabled = bool(data.get("enabled", True))
    with bus_lock:
        if enabled:
            bus.enable_torque(num_retry=3)
        else:
            bus.disable_torque()
    return jsonify({"torque_enabled": enabled})


if __name__ == "__main__":
    connect_bus()
    try:
        app.run(host="0.0.0.0", port=6000, debug=False)
    finally:
        with bus_lock:
            bus.disable_torque()
            bus.disconnect()
