# Pose Landmarker 기반 로봇팔 텔레옵 (motor_1~3) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 사람의 어깨/팔꿈치/손목/엉덩이 pose landmark로 로봇팔의 motor_1(base yaw)/motor_2(shoulder_lift)/motor_3(elbow_flex)를 실시간으로 미러링하는 새 서브시스템 `TITI/arm_teleop`을 만든다.

**Architecture:** landmark 좌표 → 벡터 각도 직접 계산(학습 없음) → EMA 스무딩 → 2점 선형 캘리브레이션으로 raw tick 변환 → `클라이언트.py`의 `로봇팔.여러개이동()`으로 전송. 순수 계산 함수(`teleop_common.py`)는 mediapipe/카메라/하드웨어와 분리해 pytest로 단위 테스트하고, 카메라/하드웨어를 묶는 `calibrate.py`/`run_teleop.py`는 수동으로 검증한다.

**Tech Stack:** Python, mediapipe(PoseLandmarker), OpenCV, pytest(신규 도입), 기존 `TITI/robot_arm_app/클라이언트.py`의 `로봇팔` 클래스.

**Spec:** [docs/superpowers/specs/2026-08-22-arm-teleop-design.md](../specs/2026-08-22-arm-teleop-design.md)

## Global Constraints

- `mediapipe>=0.10.0,<1.0.0` — 1.0.x는 macOS에서 GPU 초기화 크래시가 있음을 확인했으므로 절대 상한을 넘기지 않는다.
- raw tick 범위는 항상 `[0, 4095]`이고, 캘리브레이션이 정의한 `[raw_min, raw_max]`(두 기준점 중 작은/큰 값)를 벗어나면 클램프한다.
- 종료(q/ESC) 또는 예외 발생 시 `finally` 블록에서 반드시 `팔.토크끄기()`를 호출한다 (오타로 인한 과거 버그 재발 방지).
- 실측 캘리브레이션 값이 담긴 `calibration.json`은 git에 커밋하지 않는다 (`.gitignore` 대상). 저장소에는 스키마 예시(`calibration.example.json`)만 남긴다.

---

## File Structure

```
TITI/arm_teleop/
  requirements.txt              # mediapipe<1.0.0, opencv-python, numpy, Pillow, pytest
  calibration.example.json      # 캘리브레이션 스키마 예시 (커밋 대상)
  scripts/
    teleop_common.py            # 순수 함수: 각도 계산, EMA, 캘리브레이션 로드/변환
    test_teleop_common.py       # teleop_common.py 단위 테스트
    calibrate.py                # 대화형 캘리브레이션 스크립트
    run_teleop.py                # 메인 텔레옵 루프
TITI/../.gitignore               # 저장소 루트 .gitignore에 calibration.json 무시 규칙 추가
```

---

### Task 1: 폴더 스캐폴드 + requirements.txt + pytest 설치 확인

**Files:**
- Create: `TITI/arm_teleop/requirements.txt`
- Create: `TITI/arm_teleop/scripts/__init__.py` 는 만들지 않음 (다른 lab들과 동일하게 플랫 스크립트 디렉터리 유지)
- Modify: `.gitignore` (저장소 루트)

**Interfaces:**
- Consumes: 없음 (첫 태스크)
- Produces: `TITI/arm_teleop/` 디렉터리 존재, `pytest` 실행 가능 상태 — 이후 태스크들이 이 디렉터리 아래에 파일을 만든다.

- [ ] **Step 1: 디렉터리와 requirements.txt 생성**

`TITI/arm_teleop/requirements.txt`:
```
mediapipe>=0.10.0,<1.0.0
opencv-python>=4.8.0
numpy>=1.24.0
Pillow>=10.0.0
pytest>=8.0.0
```

- [ ] **Step 2: 설치**

Run: `/Users/hwangboyun/c/robotarm/.venv/bin/python3 -m pip install -r TITI/arm_teleop/requirements.txt`
Expected: 에러 없이 완료 (mediapipe/opencv/numpy/Pillow는 이미 설치돼 있어 pytest만 새로 설치됨)

- [ ] **Step 3: pytest 동작 확인**

Run: `/Users/hwangboyun/c/robotarm/.venv/bin/python3 -m pytest --version`
Expected: 버전 번호 출력 (예: `pytest 8.x.x`)

- [ ] **Step 4: .gitignore에 calibration.json 무시 규칙 추가**

저장소 루트 `.gitignore`에 다음 줄 추가:
```
TITI/arm_teleop/calibration.json
```

- [ ] **Step 5: 커밋**

