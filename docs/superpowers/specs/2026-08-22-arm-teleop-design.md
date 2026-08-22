# Pose Landmarker 기반 로봇팔 전체(motor_1~3) 텔레옵 설계

## 배경

`TITI/arm_pose_lab`은 어깨/팔꿈치/손목 landmark로 "펴짐/접힘" 이진 분류만 하고, motor_3 하나만 두 위치 중 하나로 움직인다. 이번 작업은 그 대신 **사람의 팔 자세를 실시간으로 로봇팔에 연속적으로 미러링**하는 새 서브시스템을 만드는 것이다. 1단계는 motor_1(base yaw), motor_2(shoulder_lift), motor_3(elbow_flex) 세 관절만 다루고, 손목/그리퍼(motor_4~6)는 이후 단계에서 확장한다.

## 대상 하드웨어

이 로봇팔은 HuggingFace LeRobot의 **SO-101/SO-100 팔로워** (`config_so_follower.py`에 `so101_follower`/`so100_follower`로 등록, STS3215 Feetech 서보 6개)다. 코드상 모터 이름은 `motor_1~6`이지만 실제 역할은 SO-101 표준과 동일하다.

| 모터 | 역할 | 비고 |
|---|---|---|
| motor_1 | shoulder_pan (베이스 회전) | 독립적 |
| motor_2 | shoulder_lift (어깨) | 체인 시작점 |
| motor_3 | elbow_flex (팔꿈치) | 상완 기준 **상대각** |
| motor_4 | wrist_flex | 1단계 범위 아님 |
| motor_5 | wrist_roll | 1단계 범위 아님 |
| motor_6 | gripper | 1단계 범위 아님 |

기존 `TITI/robot_arm_app/클라이언트.py`의 `로봇팔` 클래스(`여러개이동`, `토크켜기`, `토크끄기`, `위치목록`)를 그대로 재사용한다. raw tick 범위는 0~4095, `CENTER=2048`이 전기적 중앙값이지만 이것이 실제 물리적 "0도"와 일치한다는 보장은 없다 — 그래서 캘리브레이션이 필요하다(아래 참고).

## 계산 방식 — 직접 좌표 계산 (AI 회귀 아님)

연속적인 관절 각도 추정은 분류 문제가 아니라 벡터 기하학 문제이므로, `hand_pose_lab`/`arm_pose_lab`처럼 신경망을 학습시키지 않고 **landmark 벡터의 각도를 직접 계산**한다. 학습 데이터를 만들려면 결국 이 기하 계산으로 정답 라벨을 만들어야 해서, ML 단계를 추가해도 이점이 없다.

### motor_1 (base yaw)

MediaPipe Pose landmark: 왼쪽 어깨(11), 오른쪽 어깨(12). `x, z`만 사용 (y는 회전과 무관).

```
v = (vx, vz) = (오른쪽어깨.x - 왼쪽어깨.x, 오른쪽어깨.z - 왼쪽어깨.z)
yaw_deg = degrees(atan2(vz, vx))
corrected = yaw_deg - yaw_zero   # 캘리브레이션 때 측정한 "정면" 오프셋
```

### motor_2 (shoulder_lift)

landmark: 어깨(12), 팔꿈치(14), 엉덩이(24). `x, y`만 사용 (z는 노이즈가 커서 배제).

```
v_up = 어깨 - 엉덩이
v_arm = 팔꿈치 - 어깨
theta2_deg = degrees(arccos((v_up · v_arm) / (|v_up| |v_arm|)))
```
0° = 팔이 몸통과 같은 방향(늘어뜨림), 커질수록 팔이 위로.

### motor_3 (elbow_flex, 상완 기준 상대각)

landmark: 어깨(12), 팔꿈치(14), 손목(16).

```
v1 = 어깨 - 팔꿈치
v2 = 손목 - 팔꿈치
elbow_deg = 180 - degrees(arccos((v1 · v2) / (|v1| |v2|)))
```
0° = 완전히 폄, 커질수록 굽음.

### 공통: 스무딩

