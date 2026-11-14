# simulator

실제 SO-101 로봇팔의 동작을 MuJoCo로 Mac에 바로 보여 주는 작업 공간입니다.
기존 `TITI/` 코드는 수정하지 않고, `robot_arm_app`의 REST API(`:6000`)와
`voice_motor`의 설정 파일(`arm.json`, `poses.json`)만 읽습니다.

## 설치

```bash
source .venv/bin/activate
pip install -r simulator/requirements.txt
```

## 브라우저에서 쓰기 (명령어 없이)

Finder에서 **`simulator/시뮬레이터 열기.command`를 더블클릭**하면 터미널 창이 뜨고 브라우저가
`http://localhost:8780`을 엽니다. 끝낼 때는 그 터미널 창을 닫거나 Ctrl+C를 누릅니다.
(처음 한 번 macOS가 확인을 물으면 ‘열기’를 누르세요.)

| 화면 | 하는 일 |
| --- | --- |
| 1인칭 / 3인칭 | 손목 카메라와 3인칭 화면. 아래 작은 화면을 누르면 크게 바뀝니다 |
| 검출기가 본 화면 | 마지막으로 큐브를 찾은 장면, 초록 윤곽이 찾은 큐브 |
| 책상 지도 | 위에서 본 책상. **클릭·드래그로 큐브를 놓고**, 휠이나 막대로 돌립니다. 초록 띠가 잘 닿는 범위 |
| 버튼 | 집기 시작 · 내려놓기 · 처음 자세 · 정지 · 처음 상태로 · 무작위 위치 |
| 자동 반복 / 속도 | 집기 → 내려놓기 → 새 위치를 계속 반복, 0.5×~4× 속도 |

### 다른 컴퓨터에서 접속

더블클릭 실행은 같은 Wi-Fi·공유기를 쓰는 다른 컴퓨터·태블릿·폰에서도 열 수 있게 켜집니다(`--lan`).
접속 주소는 터미널 창과 페이지 맨 위 노란 띠에 나옵니다(예: `http://192.168.0.205:8780`,
`http://<맥 이름>.local:8780`). [복사] 버튼으로 주소를 복사해 보내면 됩니다.

- **처음 한 번:** macOS가 “Python이 들어오는 네트워크 연결을 허용하겠습니까?”라고 물으면 **[허용]**을 누르세요.
  거부했다면 시스템 설정 → 네트워크 → 방화벽 → 옵션에서 Python을 허용으로 바꿉니다.
- 접속한 모든 화면이 **같은 시뮬레이터 하나를 함께** 보고 조작합니다(2명 이상이면 위에 👀 인원 표시).
- 비밀번호가 없어서 주소를 아는 같은 네트워크의 누구나 조작할 수 있습니다. 시뮬레이터만 움직이고 실제 팔과는
  연결되지 않지만, 카페·학교처럼 공용 네트워크에서는 `python simulator/web_sim.py --open`(내 컴퓨터만)으로 켜세요.
- 주소가 열리지 않으면: 두 기기가 같은 네트워크인지, 맥 터미널 창이 켜져 있는지 확인하세요.
  게스트 Wi-Fi는 기기끼리 연결을 막아 두는 경우가 많습니다.

### 다른 네트워크(인터넷 어디서나)에서 접속 — 포트포워딩 없이

이 맥의 브라우저에서 페이지 위쪽 **[🌐 인터넷 공유 켜기]**를 누르면 5~15초 뒤
`https://<무작위 단어>.trycloudflare.com/?key=<접속 키>` 링크가 나옵니다. [복사]해서 보내면
LTE·다른 집·학교 등 어느 네트워크에서든 열립니다. 터미널로 켤 때는 `python simulator/web_sim.py --share`.