```bash
git add TITI/arm_teleop/requirements.txt .gitignore
git commit -m "scaffold TITI/arm_teleop and pin its requirements"
```

---

### Task 2: 각도 계산 함수 (`teleop_common.py`) — Point3, yaw/shoulder/elbow

**Files:**
- Create: `TITI/arm_teleop/scripts/teleop_common.py`
- Test: `TITI/arm_teleop/scripts/test_teleop_common.py`

**Interfaces:**
- Consumes: 없음
- Produces:
  - `Point3(x: float, y: float, z: float)` dataclass — Task 5/6에서 mediapipe landmark를 이 타입으로 변환해 사용
  - `compute_yaw_deg(left_shoulder: Point3, right_shoulder: Point3) -> float`
  - `compute_shoulder_lift_deg(shoulder: Point3, elbow: Point3, hip: Point3) -> float`
  - `compute_elbow_flex_deg(shoulder: Point3, elbow: Point3, wrist: Point3) -> float`
  - landmark 인덱스 상수: `LEFT_SHOULDER_IDX = 11`, `RIGHT_SHOULDER_IDX = 12`, `RIGHT_ELBOW_IDX = 14`, `RIGHT_WRIST_IDX = 16`, `RIGHT_HIP_IDX = 24`

- [ ] **Step 1: 실패하는 테스트 작성**

`TITI/arm_teleop/scripts/test_teleop_common.py`:
```python
import math

from teleop_common import (
    Point3,
    compute_elbow_flex_deg,
    compute_shoulder_lift_deg,
    compute_yaw_deg,
)


def test_yaw_zero_when_facing_camera():
    # 두 어깨의 z(카메라와의 거리)가 같으면 정면 -> yaw 0
    left = Point3(x=0.3, y=0.5, z=0.0)
    right = Point3(x=0.7, y=0.5, z=0.0)
    assert compute_yaw_deg(left, right) == 0.0


def test_yaw_positive_when_right_shoulder_closer_to_camera():
    # 오른쪽 어깨가 카메라에 더 가까움(z가 더 작음/음수) -> 몸이 오른쪽으로 돌아간 것으로 판단
    left = Point3(x=0.3, y=0.5, z=0.0)
    right = Point3(x=0.6, y=0.5, z=-0.2)
    yaw = compute_yaw_deg(left, right)
    assert yaw < 0.0  # atan2(vz, vx), vz<0 -> 음수


def test_shoulder_lift_zero_when_arm_hangs_along_torso():
    hip = Point3(x=0.5, y=0.9, z=0.0)
    shoulder = Point3(x=0.5, y=0.3, z=0.0)
    elbow = Point3(x=0.5, y=0.6, z=0.0)  # shoulder에서 hip 방향(아래)으로 그대로 이어짐
    deg = compute_shoulder_lift_deg(shoulder, elbow, hip)
    assert math.isclose(deg, 0.0, abs_tol=1e-6)


def test_shoulder_lift_180_when_arm_points_up():
    hip = Point3(x=0.5, y=0.9, z=0.0)
    shoulder = Point3(x=0.5, y=0.3, z=0.0)
    elbow = Point3(x=0.5, y=0.0, z=0.0)  # shoulder에서 hip 반대 방향(위)
    deg = compute_shoulder_lift_deg(shoulder, elbow, hip)
    assert math.isclose(deg, 180.0, abs_tol=1e-6)


def test_elbow_flex_zero_when_arm_straight():
    shoulder = Point3(x=0.5, y=0.3, z=0.0)
    elbow = Point3(x=0.5, y=0.6, z=0.0)
    wrist = Point3(x=0.5, y=0.9, z=0.0)  # shoulder-elbow-wrist가 일직선
    deg = compute_elbow_flex_deg(shoulder, elbow, wrist)
    assert math.isclose(deg, 0.0, abs_tol=1e-6)


def test_elbow_flex_90_when_right_angle():
    shoulder = Point3(x=0.5, y=0.3, z=0.0)
    elbow = Point3(x=0.5, y=0.6, z=0.0)
    wrist = Point3(x=0.8, y=0.6, z=0.0)  # elbow에서 수평으로 꺾임 -> 직각
    deg = compute_elbow_flex_deg(shoulder, elbow, wrist)
    assert math.isclose(deg, 90.0, abs_tol=1e-6)
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `cd /Users/hwangboyun/c/robotarm && /Users/hwangboyun/c/robotarm/.venv/bin/python3 -m pytest TITI/arm_teleop/scripts/test_teleop_common.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'teleop_common'`

- [ ] **Step 3: `teleop_common.py` 구현**

`TITI/arm_teleop/scripts/teleop_common.py`:
```python
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Tuple