MediaPipe의 `z`는 `x, y`보다 노이즈가 훨씬 크고, `x, y` 기반 각도도 프레임 간 흔들림이 있다. 세 각도(theta1/2/3) 모두 지수이동평균(EMA, `alpha≈0.3` 시작값, 실측 후 조정)으로 필터링한다.

## 사람 각도 → 로봇 raw tick 변환: 2점 캘리브레이션

`index.html`의 `CENTER=2048=0°`, `theta2=0→수직위` 같은 변환은 UI 시각화용으로 만든 임의 값이라 실제 서보 물리적 위치와 일치한다는 보장이 없다. 하드코딩된 변환식 대신, 모터마다 사람이 취할 수 있는 두 개의 기준 자세(예: 완전히 폄 / 최대로 굽힘)에서

1. 팔을 그 자세로 물리적으로 이동시켜 raw tick을 기록하고
2. 같은 자세에서 사람이 취한 pose landmark 각도를 기록해서

`raw = a * human_deg + b` 선형보간 계수 `(a, b)`를 모터별로 구해 `calibration.json`에 저장한다. 이 두 기준점이 안전 범위(raw_min, raw_max)도 자연스럽게 정의한다.

`calibration.json` 스키마 (motor_1~3만):
```json
{
  "motor_1": {"human_deg_a": 0.0, "raw_a": 2048, "human_deg_b": 30.0, "raw_b": 2900, "yaw_zero": 0.0},
  "motor_2": {"human_deg_a": 10.0, "raw_a": 1200, "human_deg_b": 150.0, "raw_b": 3400},
  "motor_3": {"human_deg_a": 5.0, "raw_a": 2048, "human_deg_b": 140.0, "raw_b": 3100}
}
```
실측값은 사람/설치 환경마다 다르므로 실제 값이 담긴 파일은 `.gitignore`, 저장소에는 스키마 예시만 남긴다.

## 폴더 구조

```
TITI/arm_teleop/
  scripts/
    teleop_common.py   # landmark→각도 계산 함수, EMA 스무딩, calibration.json 로드/적용
    calibrate.py        # 대화형 캘리브레이션: 두 자세 안내 → raw/사람각도 기록 → calibration.json 저장
    run_teleop.py        # 메인 루프
  calibration.example.json   # 스키마 예시 (커밋 대상)
  requirements.txt     # mediapipe>=0.10.0,<1.0.0 / opencv-python / numpy / Pillow
```
`calibration.json`(실측값)은 `.gitignore`에 추가.

## 데이터 흐름

카메라 프레임 → `PoseLandmarker.detect_for_video` → 어깨/팔꿈치/손목/엉덩이 landmark 추출 → 위 수식으로 theta1/2/3 계산 → EMA 스무딩 → calibration.json으로 raw tick 변환 → `[raw_min, raw_max]` 클램프 → `팔.여러개이동({"motor_1":..., "motor_2":..., "motor_3":...})` 한 번에 전송(개별 모터 호출보다 네트워크 왕복 감소).

## 에러 처리

- 카메라 프레임 읽기 실패: 루프 종료(기존 스크립트들과 동일 패턴)
- pose landmark 미검출: 마지막으로 계산된 각도를 유지, 새 모터 명령을 보내지 않음
- 종료(q/ESC) 또는 예외 발생: `finally` 블록에서 반드시 `팔.토크끄기()` 호출 (지난 세션에서 발견된 `토크해제()` 오타 버그 재발 방지)

## 테스트 계획

- `run_teleop.py --dry-run`: 실제 모터로 전송하지 않고 계산된 raw 값만 콘솔에 출력. 캘리브레이션 값 검증 및 각도 계산 로직 확인용.
- dry-run으로 세 관절 각도가 사람 동작과 방향이 맞게 움직이는지 확인 후, 실제 전송 활성화.
- 이후 자잘한 오류는 사용 중 발견하며 수정 (사용자 요청에 따라 반복 개선).

## 다음 단계 (이번 스펙 범위 밖)

motor_4(wrist_flex)/motor_5(wrist_roll)는 pose landmark의 손목만으로는 방향을 못 잡아서 `hand_pose_lab`의 손 landmark까지 동시에 필요 — motor_1~3이 안정화된 뒤 별도로 설계.
