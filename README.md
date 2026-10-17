# robotarm

MediaPipe 손·팔 인식과 Feetech 서보 모터를 이용한 6축 로봇팔 제어 프로젝트입니다.
Python 3.12를 기준으로 합니다. 아래 명령은 저장소 루트에서 실행합니다.

## 설치

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

개발·테스트 도구까지 설치하려면 `pip install -r requirements-dev.txt`를 사용합니다.
개별 기능만 설치할 때는 각 폴더의 `requirements.txt`를 사용할 수 있습니다.
카메라 미리보기에는 GUI를 지원하는 OpenCV와 운영체제의 카메라 접근 권한이 필요합니다.

## 구성

| 경로 | 용도 |
| --- | --- |
| `TITI/robot_arm_app/` | Flask REST 서버, 브라우저 제어 화면, Python 클라이언트 |
| `TITI/hand_pose_lab/` | 손 펴짐·접힘 데이터 수집, 학습, 그리퍼 제어 |
| `TITI/arm_pose_lab/` | 오른팔 펴짐·접힘 데이터 수집, 학습, motor_3 제어 |
| `TITI/arm_teleop/` | 관절 각도 직접 계산, 캘리브레이션, motor_1~3 연속 제어 |
| `TITI/common/` | 카메라·화면 표시, CSV·JSON, 장치 선택, 학습 공통 코드 |
| `tests/` | 하드웨어 없이 실행하는 포즈 워크플로 회귀 테스트 |
| `docs/superpowers/` | 기존 텔레옵 설계·구현 기록 |

각 lab의 `data/`와 `models/`, 루트의 두 `.task` 파일은 실제 수집·학습·인식에 사용합니다.
기존 데이터 경로, 체크포인트 형식, 스크립트 실행 경로를 유지합니다.

## REST 서버와 브라우저 제어

`TITI/robot_arm_app/app.py`의 `PORT`를 실제 시리얼 포트로 수정합니다.
서버는 모터 ID 1~6, `sts3215` 모델을 기본으로 사용합니다.

```bash
python TITI/robot_arm_app/app.py
```

브라우저에서 <http://localhost:6000>을 열면 조인트 드래그 또는 슬라이더로 제어합니다.
서버 실행 시 토크가 켜지며, 정상 종료 시 토크를 해제하고 연결을 닫습니다.

| API | 동작 |
| --- | --- |
| `GET /api/state` | 전체 모터 현재 위치 조회 |
| `POST /api/motor/<motor_name>/goal` | `{"position": 2048}` 형식으로 단일 모터 이동 |
| `POST /api/motors/goal` | `{"motor_2": 2500, "motor_3": 1600}` 형식으로 동시 이동 |
| `POST /api/torque` | `{"enabled": true}` 또는 `false`로 토크 제어 |

Python 클라이언트는 `TITI/robot_arm_app/클라이언트.py`의 `로봇팔` 클래스입니다.
같은 폴더의 `예시사용.py`에서 사용법을 확인할 수 있습니다. 클라이언트 기본 주소는
`http://localhost:6000`이며, 다른 서버 주소는 `로봇팔(base_url="...")`로 지정합니다.

## 손·팔 포즈 수집과 학습

손 포즈:

```bash
python TITI/hand_pose_lab/scripts/collect_hand_pose_dataset.py --append
python TITI/hand_pose_lab/scripts/train_hand_pose_classifier.py
python TITI/hand_pose_lab/scripts/run_hand_pose_classifier.py
```

팔 포즈:

```bash
python TITI/arm_pose_lab/scripts/collect_arm_pose_dataset.py --append
python TITI/arm_pose_lab/scripts/train_arm_pose_classifier.py
python TITI/arm_pose_lab/scripts/run_arm_pose_classifier.py
```

수집 중 `o`는 펴짐, `f`는 접힘을 기록하고 `q` 또는 ESC로 종료합니다.
**수집 명령에서 `--append`를 생략하면 지정한 데이터셋 폴더를 지우고 새로 수집합니다.**
학습은 기본 모델 파일을 덮어씁니다. 실험 결과를 따로 보관하려면 `--model-out`과
`--summary-out`으로 다른 출력 경로를 지정합니다.

추론 스크립트는 실행 중인 REST 서버를 통해 실제 로봇을 제어합니다.
단순 손 랜드마크 표시만 보려면 `python mediapipe_hand.py`를 실행합니다.
lab 명령의 `--help`로 카메라 번호, 모델 경로, 학습 옵션을 확인할 수 있습니다.

## 연속 팔 텔레옵

먼저 REST 서버를 실행합니다. 캘리브레이션은 토크를 해제한 상태에서 사람과 로봇의
두 기준 자세를 기록하며, 결과를 `TITI/arm_teleop/calibration.json`에 저장합니다.

```bash
python TITI/arm_teleop/scripts/calibrate.py
python TITI/arm_teleop/scripts/run_teleop.py --dry-run
python TITI/arm_teleop/scripts/run_teleop.py
```

`--dry-run`은 카메라·캘리브레이션을 사용해 목표 위치를 출력하며 모터 명령은 보내지 않습니다.
`--alpha`는 스무딩, `--max-raw-delta`는 프레임당 위치 변화 제한을 조절합니다.
`calibration.example.json`은 형식 예제이며 실제 로봇의 캘리브레이션 결과를 대신하지 않습니다.

## 독립 실험·진단 도구

기존 사용 경로를 유지하기 위해 아래 파일은 이동하지 않았습니다. REST 서버와 별개로
시리얼 포트에 직접 연결하므로 각 파일의 `PORT`와 모터 ID를 확인한 뒤 단독 실행합니다.

| 스크립트 | 용도 |
| --- | --- |
| `TITI/read_all_positions.py` | 6개 모터 위치 연속 조회 |
| `TITI/disable_torque.py` | 지정한 단일 모터의 토크 해제 |
| `TITI/arrow_key_control.py` | Windows 방향키·G 키 기반 직접 제어 |
| `TITI/motorControl.py` | 구형 시리얼 패킷 기반 단일 모터 실험 |
| `TITI/motorControl_lerobot.py` | LeRobot 기반 단일 모터 실험 |

방향키 도구의 추가 의존성은 `pip install -r requirements-tools.txt`로 설치합니다.
실험 도구에는 이동을 반복하는 무한 루프가 있으므로 일반 앱 실행 진입점으로 사용하지 않습니다.
각 스크립트는 직접 실행할 때 연결하며, import만으로 카메라나 모터를 열지 않습니다.

`student-red-cube-lab`은 Git에 외부 저장소 커밋 참조로 등록되어 있고 현재 체크아웃에는
소스가 없습니다. 이 프로젝트의 Python 실행 경로와는 연결되어 있지 않습니다.

## 검증

```bash
python -m pytest -q
ruff check --select E9,F63,F7,F82 TITI tests mediapipe_hand.py
```

테스트는 텔레옵 계산, 수집 CSV와 학습 입력의 호환성, 기존 체크포인트 로딩,
분류기 import 시 모터 요청이 발생하지 않는지 확인합니다. 실제 카메라 인식과 모터 동작은
연결된 하드웨어에서 별도로 확인해야 합니다.