LEFT_SHOULDER_IDX = 11
RIGHT_SHOULDER_IDX = 12
RIGHT_ELBOW_IDX = 14
RIGHT_WRIST_IDX = 16
RIGHT_HIP_IDX = 24


@dataclass
class Point3:
    x: float
    y: float
    z: float


def _angle_between_2d(v1: Tuple[float, float], v2: Tuple[float, float]) -> float:
    dot = v1[0] * v2[0] + v1[1] * v2[1]
    n1 = math.hypot(*v1)
    n2 = math.hypot(*v2)
    if n1 == 0.0 or n2 == 0.0:
        return 0.0
    cos_theta = max(-1.0, min(1.0, dot / (n1 * n2)))
    return math.degrees(math.acos(cos_theta))


def compute_yaw_deg(left_shoulder: Point3, right_shoulder: Point3) -> float:
    """어깨선이 카메라 정면 대비 얼마나 회전했는지(도). 정면=0, z는 노이즈가 있어 스무딩 필요."""
    vx = right_shoulder.x - left_shoulder.x
    vz = right_shoulder.z - left_shoulder.z
    return math.degrees(math.atan2(vz, vx))


def compute_shoulder_lift_deg(shoulder: Point3, elbow: Point3, hip: Point3) -> float:
    """0=팔이 몸통(엉덩이 방향)과 같은 방향으로 늘어뜨림, 180=반대 방향(위)으로 뻗음."""
    v_up = (shoulder.x - hip.x, shoulder.y - hip.y)
    v_arm = (elbow.x - shoulder.x, elbow.y - shoulder.y)
    return _angle_between_2d(v_up, v_arm)


def compute_elbow_flex_deg(shoulder: Point3, elbow: Point3, wrist: Point3) -> float:
    """0=팔을 완전히 폄, 커질수록 팔꿈치가 굽음."""
    v1 = (shoulder.x - elbow.x, shoulder.y - elbow.y)
    v2 = (wrist.x - elbow.x, wrist.y - elbow.y)
    return 180.0 - _angle_between_2d(v1, v2)
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `cd /Users/hwangboyun/c/robotarm && /Users/hwangboyun/c/robotarm/.venv/bin/python3 -m pytest TITI/arm_teleop/scripts/test_teleop_common.py -v`
Expected: 6개 테스트 모두 PASS

- [ ] **Step 5: 커밋**

```bash
git add TITI/arm_teleop/scripts/teleop_common.py TITI/arm_teleop/scripts/test_teleop_common.py
git commit -m "add pose landmark angle calculations for arm teleop"
```

---

### Task 3: EMA 스무딩 필터

**Files:**
- Modify: `TITI/arm_teleop/scripts/teleop_common.py`
- Test: `TITI/arm_teleop/scripts/test_teleop_common.py`

**Interfaces:**
- Consumes: 없음 (Task 2와 독립)
- Produces: `EmaFilter` 클래스 — `update(new_value: float) -> float`, `reset() -> None`. Task 6(`run_teleop.py`)이 관절당 인스턴스 하나씩 사용.

- [ ] **Step 1: 실패하는 테스트 추가**

`test_teleop_common.py`에 추가:
```python
from teleop_common import EmaFilter


def test_ema_first_update_returns_input_unchanged():
    f = EmaFilter(alpha=0.3)
    assert f.update(10.0) == 10.0


def test_ema_smooths_toward_new_value():
    f = EmaFilter(alpha=0.3)
    f.update(10.0)
    result = f.update(20.0)
    assert result == 0.3 * 20.0 + 0.7 * 10.0


def test_ema_reset_clears_state():
    f = EmaFilter(alpha=0.3)
    f.update(10.0)
    f.reset()
    assert f.update(5.0) == 5.0
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `cd /Users/hwangboyun/c/robotarm && /Users/hwangboyun/c/robotarm/.venv/bin/python3 -m pytest TITI/arm_teleop/scripts/test_teleop_common.py -v -k ema`
Expected: FAIL — `ImportError: cannot import name 'EmaFilter'`

- [ ] **Step 3: `EmaFilter` 구현**

`teleop_common.py`에 추가:
```python
from typing import Optional


class EmaFilter:
    """지수이동평균. 첫 update()는 그대로 반환, 이후는 alpha 비율로 새 값을 반영."""

    def __init__(self, alpha: float = 0.3):
        self.alpha = alpha
        self._value: Optional[float] = None

    def update(self, new_value: float) -> float:
        if self._value is None:
            self._value = new_value
        else:
            self._value = self.alpha * new_value + (1 - self.alpha) * self._value
        return self._value

    def reset(self) -> None:
        self._value = None
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `cd /Users/hwangboyun/c/robotarm && /Users/hwangboyun/c/robotarm/.venv/bin/python3 -m pytest TITI/arm_teleop/scripts/test_teleop_common.py -v`
Expected: 9개 테스트 모두 PASS (기존 6개 + 신규 3개)

