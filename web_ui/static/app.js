const appState = { status: null, detections: [], selectedId: null, socket: null, reconnectTimer: null };
const $ = (id) => document.getElementById(id);
const runningStates = new Set(["INITIALIZING", "OBSERVING", "TARGET_SELECTED", "APPROACHING", "GRASPING", "TRANSFERRING", "RELEASING", "POURING", "HOMING"]);
const stageOrder = ["OBSERVING", "APPROACHING", "GRASPING", "TRANSFERRING", "POURING", "FINISHED"];

function setClock() {
  $("clock").textContent = new Date().toLocaleTimeString("en-GB", { hour12: false });
}

function showToast(message, error = false) {
  const toast = $("toast");
  toast.textContent = message;
  toast.classList.toggle("error", error);
  toast.classList.add("show");
  window.clearTimeout(showToast.timer);
  showToast.timer = window.setTimeout(() => toast.classList.remove("show"), 2600);
}

async function api(path, options = {}) {
  const response = await fetch(path, { headers: { "Content-Type": "application/json", ...(options.headers || {}) }, ...options });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(body.detail || `요청 실패 (${response.status})`);
  return body;
}

function stateClass(state) {
  if (state === "READY") return "ready";
  if (state === "FINISHED") return "finished";
  if (state === "ERROR") return "error";
  if (state === "STOPPING") return "stopping";
  return runningStates.has(state) ? "running" : "offline";
}

function setConnection(dotId, textId, connected, onlineText, offlineText) {
  $(dotId).classList.toggle("online", connected);
  $(textId).textContent = connected ? onlineText : offlineText;
}

function renderStatus(status) {
  appState.status = status;
  const badge = $("systemState");
  badge.className = `state-badge ${stateClass(status.state)}`;
  badge.innerHTML = `<span></span>${status.state}`;
  setConnection("robotDot", "robotStatus", status.robot_connected, "Mock 연결됨", "연결 안 됨");
  setConnection("cameraDot", "cameraStatus", status.camera_connected, "Mock 스트림", "연결 안 됨");
  setConnection("modelDot", "modelStatus", status.model_loaded, "Mock 로드됨", "로드 안 됨");
  $("currentStep").textContent = status.current_step || (status.state === "FINISHED" ? "작업 완료" : "대기 중");
  $("progressValue").textContent = `${status.progress}%`;
  $("progressBar").style.width = `${status.progress}%`;
  $("frameTime").textContent = status.camera_connected ? new Date().toLocaleTimeString("en-GB", { hour12: false }) : "NO SIGNAL";

  const stateIndex = stageOrder.indexOf(status.state);
  document.querySelectorAll("[data-stage]").forEach((node, index) => node.classList.toggle("active", stateIndex >= 0 && index <= stateIndex));
  const ready = status.state === "READY";
  $("initializeBtn").disabled = !(["OFFLINE", "ERROR"].includes(status.state) && !status.busy);
  $("detectBtn").disabled = !(ready || status.state === "FINISHED") || status.busy;
  $("runBtn").disabled = !ready || status.busy || appState.detections.length === 0;
  $("homeBtn").disabled = !(["READY", "FINISHED"].includes(status.state)) || status.busy;
  $("stopBtn").disabled = !status.busy;
}

function addLog(entry) {
  const stream = $("logStream");
  stream.querySelector(".log-placeholder")?.remove();
  const row = document.createElement("div");
  row.className = `log-line ${(entry.level || "INFO").toLowerCase()}`;
  const timestamp = new Date(entry.timestamp);
  const time = Number.isNaN(timestamp.getTime()) ? "--:--:--" : timestamp.toLocaleTimeString("en-GB", { hour12: false });
  row.innerHTML = `<time>${time}</time><b>${entry.level || "INFO"}</b><span></span>`;
  row.querySelector("span").textContent = entry.message;
  stream.appendChild(row);
  while (stream.children.length > 120) stream.firstElementChild?.remove();
  stream.scrollTop = stream.scrollHeight;
}

function renderDetections(items) {
  appState.detections = items;
  if (!appState.selectedId && items.length) appState.selectedId = items[0].id;
  const list = $("ingredientsList");
  $("detectionCount").textContent = `${items.length} OBJECTS`;
  $("cameraEmpty").classList.toggle("hidden", items.length > 0);

  if (!items.length) {
    list.innerHTML = `<div class="empty-list"><span>＋</span><p>감지 결과가 없습니다.</p></div>`;
  } else {
    list.innerHTML = "";
    items.forEach((item, index) => {
      const card = document.createElement("div");
      card.className = "ingredient-card";
      card.dataset.id = item.id;
      card.innerHTML = `<span class="ingredient-index">#${String(index + 1).padStart(2, "0")}</span>
        <div class="ingredient-main"><strong></strong><span>CONF ${Math.round(item.confidence * 100)}% · DEPTH ${item.depth_m.toFixed(2)}m</span>
        <div class="confidence"><i style="width:${item.confidence * 100}%"></i></div></div>
        <span class="ingredient-status ${item.status === "완료" ? "done" : ""}">${item.status}</span>`;
      card.querySelector("strong").textContent = item.display_name;
      card.addEventListener("click", () => { appState.selectedId = item.id; updateCoordinate(item); drawFrame(); });
      list.appendChild(card);
    });
  }

  const selected = items.find((item) => item.id === appState.selectedId) || items[0];
  updateCoordinate(selected);
  drawFrame();
  if (appState.status) renderStatus(appState.status);
}

