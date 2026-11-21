// The stack page (/stack/): state → UI, the table map with three cubes,
// order chips, grading. Server talk, video and sharing live in common.js.
"use strict";

const STAGES = ["calibrate", "look", "pick", "place", "check", "final"];
const STAGE_NAME = {
  idle: "대기", calibrate: "집게 보정", look: "고정 카메라로 찾기", pick: "집는 중",
  place: "올리는 중", check: "탑 확인", retry: "다시 시도", final: "최종 확인",
  done: "성공", fail: "실패", home: "처음 자세로",
};
const COLOR = { red: "빨강", yellow: "노랑", blue: "파랑" };
const CUBE_VAR = { red: "--red", yellow: "--yellow", blue: "--blue" };

let drag = null; // {color, x, y, dx, dy} while moving a cube
let lastStage = -1;

// ---------- state → UI ----------
function apply(s) {
  state = s;
  $("stacks").textContent = `성공 ${s.stacks.ok} / ${s.stacks.total}`;
  if (typeof s.viewers === "number") {
    $("viewers").hidden = s.viewers < 2;
    $("viewers").textContent = `👀 ${s.viewers}명 보는 중`;
  }
  const lag = videoDelay();
  $("sim-time").textContent = `${s.time.toFixed(1)} s` +
    (lag === null ? "" : ` · 영상 ${lag.toFixed(1)}초 늦게`);
  $("stage-badge").textContent = STAGE_NAME[s.stage] || s.stage;

  const status = $("status");
  status.textContent = s.status || "준비됐습니다. ‘쌓기 시작’을 누르세요.";
  status.className = "status" + (s.stage === "done" ? " ok" : s.stage === "fail" ? " bad" : "");

  const pipe = $("pipeline");
  const now = STAGES.indexOf(s.stage);
  const finished = s.stage === "done";
  pipe.classList.toggle("failed", s.stage === "fail");
  [...pipe.children].forEach((li, i) => {
    li.classList.toggle("now", i === now || (s.stage === "fail" && i === lastStage));
    li.classList.toggle("done", finished || (now >= 0 && i < now));
  });
  if (now >= 0) lastStage = now;

  $("btn-start").disabled = s.busy;
  $("btn-home").disabled = s.busy;
  $("btn-stop").disabled = !s.busy && !s.auto;
  $("btn-random").disabled = s.busy;
  $("auto").checked = s.auto;
  $("map").classList.toggle("busy", s.busy);
  document.querySelectorAll("#speed button").forEach((b) => {
    b.classList.toggle("active", Number(b.dataset.speed) === s.speed);
  });
  renderOrder(s.order, s.busy);
  renderGrade(s.grade, s.stacks);
  renderTicks(s.ticks);
  renderLog(s.log);
}

let lastOrderKey = "";
function renderOrder(order, busy) {
  const key = order.join() + busy;
  if (key === lastOrderKey) return;
  lastOrderKey = key;
  const box = $("order");
  const parts = ['<span class="order-end">아래</span>'];
  order.forEach((c, i) => {
    if (i) parts.push(`<button class="swap" data-i="${i}" ${busy ? "disabled" : ""} title="두 큐브 순서 바꾸기">⇄</button>`);
    parts.push(`<span class="chip"><i class="sw cube-${c}"></i>${COLOR[c]}</span>`);
  });
  parts.push('<span class="order-end">위</span>');
  box.innerHTML = parts.join("");
  box.querySelectorAll(".swap").forEach((b) => {
    b.onclick = () => {
      const i = Number(b.dataset.i);
      const next = state.order.slice();
      [next[i - 1], next[i]] = [next[i], next[i - 1]];
      post("/api/order", { order: next });
    };
  });
}

let lastGradeKey = "";
function renderGrade(g, stacks) {
  const key = JSON.stringify([g, stacks]);
  if (key === lastGradeKey) return;
  lastGradeKey = key;
  if (!g) return;
  const right = g.stacked === (g.claim === "stacked");
  const rows = g.layers.map((L, i) => `<tr class="${L.ok ? "" : "bad"}">
      <td>${i + 1}층</td><td><i class="sw cube-${L.color}"></i>${COLOR[L.color]}</td>
      <td class="mono">${i ? L.offset_mm.toFixed(1) + " mm" : "바닥"}</td>
      <td class="mono">${i ? L.yaw_deg.toFixed(0) + "°" : ""}</td>
      <td class="mono">${L.z_mm.toFixed(0)} mm</td>
      <td>${L.ok ? "✓" : "✗"}</td></tr>`).reverse().join("");
  $("grade").innerHTML = `
    <p class="verdict ${g.stacked ? "ok" : "bad"}">${g.stacked ? "쌓였습니다" : "안 쌓였습니다"}
      <small>· 로봇 판단: ${g.claim === "stacked" ? "성공" : "실패"} (${right ? "맞음" : "틀림"})</small></p>
    <table><thead><tr><th>층</th><th>색</th><th>아래와 차이</th><th>각도</th><th>높이</th><th></th></tr></thead>
    <tbody>${rows}</tbody></table>
    <p class="hint">누적: 성공 ${stacks.ok} / ${stacks.total} · 판단 틀림 ${stacks.misjudged}회 · 기준: 차이 ≤ 6 mm, 각도 ≤ 10°</p>`;
}