- [ ] **Step 5: 커밋**

```bash
git add TITI/arm_teleop/scripts/teleop_common.py TITI/arm_teleop/scripts/test_teleop_common.py
git commit -m "add EMA smoothing filter for teleop angles"
```

---

### Task 4: 캘리브레이션 (선형 매핑 + JSON 로드/저장)

**Files:**
- Modify: `TITI/arm_teleop/scripts/teleop_common.py`
- Test: `TITI/arm_teleop/scripts/test_teleop_common.py`
- Create: `TITI/arm_teleop/calibration.example.json`

**Interfaces:**
- Consumes: 없음
- Produces:
  - `MotorCalibration(human_deg_a: float, raw_a: int, human_deg_b: float, raw_b: int, yaw_zero: float = 0.0)` dataclass — `.human_deg_to_raw(human_deg: float) -> int` 메서드 포함
  - `load_calibration(path: Path) -> Dict[str, MotorCalibration]`
  - `save_calibration(path: Path, calibration: Dict[str, MotorCalibration]) -> None`
  - Task 5(`calibrate.py`)가 `save_calibration`을, Task 6(`run_teleop.py`)이 `load_calibration`과 `MotorCalibration.human_deg_to_raw`를 사용.

- [ ] **Step 1: 실패하는 테스트 추가**

`test_teleop_common.py`에 추가:
```python
import json

from teleop_common import MotorCalibration, load_calibration, save_calibration


def test_human_deg_to_raw_linear_interpolation():
    cal = MotorCalibration(human_deg_a=0.0, raw_a=2048, human_deg_b=90.0, raw_b=3000)
    assert cal.human_deg_to_raw(45.0) == round(2048 + (3000 - 2048) * 0.5)


def test_human_deg_to_raw_clamps_below_range():
    cal = MotorCalibration(human_deg_a=0.0, raw_a=2048, human_deg_b=90.0, raw_b=3000)
    assert cal.human_deg_to_raw(-100.0) == 2048


def test_human_deg_to_raw_clamps_above_range():
    cal = MotorCalibration(human_deg_a=0.0, raw_a=2048, human_deg_b=90.0, raw_b=3000)
    assert cal.human_deg_to_raw(999.0) == 3000


def test_human_deg_to_raw_works_when_raw_b_less_than_raw_a():
    # 사람 각도가 커질수록 raw가 작아지는 관절도 있을 수 있음
    cal = MotorCalibration(human_deg_a=0.0, raw_a=3000, human_deg_b=90.0, raw_b=2048)
    assert cal.human_deg_to_raw(0.0) == 3000
    assert cal.human_deg_to_raw(90.0) == 2048
    assert cal.human_deg_to_raw(999.0) == 3000  # 클램프는 min/max 기준


def test_save_and_load_calibration_roundtrip(tmp_path):
    calibration = {
        "motor_1": MotorCalibration(human_deg_a=0.0, raw_a=2048, human_deg_b=30.0, raw_b=2900, yaw_zero=1.5),
        "motor_2": MotorCalibration(human_deg_a=10.0, raw_a=1200, human_deg_b=150.0, raw_b=3400),
    }
    path = tmp_path / "calibration.json"
    save_calibration(path, calibration)

    loaded = load_calibration(path)

    assert loaded["motor_1"] == calibration["motor_1"]
    assert loaded["motor_2"] == calibration["motor_2"]
    assert json.loads(path.read_text(encoding="utf-8"))["motor_1"]["yaw_zero"] == 1.5
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `cd /Users/hwangboyun/c/robotarm && /Users/hwangboyun/c/robotarm/.venv/bin/python3 -m pytest TITI/arm_teleop/scripts/test_teleop_common.py -v -k calibration`
Expected: FAIL — `ImportError: cannot import name 'MotorCalibration'`

- [ ] **Step 3: `MotorCalibration`/`load_calibration`/`save_calibration` 구현**

`teleop_common.py`에 추가 (파일 상단 import에 `json`, `from dataclasses import asdict`, `from pathlib import Path`, `from typing import Dict` 추가):
```python
import json
from dataclasses import asdict
from pathlib import Path
from typing import Dict