- **원리:** `cloudflared`(Cloudflare 터널, 이미 설치됨)가 이 맥에서 Cloudflare로 *나가는* 연결을 맺고,
  Cloudflare가 공개 주소로 온 접속을 그 연결로 넘겨줍니다. 그래서 공유기 설정·포트포워딩·계정이 필요 없고,
  macOS 방화벽 허용도 필요 없습니다.
- **보안:** 공개 주소는 누구나 열 수 있으므로 **접속 키가 있어야만** 들어옵니다(링크에 포함, 이후 쿠키로 기억).
  키 없이 열면 키 입력 화면이 나옵니다. **[공유 끄기]**를 누르면 주소와 키가 모두 사라지고, 다시 켜면 새 주소·새 키가 생깁니다.
- 공유 켜기/끄기는 **시뮬레이터를 켠 맥에서만** 할 수 있습니다(원격 접속자는 못 바꿈).
- 인터넷으로 볼 때는 데이터를 아끼려고 영상이 초당 10장(작은 화면 3장)으로 줄어듭니다.
- 무료 임시 터널이라 켤 때마다 주소가 바뀌고, 맥이 잠자기에 들어가거나 터미널 창을 닫으면 끊깁니다.
  고정 주소가 필요하면 Cloudflare 계정으로 이름 있는 터널을 만들거나 Tailscale을 쓰는 방법이 있습니다.

영상이 안 나오면 주소 끝에 `?still=1`을 붙이면(`http://localhost:8780/?still=1`) 0.5초마다
정지 화면으로 바꿔 보여 줍니다. 터미널로 직접 켜려면 `python simulator/web_sim.py --open`.

## 실행 (저장소 루트에서)

macOS에서는 MuJoCo 창을 띄울 때 `python` 대신 `mjpython`을 써야 합니다.

```bash
# 1) 실제 팔 미러: app.py가 떠 있는 상태에서 (읽기 전용, 명령을 보내지 않음)
mjpython simulator/mirror.py
mjpython simulator/mirror.py --base-url http://192.168.0.10:6000 --hz 10

# 2) 하드웨어 없이: poses.json의 자세를 차례로 재생
mjpython simulator/mirror.py --demo

# 3) 창 없이 한 장면만 PNG로 저장 (python으로도 실행 가능)
python simulator/mirror.py --demo --snapshot frame.png
```

- 왼쪽 위에 연결 상태(`LIVE` / `OFFLINE` / `DEMO`)가, 왼쪽 아래에 모터별 raw tick이 표시됩니다.
- 빨간 점은 `voice_motor/kinematics.py`가 쓰는 그립 지점(손끝)입니다.
- 서버가 끊기면 마지막 자세를 유지하고, 다시 연결되면 이어서 따라갑니다.
- `/api/state` 한 번은 서보 버스 읽기 한 번입니다. pick처럼 명령을 보내는 작업과 버스를
  공유하므로 기본 15 Hz로 읽고, 화면에서는 그 사이를 부드럽게 보간합니다.

## 1인칭 큐브 집기 (물리 시뮬레이션)

손목 카메라(로봇의 1인칭 시점)로 빨간 큐브를 찾아 잡고 들어 올립니다. 하드웨어는 필요 없습니다.

```bash
mjpython simulator/pick_sim.py                              # 무한 반복: 집기 → 내려놓기 → 새 큐브
mjpython simulator/pick_sim.py --once --cube 0.22 0.05 20   # 큐브 위치 지정 (m, m, 도)
mjpython simulator/pick_sim.py --speed 2 --seed 3           # 2배속, 큐브 위치 재현
python   simulator/pick_sim.py --headless --sheet pick.png  # 창 없이 단계별 장면 저장
```

- 메인 화면은 손목 카메라입니다. 오른쪽 위 인셋은 검출기가 본 화면(초록 윤곽 = 찾은 큐브),
  오른쪽 아래 인셋은 3인칭 화면입니다. 창에서 `[` `]`로 카메라를 바꾸고 `Esc`로 자유 시점이 됩니다.
