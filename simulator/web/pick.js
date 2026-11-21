// The pick page (/pick/): state → UI, the table map with the one red cube,
// buttons. Server talk, video and sharing live in common.js.
"use strict";

const STAGES = ["scan", "hover", "descend", "grip", "lift"];
const STAGE_NAME = {
  idle: "대기", scan: "찾는 중", hover: "다가가는 중", descend: "내려가는 중",
  grip: "잡는 중", lift: "들어 올리는 중", done: "성공", fail: "실패",
  place: "내려놓는 중", home: "처음 자세로",
};

let drag = null; // {x, y} preview while placing the cube
let yawDeg = 20;
let yawTimer = null;

// ---------- state → UI ----------
function apply(s) {
  state = s;
  $("picks").textContent = `성공 ${s.picks.ok} / ${s.picks.total}`;
  if (typeof s.viewers === "number") {
    $("viewers").hidden = s.viewers < 2;
    $("viewers").textContent = `👀 ${s.viewers}명 보는 중`;
  }
  const lag = videoDelay();
  $("sim-time").textContent = `${s.time.toFixed(1)} s` +
    (lag === null ? "" : ` · 영상 ${lag.toFixed(1)}초 늦게`);
  $("stage-badge").textContent = STAGE_NAME[s.stage] || s.stage;

  const status = $("status");
  status.textContent = s.status || "준비됐습니다. 지도에서 큐브를 놓고 ‘집기 시작’을 누르세요.";
  status.className = "status" + (s.stage === "done" ? " ok" : s.stage === "fail" ? " bad" : "");

  const pipe = $("pipeline");
  const now = STAGES.indexOf(s.stage);
  const finished = s.stage === "done" || (s.result === "lifted" && !s.busy);
  pipe.classList.toggle("failed", s.stage === "fail");
  [...pipe.children].forEach((li, i) => {
    li.classList.toggle("now", i === now || (s.stage === "fail" && i === lastStage));
    li.classList.toggle("done", finished || (now >= 0 && i < now));
  });
  if (now >= 0) lastStage = now;

  $("btn-pick").disabled = s.busy;
  $("btn-place").disabled = s.busy || !s.holding;
  $("btn-home").disabled = s.busy;
  $("btn-stop").disabled = !s.busy && !s.auto;
  $("btn-random").disabled = s.busy;
  $("auto").checked = s.auto;
  $("map").classList.toggle("busy", s.busy);
  document.querySelectorAll("#speed button").forEach((b) => {
    b.classList.toggle("active", Number(b.dataset.speed) === s.speed);
  });

  renderTicks(s.ticks);
  renderLog(s.log);
  if (!drag && document.activeElement !== $("yaw")) {
    // follow the cube's real yaw (folded to ±45°) while not editing
    const y = fold(s.cube.yaw_deg);
    $("yaw").value = Math.round(y);
    $("yaw-value").textContent = `${Math.round(y)}°`;
    yawDeg = y;
  }
  const c = s.cube;
  $("coords").textContent =
    `큐브 x ${(c.x * 1000).toFixed(0)} · y ${(c.y * 1000).toFixed(0)} · 높이 ${(c.z * 1000).toFixed(0)} mm` +
    (s.sighting ? `   |   카메라 추정 x ${(s.sighting.x * 1000).toFixed(0)} · y ${(s.sighting.y * 1000).toFixed(0)} mm` : "");
}
let lastStage = -1;

let mainView = "wrist";
function setMain(view) {
  mainView = view;
  const other = view === "wrist" ? "overview" : "wrist";
  show($("main-view"), view);
  const thumb = $("thumb-other");
  thumb.dataset.view = other;
  show(thumb.querySelector("img"), other, true);
  thumb.querySelector("figcaption").textContent =
    (other === "wrist" ? "1인칭" : "3인칭") + " · 클릭하면 크게";
  document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("active", t.dataset.view === view));
}
function reloadStreams() {
  setMain(mainView);
  show($("detector-view"), "detector", true);
}
document.querySelectorAll(".tab").forEach((t) => (t.onclick = () => setMain(t.dataset.view)));
$("thumb-other").onclick = () => setMain($("thumb-other").dataset.view);
document.querySelectorAll(".video-card img").forEach((img) => {
  img.onerror = () => setTimeout(() => online && img.src && (img.src = freshen(img.src)), 1000);
});

// ---------- buttons ----------
$("btn-pick").onclick = () => post("/api/pick");
$("btn-place").onclick = () => post("/api/place");
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
  map.table();
  if (!state) return;
  const size = state.cube_size;
  map.arm(state.tip);
  // camera estimate
  if (state.sighting) {
    map.square(state.sighting.x, state.sighting.y, state.sighting.yaw_deg, size, null, css("--seen"), [4, 3]);
  }
  // cube (preview while dragging)
  const c = state.cube;
  if (drag) {
    map.square(c.x, c.y, c.yaw_deg, size, null, css("--muted"), [2, 3]);
    map.square(drag.x, drag.y, yawDeg, size, css("--cube") + "aa", css("--cube"));
  } else {
    const lifted = c.z > size;
    map.square(c.x, c.y, c.yaw_deg, size * (lifted ? 1.15 : 1), css("--cube"), lifted ? "#fff" : null);
  }
  map.fingertip(state.tip);
}

function loop() {
  draw();
  requestAnimationFrame(loop);
}

function placeAllowed() {
  if (state && state.busy) {
    toast("동작 중에는 큐브를 옮길 수 없어요. 먼저 ■ 정지를 누르세요.");
    return false;
  }
  return true;
}

canvas.addEventListener("pointerdown", (ev) => {
  if (!placeAllowed()) return;
  canvas.setPointerCapture(ev.pointerId);
  drag = map.fromEvent(ev);
});
canvas.addEventListener("pointermove", (ev) => {
  if (drag) drag = map.fromEvent(ev);
});
canvas.addEventListener("pointerup", async () => {
  if (!drag) return;
  const spot = drag;
  const res = await post("/api/cube", { x: spot.x, y: spot.y, yaw_deg: yawDeg });
  drag = null;
  if (res.ok && res.reachable === false) toast("이 위치는 팔이 닿지 않아요. 초록 범위 안이 좋아요.");
});
canvas.addEventListener("wheel", (ev) => {
  if (!state || state.busy) return;
  ev.preventDefault();
  setYaw(yawDeg + (ev.deltaY > 0 ? 5 : -5));
}, { passive: false });

function setYaw(v) {
  yawDeg = fold(v);
  $("yaw").value = Math.round(yawDeg);
  $("yaw-value").textContent = `${Math.round(yawDeg)}°`;
  if (state && !state.busy) {
    state.cube.yaw_deg = yawDeg;
    clearTimeout(yawTimer);
    yawTimer = setTimeout(() => post("/api/cube", { x: state.cube.x, y: state.cube.y, yaw_deg: yawDeg }), 250);
  }
}
$("yaw").addEventListener("input", (e) => {
  if (!placeAllowed()) return;
  setYaw(Number(e.target.value));
});

PAGE.apply = apply;
PAGE.reloadStreams = reloadStreams;
loop();
boot();
