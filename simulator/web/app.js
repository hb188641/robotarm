// Browser panel for the SO-101 pick simulation. Polls /api/state, draws the
// top-down table map, and sends button / map actions to the server.
"use strict";

const $ = (id) => document.getElementById(id);
const STAGES = ["scan", "hover", "descend", "grip", "lift"];
const STAGE_NAME = {
  idle: "대기", scan: "찾는 중", hover: "다가가는 중", descend: "내려가는 중",
  grip: "잡는 중", lift: "들어 올리는 중", done: "성공", fail: "실패",
  place: "내려놓는 중", home: "처음 자세로",
};
const MOTOR_NAME = ["어깨 회전", "어깨 들기", "팔꿈치", "손목 꺾기", "손목 회전", "그리퍼"];

let state = null;
let online = false;
let drag = null; // {x, y} preview while placing the cube
let yawDeg = 20;
let yawTimer = null;

// ---------- server ----------
async function post(path, body) {
  try {
    const r = await fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body || {}),
    });
    const data = await r.json();
    if (!data.ok) toast(data.error || "실패했습니다");
    if (data.state) apply(data.state);
    return data;
  } catch (e) {
    toast("시뮬레이터에 연결할 수 없습니다");
    return { ok: false };
  }
}

async function poll() {
  if (stateSocket.live) return setTimeout(poll, 500); // the socket brings state
  try {
    const r = await fetch("/api/state", { cache: "no-store" });
    apply(await r.json());
    setOnline(true);
  } catch (e) {
    setOnline(false);
  }
  setTimeout(poll, 150);
}

// Over the internet each poll waits a full round trip (~0.3 s through the
// tunnel), so the server pushes the state over a WebSocket instead.
const stateSocket = {
  ws: null,
  live: false,
  failures: 0,
  timer: null,
  start() {
    if (!SMOOTH || this.ws) return;
    const ws = new WebSocket(wsUrl("/ws/state"));
    this.ws = ws;
    ws.onmessage = (ev) => {
      if (this.ws !== ws) return;
      this.live = true;
      this.failures = 0;
      apply(JSON.parse(ev.data));
      setOnline(true);
    };
    ws.onclose = () => {
      if (this.ws !== ws) return;
      this.ws = null;
      if (!this.live) this.failures += 1;
      this.live = false; // polling takes over (and notices if the server is gone)
      if (this.failures < 3) this.timer = setTimeout(() => this.start(), 1000);
    };
  },
  stop() {
    clearTimeout(this.timer);
    const ws = this.ws;
    this.ws = null;
    this.live = false;
    if (ws) ws.close();
  },
};

function setOnline(on) {
  if (on === online) return;
  online = on;
  const c = $("conn");
  c.className = "pill conn " + (on ? "on" : "off");
  c.querySelector("b").textContent = on ? "연결됨" : "연결 끊김";
  if (on) reloadStreams();
}

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

function fold(deg) {
  return ((((deg + 45) % 90) + 90) % 90) - 45;
}

function renderTicks(ticks) {
  const box = $("ticks");
  if (!box.children.length) {
    box.innerHTML = MOTOR_NAME.map(
      (n, i) => `<div class="tick"><b>${i + 1} ${n}</b><span id="t${i + 1}">-</span></div>`
    ).join("");
  }
  for (let i = 1; i <= 6; i++) $("t" + i).textContent = ticks[`motor_${i}`];
}

let lastLogKey = "";
function renderLog(items) {
  const key = items.map((i) => i.t + i.msg).join("|");
  if (key === lastLogKey) return;
  lastLogKey = key;
  $("log").innerHTML = items
    .slice()
    .reverse()
    .map((i) => `<li><span class="t">${i.t.toFixed(1)}s</span><span>${escapeHtml(i.msg)}</span></li>`)
    .join("");
}

function escapeHtml(s) {
  return s.replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
}

let toastTimer = null;
function toast(msg) {
  const t = $("toast");
  t.textContent = msg;
  t.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.classList.remove("show"), 2600);
}