- 순서: **scan**(5방향을 내려다보며 찾기) → **hover**(위로 가서 가까이서 다시 보고 보정) →
  **descend**(열린 집게를 내림) → **grip**(닫기, 끝까지 닫히면 놓친 것) → **lift**(8 cm 들기, 따라왔는지 확인).
- 검출은 `voice_motor/vision.py`의 HSV 마스크와 큐브 모양 판정을 그대로 쓰고, 자세는
  `voice_motor/kinematics.solve`로 구합니다. 그래서 명령은 실제 팔과 같은 raw tick입니다.
- 손목 카메라 위치(`sim/scene.py`의 `CAM_POS`)와 큐브 크기 25 mm는 가정값입니다.
  실제 카메라를 달면 이 값을 실측으로 바꾸면 됩니다.
- 집게 메시는 볼록 껍질로 충돌하면 손가락 사이가 막히므로, 손가락 끝에 박스 패드를 달아
  충돌을 대신합니다(파란 반투명, 창에서 `3`으로 표시). 무작위 위치 40회 집기 모두 성공했습니다.

## 좌표 규칙

| 모터 | MuJoCo 관절 | 변환 |
| --- | --- | --- |
| motor_1~5 | shoulder_pan, shoulder_lift, elbow_flex, wrist_flex, wrist_roll | `q = (tick − 2048) · 2π/4096` (URDF 0점·방향과 동일) |
| motor_6 | gripper | 실측 닫힘 1634 → −0.17 rad, 열림 2793 → 1.75 rad 선형 변환 |

`kinematics.fk()`와 MuJoCo 손끝 자세가 300개 무작위 자세에서 0.1 mm 이내로 일치하는지
테스트합니다. 모델의 CAD 관절 범위가 실측(`arm.json`)보다 좁은 관절(motor_1 등)은
실측 범위까지 넓혀서 불러옵니다.

## 구성

| 경로 | 내용 |
| --- | --- |
| `mirror.py` | 미러 뷰어 실행 파일 |
| `sim/arm.py` | 모델 빌드(MjSpec), tick ↔ 관절각 변환 |
| `sim/sources.py` | `HttpSource`(/api/state 폴링), `DemoSource`(포즈 재생) |
| `시뮬레이터 열기.command` | 더블클릭 실행 파일 (브라우저 패널) |
| `web_sim.py`, `web/` | 브라우저 패널: Flask 서버, 화면(HTML·CSS·JS) |
| `sim/world.py` | 시뮬레이션 스레드: 명령 처리, 영상·상태 공개 |
| `sim/share.py` | 인터넷 공유: Cloudflare 임시 터널 실행, 접속 키 검사 |
| `pick_sim.py` | 1인칭 큐브 집기 실행 파일 (MuJoCo 창) |
| `sim/scene.py` | 집기 장면: 손목 카메라, 큐브, 손가락 패드 |
| `sim/physics_arm.py` | 물리 팔: tick 목표를 속도 제한 궤적으로 따라감 |
| `sim/eye.py` | 손목 카메라 렌더링, 큐브 검출, 화면 → 책상 좌표 변환 |
| `sim/picker.py` | 찾기 → 다가가기 → 잡기 → 들기 상태 흐름 |
| `models/so101/` | TheRobotStudio SO-101 MJCF·메시 원본 (`SOURCE.md` 참고) |
| `tests/` | `python -m pytest simulator/tests` |
| `docs/mujoco/` | MuJoCo 문서 사본, `tools/html2md.py` 변환기 |

## 다음 단계

1. 프록시 모드: 같은 REST API를 `:6001`로 열어 명령은 실제 팔로 전달하고 목표 자세를 고스트로 표시
2. 디지털 트윈: 하드웨어 없이 MuJoCo 물리로 `/api/state`·목표 이동을 흉내 냄
3. 1인칭 집기를 실제 팔에 연결: 손목 카메라 장착 후 같은 흐름을 REST API로 실행