@dataclass
class MotorCalibration:
    human_deg_a: float
    raw_a: int
    human_deg_b: float
    raw_b: int
    yaw_zero: float = 0.0

    def human_deg_to_raw(self, human_deg: float) -> int:
        if self.human_deg_b == self.human_deg_a:
            raise ValueError("human_deg_a and human_deg_b must differ")
        slope = (self.raw_b - self.raw_a) / (self.human_deg_b - self.human_deg_a)
        raw = self.raw_a + slope * (human_deg - self.human_deg_a)
        lo, hi = sorted((self.raw_a, self.raw_b))
        return int(round(min(max(raw, lo), hi)))


def load_calibration(path: Path) -> Dict[str, MotorCalibration]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return {motor: MotorCalibration(**values) for motor, values in data.items()}


def save_calibration(path: Path, calibration: Dict[str, MotorCalibration]) -> None:
    payload = {motor: asdict(cal) for motor, cal in calibration.items()}
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `cd /Users/hwangboyun/c/robotarm && /Users/hwangboyun/c/robotarm/.venv/bin/python3 -m pytest TITI/arm_teleop/scripts/test_teleop_common.py -v`
Expected: 14개 테스트 모두 PASS (기존 9개 + 신규 5개)

- [ ] **Step 5: 캘리브레이션 스키마 예시 파일 작성**

`TITI/arm_teleop/calibration.example.json`:
```json
{
  "motor_1": {"human_deg_a": 0.0, "raw_a": 2048, "human_deg_b": 30.0, "raw_b": 2900, "yaw_zero": 0.0},
  "motor_2": {"human_deg_a": 10.0, "raw_a": 1200, "human_deg_b": 150.0, "raw_b": 3400, "yaw_zero": 0.0},
  "motor_3": {"human_deg_a": 5.0, "raw_a": 2048, "human_deg_b": 140.0, "raw_b": 3100, "yaw_zero": 0.0}
}
```

- [ ] **Step 6: 커밋**

```bash
git add TITI/arm_teleop/scripts/teleop_common.py TITI/arm_teleop/scripts/test_teleop_common.py TITI/arm_teleop/calibration.example.json
git commit -m "add linear calibration mapping and calibration.json load/save"
```

---

### Task 5: 대화형 캘리브레이션 스크립트 (`calibrate.py`)

**Files:**
- Create: `TITI/arm_teleop/scripts/calibrate.py`

**Interfaces:**
- Consumes: `teleop_common.Point3`, `teleop_common.compute_yaw_deg`, `teleop_common.compute_shoulder_lift_deg`, `teleop_common.compute_elbow_flex_deg`, `teleop_common.MotorCalibration`, `teleop_common.save_calibration`(Task 2/4) / `클라이언트.로봇팔`(기존 `TITI/robot_arm_app/클라이언트.py`) / `hand_common.open_camera`, `resize_for_display`(기존 `TITI/hand_pose_lab/scripts/hand_common.py`, 카메라 열기 재사용) / `pose_common.create_pose_landmarker`, `detect_pose`(기존 `TITI/arm_pose_lab/scripts/pose_common.py`)
- Produces: `TITI/arm_teleop/calibration.json` 파일 (Task 6이 소비)

이 태스크는 카메라+실제 로봇 하드웨어가 있어야 실행 가능해서 자동 테스트가 없다 — **수동 검증**으로 대체한다.

- [ ] **Step 1: 스크립트 작성**