// ---------- video ----------
// ?still=1 swaps the MJPEG streams for single frames refreshed twice a second
// (for browsers or networks where a stream will not play).
const STILL = new URLSearchParams(location.search).has("still");
// Over the internet every frame costs bandwidth: fewer frames, fewer for thumbnails.
const REMOTE = location.hostname.endsWith(".trycloudflare.com");
// Over the internet the tunnel delivers a long MJPEG response in ~128 KB lumps
// (the picture jumps about once a second), so frames come over WebSockets
// instead and play back from a small buffer: a little later, but evenly.
// ?smooth=1 / ?smooth=0 force it on / off.
const PARAMS = new URLSearchParams(location.search);
let SMOOTH = !STILL && "WebSocket" in window &&
  (PARAMS.has("smooth") ? PARAMS.get("smooth") !== "0" : REMOTE);
const FPS = { main: 20, small: REMOTE ? 3 : 10 };
function src(view, small) {
  if (STILL) return `/frame/${view}.jpg?t=${Date.now()}`;
  const fps = small ? FPS.small : REMOTE ? 10 : FPS.main;
  return `/stream/${view}.mjpg?fps=${fps}${small ? "" : "&main=1"}&t=${Date.now()}`;
}
function wsUrl(path) {
  return `${location.protocol === "https:" ? "wss" : "ws"}://${location.host}${path}`;
}

// Never hold frames back longer than this (s): late frames are shown at once
// (a small jump) instead of growing the delay.
const MAX_DELAY = 0.35;