function updateCoordinate(item) {
  const values = item ? [...item.base_mm.map((value) => `${value.toFixed(1)} mm`), `${item.angle_deg.toFixed(1)}°`] : ["—", "—", "—", "—"];
  ["coordX", "coordY", "coordZ", "coordAngle"].forEach((id, index) => { $(id).textContent = values[index]; });
}

function drawFrame() {
  const canvas = $("cameraCanvas");
  const rect = canvas.getBoundingClientRect();
  if (!rect.width || !rect.height) return;
  const ratio = window.devicePixelRatio || 1;
  canvas.width = Math.round(rect.width * ratio);
  canvas.height = Math.round(rect.height * ratio);
  const context = canvas.getContext("2d");
  context.scale(ratio, ratio);
  context.clearRect(0, 0, rect.width, rect.height);
  if (!appState.detections.length) return;
  const scaleX = rect.width / 1280;
  const scaleY = rect.height / 720;
  const colors = { tomato: "#ff6f76", lettuce: "#b6f36d", carrot: "#ffbe4a" };
  context.fillStyle = "rgba(8, 23, 29, 0.5)";
  context.fillRect(rect.width * .12, rect.height * .14, rect.width * .76, rect.height * .69);
  context.strokeStyle = "rgba(56, 232, 212, 0.12)";
  context.strokeRect(rect.width * .12, rect.height * .14, rect.width * .76, rect.height * .69);

  appState.detections.forEach((item) => {
    const [x, y, width, height] = item.box;
    const cx = (x + width / 2) * scaleX;
    const cy = (y + height / 2) * scaleY;
    const color = colors[item.class_name] || "#38e8d4";
    const selected = item.id === appState.selectedId;
    context.save();
    context.translate(cx, cy);
    context.rotate(item.angle_deg * Math.PI / 180);
    context.fillStyle = `${color}22`;
    context.strokeStyle = color;
    context.lineWidth = selected ? 2.2 : 1.2;
    context.setLineDash(selected ? [] : [6, 5]);
    context.fillRect(-width * scaleX / 2, -height * scaleY / 2, width * scaleX, height * scaleY);
    context.strokeRect(-width * scaleX / 2, -height * scaleY / 2, width * scaleX, height * scaleY);
    context.restore();
    context.fillStyle = color;
    context.font = "500 10px IBM Plex Mono, monospace";
    context.fillText(`${item.display_name} ${(item.confidence * 100).toFixed(0)}%`, x * scaleX, Math.max(14, y * scaleY - 7));
    context.beginPath();
    context.arc(item.pixel[0] * scaleX, item.pixel[1] * scaleY, 3, 0, Math.PI * 2);
    context.fill();
  });
}

async function loadStatus() { renderStatus(await api("/api/status")); }
async function loadDetections() { renderDetections(await api("/api/detections")); }
async function loadLogs() {
  const body = await api("/api/logs");
  $("logStream").innerHTML = "";
  body.items.forEach(addLog);
  if (!body.items.length) $("logStream").innerHTML = `<div class="log-placeholder">이벤트를 기다리는 중...</div>`;
}

async function runCommand(path, body) {
  try {
    const result = await api(path, { method: "POST", body: body ? JSON.stringify(body) : undefined });
    showToast(result.message);
    await loadStatus();
  } catch (error) { showToast(error.message, true); }
}

function connectWebSocket() {
  window.clearTimeout(appState.reconnectTimer);
  const protocol = location.protocol === "https:" ? "wss" : "ws";
  const socket = new WebSocket(`${protocol}://${location.host}/ws/events`);
  appState.socket = socket;
  $("socketStatus").textContent = "WS CONNECTING";
  socket.addEventListener("open", () => { $("socketStatus").textContent = "WS ONLINE"; });
  socket.addEventListener("message", (message) => {
    const event = JSON.parse(message.data);
    if (event.type === "status") renderStatus(event.data);
    if (event.type === "log") addLog(event.data);
    if (event.type === "detections") renderDetections(event.data.items || []);
    if (event.type === "logs_cleared") $("logStream").innerHTML = `<div class="log-placeholder">이벤트를 기다리는 중...</div>`;
  });
  socket.addEventListener("close", () => {
    $("socketStatus").textContent = "WS RETRYING";
    appState.reconnectTimer = window.setTimeout(connectWebSocket, 1800);
  });
}

$("initializeBtn").addEventListener("click", () => runCommand("/api/initialize"));
$("detectBtn").addEventListener("click", () => runCommand("/api/detect"));
$("runBtn").addEventListener("click", () => runCommand("/api/run", { dry_run: true, recipe: { tomato: 1, lettuce: 1, carrot: 1 } }));
$("stopBtn").addEventListener("click", () => runCommand("/api/stop"));
$("homeBtn").addEventListener("click", () => runCommand("/api/home"));
$("clearLogBtn").addEventListener("click", async () => {
  try {
    await api("/api/logs", { method: "DELETE" });
    $("logStream").innerHTML = `<div class="log-placeholder">이벤트를 기다리는 중...</div>`;
  } catch (error) { showToast(error.message, true); }
});

new ResizeObserver(drawFrame).observe($("cameraStage"));
setClock();
window.setInterval(setClock, 1000);
window.setInterval(() => loadStatus().catch(() => {}), 4000);
Promise.all([loadStatus(), loadDetections(), loadLogs()]).then(connectWebSocket).catch((error) => showToast(`서버 연결 실패: ${error.message}`, true));