`TITI/arm_teleop/scripts/calibrate.py`:
```python
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import cv2

sys.path.append(str(Path(__file__).resolve().parent))
from teleop_common import (
    MotorCalibration,
    Point3,
    RIGHT_ELBOW_IDX,
    RIGHT_HIP_IDX,
    RIGHT_SHOULDER_IDX,
    RIGHT_WRIST_IDX,
    LEFT_SHOULDER_IDX,
    compute_elbow_flex_deg,
    compute_shoulder_lift_deg,
    compute_yaw_deg,
    save_calibration,
)

ARM_POSE_LAB_SCRIPTS = Path(__file__).resolve().parent.parent.parent / "arm_pose_lab" / "scripts"
sys.path.append(str(ARM_POSE_LAB_SCRIPTS))
from pose_common import create_pose_landmarker, detect_pose, open_camera  # noqa: E402

ROBOT_ARM_APP_DIR = Path(__file__).resolve().parent.parent.parent / "robot_arm_app"
sys.path.append(str(ROBOT_ARM_APP_DIR))
from 클라이언트 import 로봇팔  # noqa: E402

CALIBRATION_PATH = Path(__file__).resolve().parent.parent / "calibration.json"

# (motor, human_deg_reader) 순서. human_deg_reader는 pose로부터 해당 관절의 현재 사람 각도를 계산.
STEPS = ["motor_1", "motor_2", "motor_3"]


def _human_angles(pose) -> dict:
    left_shoulder = Point3(pose[LEFT_SHOULDER_IDX].x, pose[LEFT_SHOULDER_IDX].y, pose[LEFT_SHOULDER_IDX].z)
    shoulder = Point3(pose[RIGHT_SHOULDER_IDX].x, pose[RIGHT_SHOULDER_IDX].y, pose[RIGHT_SHOULDER_IDX].z)
    elbow = Point3(pose[RIGHT_ELBOW_IDX].x, pose[RIGHT_ELBOW_IDX].y, pose[RIGHT_ELBOW_IDX].z)
    wrist = Point3(pose[RIGHT_WRIST_IDX].x, pose[RIGHT_WRIST_IDX].y, pose[RIGHT_WRIST_IDX].z)
    hip = Point3(pose[RIGHT_HIP_IDX].x, pose[RIGHT_HIP_IDX].y, pose[RIGHT_HIP_IDX].z)
    return {
        "motor_1": compute_yaw_deg(left_shoulder, shoulder),
        "motor_2": compute_shoulder_lift_deg(shoulder, elbow, hip),
        "motor_3": compute_elbow_flex_deg(shoulder, elbow, wrist),
    }


def _capture_reading(cap, detector) -> dict:
    """현재 프레임에서 pose를 감지할 때까지 몇 번 재시도 후 사람 각도 dict 반환."""
    for _ in range(30):
        ok, frame = cap.read()
        if not ok or frame is None:
            continue
        frame = cv2.flip(frame, 1)
        timestamp_ms = int(time.monotonic() * 1000)
        pose = detect_pose(detector, frame, timestamp_ms)
        cv2.imshow("Calibrate", frame)
        cv2.waitKey(1)
        if pose is not None:
            return _human_angles(pose)
        time.sleep(0.05)
    raise RuntimeError("사람 pose를 감지하지 못했습니다. 카메라 앞에 서 있는지 확인하세요.")


def main() -> None:
    parser = argparse.ArgumentParser(description="motor_1~3용 2점 캘리브레이션.")
    parser.add_argument("--camera", type=int, default=0)
    args = parser.parse_args()

    arm = 로봇팔()
    arm.토크끄기()  # 캘리브레이션 중에는 손으로 직접 팔을 움직여야 하므로 토크를 끈다.

    cap = open_camera(args.camera, 1280, 720, 30)
    result: dict = {}
    try:
        with create_pose_landmarker() as detector:
            for motor in STEPS:
                input(f"\n[{motor}] 첫 번째 기준 자세로 팔을 손으로 움직이고 Enter를 누르세요...")
                deg_a = _capture_reading(cap, detector)[motor]
                raw_a = arm.위치(motor)
                print(f"  기록: human_deg={deg_a:.1f}, raw={raw_a}")

                input(f"[{motor}] 두 번째 기준 자세로 팔을 손으로 움직이고 Enter를 누르세요...")
                deg_b = _capture_reading(cap, detector)[motor]
                raw_b = arm.위치(motor)
                print(f"  기록: human_deg={deg_b:.1f}, raw={raw_b}")

                yaw_zero = 0.0
                if motor == "motor_1":
                    input("[motor_1] 이제 카메라를 정면으로 보고 서서 Enter를 누르세요 (yaw 0점 기준)...")
                    yaw_zero = _capture_reading(cap, detector)[motor]

                result[motor] = MotorCalibration(
                    human_deg_a=deg_a, raw_a=raw_a, human_deg_b=deg_b, raw_b=raw_b, yaw_zero=yaw_zero
                )
    finally:
        cap.release()
        cv2.destroyAllWindows()

    save_calibration(CALIBRATION_PATH, result)
    print(f"\n캘리브레이션 저장 완료: {CALIBRATION_PATH}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 문법 검증**

Run: `/Users/hwangboyun/c/robotarm/.venv/bin/python3 -m py_compile TITI/arm_teleop/scripts/calibrate.py`
Expected: 에러 없음

- [ ] **Step 3: 수동 실행 검증** (카메라 + 실제 로봇팔 필요)

Run: `cd /Users/hwangboyun/c/robotarm && /Users/hwangboyun/c/robotarm/.venv/bin/python3 TITI/arm_teleop/scripts/calibrate.py`
Expected: motor_1/2/3 각각 두 자세를 안내받고, 완료 후 `TITI/arm_teleop/calibration.json`이 생성되며 세 모터의 `human_deg_a/raw_a/human_deg_b/raw_b`가 실측값으로 채워져 있음.

- [ ] **Step 4: 커밋**

```bash
git add TITI/arm_teleop/scripts/calibrate.py
git commit -m "add interactive calibration script for arm teleop"
```
(참고: `calibration.json` 자체는 Task 1에서 추가한 `.gitignore` 규칙 때문에 커밋되지 않는다.)

---

### Task 6: 메인 텔레옵 루프 (`run_teleop.py`)

**Files:**
- Create: `TITI/arm_teleop/scripts/run_teleop.py`

**Interfaces:**
- Consumes: `teleop_common.Point3/EmaFilter/MotorCalibration/load_calibration`(Task 2/3/4), `teleop_common.compute_yaw_deg/compute_shoulder_lift_deg/compute_elbow_flex_deg`(Task 2), `pose_common.create_pose_landmarker/detect_pose/open_camera/draw_pose/draw_text_panel/resize_for_display`(기존 `TITI/arm_pose_lab/scripts/pose_common.py`), `클라이언트.로봇팔`(기존)
- Produces: 실행형 스크립트 (다른 태스크가 이걸 import하지 않음)

이 태스크도 카메라+로봇 하드웨어가 필요해 자동 테스트가 없다 — **수동 검증**으로 대체한다.

- [ ] **Step 1: 스크립트 작성**

`TITI/arm_teleop/scripts/run_teleop.py`:
```python
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import cv2

