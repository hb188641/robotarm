# cube_stack — 빨강·노랑·파랑 큐브 쌓기 (MuJoCo + OpenCV, 학습 없음)

SO-101 팔이 책상에 흩어진 큐브 3개를 카메라로 찾아 한 곳에 쌓습니다.
허공의 **고정 카메라**가 큐브 지도를 만들고, **손목 카메라**가 집기 직전과 놓은 뒤를 확인합니다.
설계는 [SPEC.md](SPEC.md)에 있습니다.

## 실행 (저장소 루트에서, `.venv` 켠 상태)

```bash
mjpython simulator/cube_stack/stack_sim.py
```

- 메인 화면은 3인칭 시점이고, 오른쪽 위는 고정 카메라(찾은 큐브 윤곽), 그 아래는 손목 카메라입니다.
- 한 번 쌓으면 심판 결과를 터미널에 찍고, 새 무작위 배치로 계속 반복합니다.
- `[` / `]`로 카메라를 바꾸고, Tab을 누르면 MuJoCo 메뉴가 나옵니다.

옵션:

| 옵션 | 뜻 |
| --- | --- |
| `--once` | 한 번만 쌓고 멈춤 |
| `--seed N` | 배치를 재현 |
| `--order blue,red,yellow` | 쌓는 순서 (아래→위) |
| `--speed 2` | 재생 속도 |
| `--headless --sheet out.png` | 창 없이 단계별 장면 PNG |
| `--headless --trials 50 --quiet` | 성공률 측정 |

## 테스트

```bash
python -m pytest simulator/cube_stack/tests
```