// Plays timestamped frames from /ws/<view> on a canvas next to an <img>.
// Each frame carries its render time on the server. The fastest trip seen
// recently gives the clock offset; frames are then shown at render time +
// that offset + a delay just big enough to cover how late frames usually
// come (95th percentile), so network hiccups do not show as stutter.
class SmoothVideo {
  constructor(img) {
    this.img = img;
    this.canvas = document.createElement("canvas");
    this.canvas.className = "smooth";
    this.canvas.hidden = true;
    img.after(this.canvas);
    this.ctx = this.canvas.getContext("2d");
    this.ws = null;
    this.want = null;
    this.reset();
  }
  reset() {
    (this.queue || []).forEach((f) => f.bmp.close());
    this.queue = [];
    this.trips = []; // arrival - render time, seconds (includes clock offset)
    this.offset = 0;
    this.target = this.delay = 0.12;
    this.shown = false;
  }
  play(view, fps, main) {
    this.stop();
    this.want = { view, fps, main };
    this.img.hidden = true;
    this.canvas.hidden = false;
    this.connect();
  }
  stop() {
    this.want = null;
    clearTimeout(this.retry);
    if (this.ws) {
      const ws = this.ws;
      this.ws = null;
      ws.close();
    }
    this.reset();
  }
  connect() {
    const { view, fps, main } = this.want;
    // ack=1: each frame is answered, so the server never queues up a backlog.
    const ws = new WebSocket(wsUrl(`/ws/${view}?fps=${fps}&ack=1${main ? "&main=1" : ""}`));
    ws.binaryType = "arraybuffer";
    this.ws = ws;
    ws.onmessage = (ev) => this.ws === ws && this.receive(ev.data);
    ws.onclose = () => {
      if (this.ws !== ws) return; // replaced or stopped on purpose
      this.ws = null;
      if (!this.shown) this.failures = (this.failures || 0) + 1;
      if (this.failures >= 3) return fallBackToStreams();
      this.retry = setTimeout(() => this.want && this.connect(), 1000);
    };
  }
  receive(buf) {
    const now = performance.now() / 1000;
    const t = new DataView(buf).getFloat64(0, true);
    if (this.ws && this.ws.readyState === WebSocket.OPEN) this.ws.send("1"); // ack
    this.trips.push(now - t);
    if (this.trips.length > 150) this.trips.shift(); // ~10 s of frames
    this.offset = Math.min(...this.trips);
    const late = this.trips.map((s) => s - this.offset).sort((a, b) => a - b);
    const p95 = late[Math.floor(late.length * 0.95)];
    this.target = Math.min(MAX_DELAY, Math.max(0.08, p95 + 0.05));
    createImageBitmap(new Blob([new Uint8Array(buf, 12)], { type: "image/jpeg" }))
      .then((bmp) => {
        if (!this.want) return bmp.close();
        this.queue.push({ t, bmp });
        while (this.queue.length > 90) this.queue.shift().bmp.close(); // hidden tab
      })
      .catch(() => {});
  }
  tick(now) {
    if (!this.queue.length) return;
    // Grow the delay quickly when frames come late, shrink it slowly.
    const rate = this.target > this.delay ? 0.08 : 0.01;
    this.delay += (this.target - this.delay) * rate;
    const due = now - this.offset - this.delay;
    let frame = null;
    while (this.queue.length && (this.queue[0].t <= due || !this.shown)) {
      if (frame) frame.bmp.close();
      frame = this.queue.shift();
      this.shown = true;
    }
    if (!frame) return;
    const c = this.canvas;
    if (c.width !== frame.bmp.width || c.height !== frame.bmp.height) {
      c.width = frame.bmp.width;
      c.height = frame.bmp.height;
    }
    this.ctx.drawImage(frame.bmp, 0, 0);
    frame.bmp.close();
  }
}
const players = {};
function player(img) {
  return (players[img.id || img.closest("figure").id] ||= new SmoothVideo(img));
}
function show(img, view, small) {
  if (SMOOTH) return player(img).play(view, small ? FPS.small : FPS.main, !small);
  img.src = src(view, small);
}
function playFrames() {
  const now = performance.now() / 1000;
  Object.values(players).forEach((p) => p.tick(now));
  requestAnimationFrame(playFrames);
}
requestAnimationFrame(playFrames);
function fallBackToStreams() {
  // WebSockets are blocked somewhere on the way: go back to plain streams.
  if (!SMOOTH) return;
  SMOOTH = false;
  Object.values(players).forEach((p) => {
    p.stop();
    p.canvas.hidden = true;
    p.img.hidden = false;
  });
  stateSocket.stop();
  reloadStreams();
}
function videoDelay() {
  const p = SMOOTH && players["main-view"];
  return p && p.shown ? p.delay : null;
}
if (STILL) {
  setInterval(() => {
    document.querySelectorAll(".video-card img").forEach((img) => {
      img.src = freshen(img.src);
    });
  }, 500);
}
function freshen(url) {
  // new t= so the browser reconnects; keeps the other parameters (fps)
  return url.replace(/([?&]t=)\d+/, "$1" + Date.now());
}
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
// Robot base frame: x forward (up on the map), y left (left on the map).
const canvas = $("map");
const ctx = canvas.getContext("2d");
const VIEW = { yMin: -0.3, yMax: 0.3, xMin: -0.1, xMax: 0.34 };
const W = 600, H = 440;
const SCALE = W / (VIEW.yMax - VIEW.yMin); // px per metre

function toPx(x, y) {
  return [(VIEW.yMax - y) * SCALE, (VIEW.xMax - x) * SCALE];
}
function fromEvent(ev) {
  const r = canvas.getBoundingClientRect();
  const px = ((ev.clientX - r.left) / r.width) * W;
  const py = ((ev.clientY - r.top) / r.height) * H;
  return { x: VIEW.xMax - py / SCALE, y: VIEW.yMax - px / SCALE };
}

function setupCanvas() {
  const dpr = window.devicePixelRatio || 1;
  canvas.width = W * dpr;
  canvas.height = H * dpr;
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
}