sys.path.append(str(Path(__file__).resolve().parent))
from teleop_common import (
    EmaFilter,
    LEFT_SHOULDER_IDX,
    Point3,
    RIGHT_ELBOW_IDX,
    RIGHT_HIP_IDX,
    RIGHT_SHOULDER_IDX,
    RIGHT_WRIST_IDX,
    compute_elbow_flex_deg,
    compute_shoulder_lift_deg,
    compute_yaw_deg,
    load_calibration,
)

ARM_POSE_LAB_SCRIPTS = Path(__file__).resolve().parent.parent.parent / "arm_pose_lab" / "scripts"
sys.path.append(str(ARM_POSE_LAB_SCRIPTS))
from pose_common import (  # noqa: E402
    create_pose_landmarker,
    detect_pose,
    draw_pose,
    draw_text_panel,
    open_camera,
    resize_for_display,
)

ROBOT_ARM_APP_DIR = Path(__file__).resolve().parent.parent.parent / "robot_arm_app"
sys.path.append(str(ROBOT_ARM_APP_DIR))
from 클라이언트 import 로봇팔  # noqa: E402

CALIBRATION_PATH = Path(__file__).resolve().parent.parent / "calibration.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="pose landmark로 motor_1~3 실시간 텔레옵.")
    parser.add_argument("--camera", type=int, default=0)
    parser.add_argument("--width", type=int, default=1280)
    parser.add_argument("--height", type=int, default=720)
    parser.add_argument("--fps", type=int, default=30)
    parser.add_argument("--display-width", type=int, default=1280)
    parser.add_argument("--alpha", type=float, default=0.3, help="EMA 스무딩 계수 (0~1, 클수록 반응 빠르고 떨림 큼)")
    parser.add_argument("--dry-run", action="store_true", help="계산된 raw 값만 출력하고 실제 모터에는 보내지 않음")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not CALIBRATION_PATH.exists():
        raise FileNotFoundError(f"캘리브레이션 파일이 없습니다: {CALIBRATION_PATH}. 먼저 calibrate.py를 실행하세요.")
    calibration = load_calibration(CALIBRATION_PATH)

    filters = {motor: EmaFilter(alpha=args.alpha) for motor in ("motor_1", "motor_2", "motor_3")}

    arm = 로봇팔()
    if not args.dry_run:
        arm.토크켜기()

    cap = open_camera(args.camera, args.width, args.height, args.fps)
    window_name = "Arm teleop (motor_1~3)"

    print("q 또는 ESC로 종료")
    try:
        with create_pose_landmarker() as detector:
            while True:
                ok, frame = cap.read()
                if not ok or frame is None:
                    print("Frame read failed.")
                    break

                frame = cv2.flip(frame, 1)
                timestamp_ms = int(time.monotonic() * 1000)
                pose = detect_pose(detector, frame, timestamp_ms)

                display = frame.copy()
                lines = ["Arm teleop"]

                if pose is not None:
                    draw_pose(display, pose)

                    left_shoulder = Point3(pose[LEFT_SHOULDER_IDX].x, pose[LEFT_SHOULDER_IDX].y, pose[LEFT_SHOULDER_IDX].z)
                    shoulder = Point3(pose[RIGHT_SHOULDER_IDX].x, pose[RIGHT_SHOULDER_IDX].y, pose[RIGHT_SHOULDER_IDX].z)
                    elbow = Point3(pose[RIGHT_ELBOW_IDX].x, pose[RIGHT_ELBOW_IDX].y, pose[RIGHT_ELBOW_IDX].z)
                    wrist = Point3(pose[RIGHT_WRIST_IDX].x, pose[RIGHT_WRIST_IDX].y, pose[RIGHT_WRIST_IDX].z)
                    hip = Point3(pose[RIGHT_HIP_IDX].x, pose[RIGHT_HIP_IDX].y, pose[RIGHT_HIP_IDX].z)

                    raw_yaw = compute_yaw_deg(left_shoulder, shoulder) - calibration["motor_1"].yaw_zero
                    raw_shoulder = compute_shoulder_lift_deg(shoulder, elbow, hip)
                    raw_elbow = compute_elbow_flex_deg(shoulder, elbow, wrist)

                    smoothed = {
                        "motor_1": filters["motor_1"].update(raw_yaw),
                        "motor_2": filters["motor_2"].update(raw_shoulder),
                        "motor_3": filters["motor_3"].update(raw_elbow),
                    }

                    targets = {
                        motor: calibration[motor].human_deg_to_raw(deg) for motor, deg in smoothed.items()
                    }

                    for motor, deg in smoothed.items():
                        lines.append(f"{motor}: {deg:.1f} deg -> raw {targets[motor]}")

                    if args.dry_run:
                        print(targets)
                    else:
                        arm.여러개이동(targets)
                else:
                    lines.append("사람이 감지되지 않음")
                    for motor in filters.values():
                        motor.reset()

                draw_text_panel(display, lines)
                cv2.imshow(window_name, resize_for_display(display, args.display_width))
                key = cv2.waitKey(1) & 0xFF
                if key in (ord("q"), 27):
                    break
    finally:
        if not args.dry_run:
            arm.토크끄기()
        cap.release()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 문법 검증**

