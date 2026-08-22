# robotarm

MediaPipe 기반 손/팔 포즈 인식과 Feetech 서보 모터로 구동되는 6축 로봇팔 제어 프로젝트입니다.

## 구성

- `TITI/robot_arm_app` — LeRobot `FeetechMotorsBus`를 REST API로 감싼 Flask 서버. 브라우저(`templates/index.html`)에서 모터 각도를 조작할 수 있습니다.
- `TITI/hand_pose_lab` — MediaPipe로 손 포즈 데이터를 수집·학습·추론하는 스크립트 모음.
- `TITI/arm_pose_lab` — MediaPipe로 팔 포즈 데이터를 수집·학습·추론하는 스크립트 모음.
- `mediapipe_hand.py` — MediaPipe Hands 데모 스크립트.

## 설치

Python 3.12 기준 가상환경을 만들고 각 모듈의 의존성을 설치합니다.

```bash
python3.12 -m venv .venv
source .venv/bin/activate

pip install -r TITI/hand_pose_lab/requirements.txt
pip install -r TITI/arm_pose_lab/requirements.txt
pip install -r TITI/robot_arm_app/requirements.txt
```

## robot_arm_app 실행

`TITI/robot_arm_app/app.py`의 `PORT` 값을 로봇팔이 연결된 시리얼 포트로 맞춘 뒤 실행합니다.

```bash
python TITI/robot_arm_app/app.py
```

서버가 뜨면 `http://localhost:6000`에서 모터를 제어하고, `GET /api/state`로 현재 모터 위치를 확인할 수 있습니다.