function css(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

function drawSquare(x, y, yawDeg, size, fill, stroke, dash) {
  const [px, py] = toPx(x, y);
  const s = size * SCALE;
  ctx.save();
  ctx.translate(px, py);
  // map rotation: +yaw (counter-clockwise seen from above) turns left on screen
  ctx.rotate((-yawDeg * Math.PI) / 180);
  if (fill) {
    ctx.fillStyle = fill;
    ctx.fillRect(-s / 2, -s / 2, s, s);
  }
  if (stroke) {
    ctx.setLineDash(dash || []);
    ctx.lineWidth = 2;
    ctx.strokeStyle = stroke;
    ctx.strokeRect(-s / 2, -s / 2, s, s);
  }
  ctx.restore();
}

function draw() {
  ctx.clearRect(0, 0, W, H);
  ctx.fillStyle = css("--table");
  ctx.fillRect(0, 0, W, H);

  // grid every 5 cm, labels every 10 cm
  ctx.lineWidth = 1;
  ctx.font = "11px -apple-system, sans-serif";
  for (let v = -0.3; v <= 0.34 + 1e-9; v += 0.05) {
    const strong = Math.abs(Math.round(v * 100) % 10) === 0;
    ctx.strokeStyle = css(strong ? "--grid-strong" : "--grid");
    const [, py] = toPx(v, 0);
    if (v >= VIEW.xMin) {
      ctx.beginPath(); ctx.moveTo(0, py); ctx.lineTo(W, py); ctx.stroke();
    }
    const [px] = toPx(0, v);
    ctx.beginPath(); ctx.moveTo(px, 0); ctx.lineTo(px, H); ctx.stroke();
    if (strong && Math.abs(v) > 1e-9) {
      ctx.fillStyle = css("--muted");
      if (v >= VIEW.xMin) ctx.fillText(`${Math.round(v * 100)}cm`, toPx(0, 0)[0] + 4, py - 3);
    }
  }

  // reach band (front half-annulus the arm handles comfortably)
  const [ox, oy] = toPx(0, 0);
  ctx.fillStyle = css("--reach");
  ctx.beginPath();
  const a0 = -Math.PI / 2 - (70 * Math.PI) / 180, a1 = -Math.PI / 2 + (70 * Math.PI) / 180;
  ctx.arc(ox, oy, 0.28 * SCALE, a0, a1);
  ctx.arc(ox, oy, 0.13 * SCALE, a1, a0, true);
  ctx.closePath();
  ctx.fill();

  // robot base
  ctx.fillStyle = css("--accent");
  ctx.beginPath(); ctx.arc(ox, oy, 0.022 * SCALE, 0, Math.PI * 2); ctx.fill();
  ctx.fillStyle = css("--ink");
  ctx.font = "12px -apple-system, sans-serif";
  ctx.fillText("로봇", ox - 12, oy + 0.022 * SCALE + 14);
  ctx.fillStyle = css("--muted");
  ctx.fillText("앞 ↑", ox - 12, 14);

  if (!state) return;
  const size = state.cube_size;

  // arm: base → fingertip
  const [tx, ty] = toPx(state.tip.x, state.tip.y);
  ctx.strokeStyle = css("--accent");
  ctx.lineWidth = 6;
  ctx.lineCap = "round";
  ctx.beginPath(); ctx.moveTo(ox, oy); ctx.lineTo(tx, ty); ctx.stroke();

  // camera estimate
  if (state.sighting) {
    drawSquare(state.sighting.x, state.sighting.y, state.sighting.yaw_deg, size, null, css("--seen"), [4, 3]);
  }
  // cube (preview while dragging)
  const c = state.cube;
  if (drag) {
    drawSquare(c.x, c.y, c.yaw_deg, size, null, css("--muted"), [2, 3]);
    drawSquare(drag.x, drag.y, yawDeg, size, css("--cube") + "aa", css("--cube"));
  } else {
    const lifted = c.z > size;
    drawSquare(c.x, c.y, c.yaw_deg, size * (lifted ? 1.15 : 1), css("--cube"), lifted ? "#fff" : null);
  }

  // fingertip
  ctx.fillStyle = css("--tip");
  ctx.beginPath(); ctx.arc(tx, ty, 5, 0, Math.PI * 2); ctx.fill();
  ctx.fillStyle = css("--ink");
  ctx.font = "11px -apple-system, sans-serif";
  ctx.fillText(`${Math.round(state.tip.z * 1000)}mm`, tx + 8, ty - 6);
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
  drag = fromEvent(ev);
});
canvas.addEventListener("pointermove", (ev) => {
  if (drag) drag = fromEvent(ev);
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

// ---------- sharing: same network and internet ----------
let shareInfo = null;
let shareTimer = null;

function urlChip(url, label) {
  return `<span class="share-url"><code>${escapeHtml(label || url)}</code>` +
    `<button data-url="${escapeHtml(url)}">복사</button></span>`;
}

async function loadShare() {
  clearTimeout(shareTimer);
  try {
    shareInfo = await (await fetch("/api/info", { cache: "no-store" })).json();
  } catch (e) {
    shareTimer = setTimeout(loadShare, 3000);
    return;
  }
  const lan = shareInfo.share_urls || [];
  const net = shareInfo.internet || {};
  $("share-lan").hidden = !lan.length || shareInfo.remote;
  $("share-urls").innerHTML = lan.map((u) => urlChip(u)).join(" ");

  let body = "";
  if (net.status === "on" && net.link) {
    body = urlChip(net.link, net.url + "/?key=…") +
      ` <span class="net-note">링크(접속 키 포함)를 가진 사람만 들어올 수 있어요</span>`;
    if (shareInfo.can_share) body += ` <button class="btn small" id="net-off">공유 끄기</button>`;
  } else if (net.status === "starting") {
    body = `<span class="net-note">Cloudflare 터널 여는 중… (보통 5~15초)</span>`;
  } else if (shareInfo.can_share) {
    if (!net.available) {
      body = `<span class="net-err">cloudflared가 필요합니다: 터미널에서 <code>brew install cloudflared</code></span>`;
    } else {
      body = `<button class="btn small" id="net-on">🌐 인터넷 공유 켜기</button>` +
        ` <span class="net-note">포트포워딩 없이 어디서나 접속하는 링크를 만듭니다</span>`;
      if (net.status === "error" && net.error) body += ` <span class="net-err">${escapeHtml(net.error)}</span>`;
    }
  }
  $("net-body").innerHTML = body;
  $("share-net").hidden = !body;
  $("share").hidden = $("share-lan").hidden && $("share-net").hidden;

  $("share").querySelectorAll("button[data-url]").forEach((b) => (b.onclick = () => copy(b.dataset.url)));
  if ($("net-on")) $("net-on").onclick = () => toggleInternet(true);
  if ($("net-off")) $("net-off").onclick = () => toggleInternet(false);
  // Keep watching while the tunnel starts, and slowly afterwards (it can drop).
  shareTimer = setTimeout(loadShare, net.status === "starting" ? 1000 : 10000);
}

async function toggleInternet(enabled) {
  if (!enabled && !confirmOff()) return;
  try {
    const r = await fetch("/api/share", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ enabled }),
    });
    const data = await r.json();
    if (!data.ok && data.error) toast(data.error);
    if (data.internet && data.internet.status === "error") toast(data.internet.error);
  } catch (e) {
    toast("시뮬레이터에 연결할 수 없습니다");
  }
  loadShare();
}

function confirmOff() {
  // No browser dialogs: a second click within 3 s confirms.
  const b = $("net-off");
  if (b.dataset.armed) return true;
  b.dataset.armed = "1";
  b.textContent = "한 번 더 누르면 끕니다 (링크 무효)";
  setTimeout(() => {
    if (b.isConnected) {
      delete b.dataset.armed;
      b.textContent = "공유 끄기";
    }
  }, 3000);
  return false;
}

function copy(text) {
  // navigator.clipboard needs a secure context; a LAN http:// page is not one.
  if (navigator.clipboard && window.isSecureContext) {
    navigator.clipboard.writeText(text).then(() => toast("주소를 복사했습니다"));
    return;
  }
  const area = document.createElement("textarea");
  area.value = text;
  document.body.appendChild(area);
  area.select();
  try {
    document.execCommand("copy");
    toast("주소를 복사했습니다");
  } catch (e) {
    toast(text);
  }
  area.remove();
}

window.addEventListener("resize", setupCanvas);
setupCanvas();
loop();
stateSocket.start();
poll();
loadShare();
