#!/bin/zsh
# Finder에서 더블클릭: 브라우저용 SO-101 시뮬레이터를 켜고 브라우저를 엽니다.
# 같은 네트워크의 다른 컴퓨터도 터미널에 표시되는 주소로 접속할 수 있습니다 (--lan).
# 다른 네트워크에서 접속하려면 페이지 위쪽 [🌐 인터넷 공유 켜기]를 누르세요 (Cloudflare 터널, 접속 키 보호).
# 끝낼 때는 이 터미널 창에서 Ctrl+C를 누르거나 창을 닫으세요.
cd "$(dirname "$0")/.." || exit 1
if [ -x .venv/bin/python ]; then PY=.venv/bin/python; else PY=python3; fi
"$PY" -c "import mujoco, flask, cv2" 2>/dev/null || "$PY" -m pip install -r simulator/requirements.txt
exec "$PY" simulator/web_sim.py --lan --open