Run: `/Users/hwangboyun/c/robotarm/.venv/bin/python3 -m py_compile TITI/arm_teleop/scripts/run_teleop.py`
Expected: 에러 없음

- [ ] **Step 3: dry-run으로 수동 검증** (카메라 필요, 로봇 불필요)

Run: `cd /Users/hwangboyun/c/robotarm && /Users/hwangboyun/c/robotarm/.venv/bin/python3 TITI/arm_teleop/scripts/run_teleop.py --dry-run`
Expected: 창이 뜨고, 팔을 움직이면 콘솔에 `{'motor_1': ..., 'motor_2': ..., 'motor_3': ...}` raw 값이 계속 출력됨. 팔을 들어올리면 motor_2 값이 캘리브레이션의 raw_b 방향으로, 팔꿈치를 굽히면 motor_3 값이 변하는지 확인. q로 정상 종료되는지 확인.

- [ ] **Step 4: 실제 로봇으로 검증** (실제 하드웨어 필요, `app.py` Flask 서버가 떠 있어야 함)

Run: `cd /Users/hwangboyun/c/robotarm && /Users/hwangboyun/c/robotarm/.venv/bin/python3 TITI/arm_teleop/scripts/run_teleop.py`
Expected: 로봇팔이 사람의 어깨/팔꿈치 움직임을 따라감. q로 종료 시 토크가 풀림(팔이 손으로 자유롭게 움직여지면 성공).

- [ ] **Step 5: 커밋**

```bash
git add TITI/arm_teleop/scripts/run_teleop.py
git commit -m "add main teleop loop mirroring motor_1~3 from pose landmarks"
```

---

## Self-Review Notes

- **Spec coverage**: yaw/shoulder/elbow 수식(Task 2), EMA 스무딩(Task 3), 2점 캘리브레이션+안전 클램프(Task 4), 폴더 구조(Task 1/전체), calibrate.py(Task 5), dry-run 포함 run_teleop.py(Task 6), 토크 끄기 finally 처리(Task 6), calibration.json gitignore(Task 1) — 스펙의 전 섹션이 태스크로 매핑됨. motor_4~6/hand landmarker 통합은 스펙에서도 범위 밖으로 명시했으므로 이 계획에 없음.
- **Placeholder scan**: 없음 — 모든 스텝에 실제 코드/명령이 포함됨.
- **Type consistency**: `Point3`, `EmaFilter`, `MotorCalibration`, `load_calibration`, `save_calibration`, `compute_yaw_deg`, `compute_shoulder_lift_deg`, `compute_elbow_flex_deg` 이름/시그니처가 Task 2~6에서 동일하게 사용됨.