// ---------- video ----------
let mainView = "overview";
function setMain(view) {
  mainView = view;
  show($("main-view"), view);
  document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("active", t.dataset.view === view));
}
function reloadStreams() {
  setMain(mainView);
  show($("top-seen"), "top_seen", true);
  show($("wrist-seen"), "wrist_seen", true);
}
document.querySelectorAll(".tab").forEach((t) => (t.onclick = () => setMain(t.dataset.view)));
document.querySelectorAll(".video-card img").forEach((img) => {
  img.onerror = () => setTimeout(() => online && img.src && (img.src = freshen(img.src)), 1000);
});

// ---------- buttons ----------
$("btn-start").onclick = () => post("/api/start");
$("btn-home").onclick = () => post("/api/home");
$("btn-stop").onclick = () => post("/api/stop");
$("btn-reset").onclick = () => post("/api/reset");
$("btn-random").onclick = () => post("/api/cube/random");
$("auto").onchange = (e) => post("/api/auto", { enabled: e.target.checked });
document.querySelectorAll("#speed button").forEach((b) => {
  b.onclick = () => post("/api/speed", { value: Number(b.dataset.speed) });
});

// ---------- map ----------
const canvas = $("map");
const map = makeMap(canvas);

function draw() {
  map.table({ inner: 0.13, outer: 0.28, deg: 60 });
  if (!state) return;
  const size = state.cube_size;
  const ctx = map.ctx;
  map.arm(state.tip);

  if (state.tower) {
    const [px, py] = map.toPx(state.tower.x, state.tower.y);
    ctx.strokeStyle = css("--seen");
    ctx.lineWidth = 2;
    ctx.setLineDash([]);
    ctx.beginPath(); ctx.arc(px, py, size * map.SCALE * 1.1, 0, Math.PI * 2); ctx.stroke();
  }
  // true cubes, lowest first so the top of a tower is drawn last
  const cubes = Object.entries(state.cubes).sort((a, b) => a[1].z - b[1].z);
  for (const [c, cube] of cubes) {
    const fill = css(CUBE_VAR[c]);
    if (drag && drag.color === c) {
      map.square(cube.x, cube.y, cube.yaw_deg, size, null, css("--muted"), [2, 3]);
      map.square(drag.x, drag.y, cube.yaw_deg, size, fill + "aa", fill);
      continue;
    }
    const level = Math.round(cube.z / size - 0.5);
    map.square(cube.x, cube.y, cube.yaw_deg, size * (1 + 0.12 * level), fill, level ? "#fff" : null);
    if (level > 0) {
      const [px, py] = map.toPx(cube.x, cube.y);
      ctx.fillStyle = css("--ink");
      ctx.font = "11px -apple-system, sans-serif";
      ctx.fillText(`${level + 1}층`, px + size * map.SCALE * 0.9, py + 4);
    }
  }
  // camera estimates (table plane)
  for (const [c, s] of Object.entries(state.seen || {})) {
    map.square(s.x, s.y, s.yaw_deg, size * 1.3, null, css(CUBE_VAR[c]), [4, 3]);
  }
  map.fingertip(state.tip);
}

function loop() {
  draw();
  requestAnimationFrame(loop);
}

function cubeAt(p) {
  if (!state) return null;
  let best = null;
  for (const [c, cube] of Object.entries(state.cubes)) {
    const d = Math.hypot(cube.x - p.x, cube.y - p.y);
    if (d < 0.03 && (!best || d < best.d)) best = { color: c, d, cube };
  }
  return best;
}

function idle() {
  if (state && state.busy) {
    toast("동작 중에는 큐브를 옮길 수 없어요. 먼저 ■ 정지를 누르세요.");
    return false;
  }
  return true;
}

canvas.addEventListener("pointerdown", (ev) => {
  const p = map.fromEvent(ev);
  const hit = cubeAt(p);
  if (!hit) return toast("큐브를 눌러 끌어 옮기세요.");
  if (!idle()) return;
  canvas.setPointerCapture(ev.pointerId);
  drag = { color: hit.color, x: hit.cube.x, y: hit.cube.y, dx: hit.cube.x - p.x, dy: hit.cube.y - p.y };
});
canvas.addEventListener("pointermove", (ev) => {
  if (!drag) return;
  const p = map.fromEvent(ev);
  drag.x = p.x + drag.dx;
  drag.y = p.y + drag.dy;
});
canvas.addEventListener("pointerup", async () => {
  if (!drag) return;
  const d = drag;
  const yaw = state.cubes[d.color].yaw_deg;
  const res = await post("/api/cube", { color: d.color, x: d.x, y: d.y, yaw_deg: fold(yaw) });
  drag = null;
  if (res.ok && res.reachable === false) toast("이 위치는 팔이 닿지 않아요. 초록 범위 안이 좋아요.");
});

const yawTimers = {};
canvas.addEventListener("wheel", (ev) => {
  const hit = cubeAt(map.fromEvent(ev));
  if (!hit || !state || state.busy) return;
  ev.preventDefault();
  const cube = state.cubes[hit.color];
  cube.yaw_deg = fold(cube.yaw_deg + (ev.deltaY > 0 ? 5 : -5));
  clearTimeout(yawTimers[hit.color]);
  yawTimers[hit.color] = setTimeout(
    () => post("/api/cube", { color: hit.color, x: cube.x, y: cube.y, yaw_deg: cube.yaw_deg }), 250);
}, { passive: false });

PAGE.apply = apply;
PAGE.reloadStreams = reloadStreams;
loop();
boot();
