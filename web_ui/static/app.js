const appState = { status: null, detections: [], selectedId: null, socket: null, reconnectTimer: null, imageId: null, online: false };
const $ = (id) => document.getElementById(id);
const runningStates = new Set(["INITIALIZING", "OBSERVING", "TARGET_SELECTED", "APPROACHING", "GRASPING", "TRANSFERRING", "RELEASING", "POURING", "HOMING"]);
const stageOrder = ["OBSERVING", "APPROACHING", "GRASPING", "TRANSFERRING", "RELEASING", "FINISHED"];

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
  if (!response.ok) throw new Error(typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail || response.status));
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
  const real = status.live_robot;
  const badge = $("systemState");
  badge.className = `state-badge ${stateClass(status.state)}`;
  badge.innerHTML = `<span></span>${status.state}`;
  setConnection("robotDot", "robotStatus", status.robot_connected, real ? "E0509 점검 통과" : "Mock 연결됨", "연결 안 됨");
  setConnection("cameraDot", "cameraStatus", status.camera_connected, real ? "촬영 방식" : "Mock 스트림", "연결 안 됨");
  setConnection("modelDot", "modelStatus", status.model_loaded, real ? "best.pt 로드됨" : "Mock 로드됨", "로드 안 됨");
  setConnection("gripperDot", "gripperStatus", status.gripper_connected, "서비스 점검 통과", real ? "확인 전" : "Mock");
  $("tcpStatus").textContent = real ? (status.tcp === null ? "—" : status.tcp || "기본 TCP (빈 이름)") : "MockGripper_v1";
  $("modeLabel").textContent = `${status.mode}${appState.online ? '' : ' · 연결 끊김'}`;
  $("feedLabel").textContent = real ? "LAST CAPTURE · 정지 사진" : "MOCK FEED";
  $("cameraSize").textContent = status.camera_profile ? `${status.camera_profile.width} × ${status.camera_profile.height}` : "1280 × 720";
  $("cameraStage").classList.toggle('real-camera', real);
  $("cameraCanvas").classList.toggle('hidden', real);
  $("sceneImage").classList.toggle('hidden', !(real && status.image_available));
  if (real && status.image_available && appState.imageId !== status.scene_id) {
    appState.imageId = status.scene_id;
    $("sceneImage").src = `/api/scene-image?v=${encodeURIComponent(status.scene_id)}`;
  }
  $("currentStep").textContent = status.current_step || (status.state === "FINISHED" ? "작업 완료" : "대기 중");
  $("progressValue").textContent = `${status.progress}%`;
  $("progressBar").style.width = `${status.progress}%`;
  $("frameTime").textContent = real ? (status.scene_valid ? "CAPTURE VALID" : "RECAPTURE REQUIRED") : "MOCK";

  const stateIndex = stageOrder.indexOf(status.state);
  document.querySelectorAll("[data-stage]").forEach((node, index) => node.classList.toggle("active", stateIndex >= 0 && index <= stateIndex));
  const held = status.state === 'HOLDING';
  const blocked = !appState.online || status.busy || status.recovery_required || status.restart_required;
  const ready = status.robot_connected && !blocked;
  const sceneReady = real ? status.scene_valid : appState.detections.length > 0;
  $("initializeBtn").disabled = blocked || (real ? status.robot_connected : !['OFFLINE','ERROR'].includes(status.state));
  $("detectBtn").disabled = !ready || held;
  $("runBtn").disabled = !ready || held || !sceneReady || (!real && status.state !== 'READY');
  $("homeBtn").disabled = !ready || held;
  $("stopBtn").disabled = !appState.online || !status.busy;
  document.querySelectorAll('[data-test]').forEach(button => {
    button.disabled = !real || !ready || (button.dataset.test === 'return' ? !held : held || !sceneReady);
  });
  document.querySelectorAll('.run-settings input, .run-settings select').forEach(input => {
    // After refreshing while HOLDING, the operator must be able to explicitly
    // authorize a LIVE return; all geometry controls remain locked.
    input.disabled = !real || status.busy || (held && input.id !== 'liveMode');
  });
  $("sceneNote").textContent = status.recovery_required ? '동작 중단: 현장에서 안전 상태를 복구하고 서버를 재시작하세요.' :
    status.restart_required ? '초기화 실패 또는 설정 변경: 로그를 확인하고 서버를 재시작하세요.' :
    held ? '박스를 들고 대기 중입니다. 파지 상태를 확인한 후 원위치 반환(RETURN)하세요.' :
    !real ? 'Mock 모드: 실제 장비를 움직이지 않습니다.' :
    status.scene_valid ? '사진·좌표 확인 후 실행하세요. 물체가 움직였다면 다시 촬영하세요.' : '05 장면 인식이 필요합니다. 촬영 전 HOME으로 이동할 때도 경로를 확인하세요.';
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
        <div class="ingredient-main"><strong></strong><span>CONF ${Math.round(item.confidence * 100)}% · ${item.depth_m == null ? '고정 Z 사용' : `DEPTH ${item.depth_m.toFixed(2)}m`}</span>
        <div class="confidence"><i style="width:${item.confidence * 100}%"></i></div></div>
        <span class="ingredient-status ${item.status === "완료" ? "done" : ""}">${item.valid ? item.status : '재촬영 필요'}</span>`;
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
  const values = item ? [
    `${item.base_mm[0].toFixed(1)} mm`, `${item.base_mm[1].toFixed(1)} mm`,
    item.base_mm.length > 2 ? `${item.base_mm[2].toFixed(1)} mm` : '기록 Z 사용',
    item.angle_deg == null ? '고정 방향' : `${item.angle_deg.toFixed(1)}°`
  ] : ["—", "—", "—", "—"];
  ["coordX", "coordY", "coordZ", "coordAngle"].forEach((id, index) => { $(id).textContent = values[index]; });
}

function drawFrame() {
  if (appState.status?.live_robot) return;
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
  const colors = { tomato: "#ff6f76", cheese: "#ffbe4a", berry: "#b39bfa" };
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

async function loadStatus() {
  try { const status = await api("/api/status"); appState.online = true; renderStatus(status); }
  catch (error) { appState.online = false; if (appState.status) renderStatus(appState.status); throw error; }
}
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
    if (event.type === "status") { appState.online = true; renderStatus(event.data); }
    if (event.type === "log") addLog(event.data);
    if (event.type === "detections") renderDetections(event.data.items || []);
    if (event.type === "logs_cleared") $("logStream").innerHTML = `<div class="log-placeholder">이벤트를 기다리는 중...</div>`;
  });
  socket.addEventListener("close", () => {
    appState.online = false;
    if (appState.status) renderStatus(appState.status);
    $("socketStatus").textContent = "WS RETRYING";
    appState.reconnectTimer = window.setTimeout(connectWebSocket, 1800);
  });
}

$("initializeBtn").addEventListener("click", () => runCommand("/api/initialize"));
$("detectBtn").addEventListener("click", () => runCommand("/api/detect", {rotate: $("rotateMode").checked}));
function motion(kind) {
  const real = appState.status?.live_robot;
  const payload = {dry_run: !real || !$("liveMode").checked, scene_id: appState.status?.scene_id,
    recipe: {tomato: 1, cheese: 1, berry: 1}, class_name: $("targetClass").value,
    rotate: $("rotateMode").checked, reference_yaw_deg: $("referenceYaw").value === '' ? null : Number($("referenceYaw").value),
    hover_height_mm: Number($("hoverHeight").value), vel: Number($("velocity").value), acc: Number($("acceleration").value)};
  if (payload.rotate && payload.reference_yaw_deg === null) { showToast('회전 기준각을 입력하세요.', true); return; }
  if (!payload.dry_run) {
    const phrase = {home:'MOVE HOME', 'bowl-hover':'MOVE BOWL', 'pick-hover':`HOVER ${payload.class_name.toUpperCase()}`,
      pick:`PICK ${payload.class_name.toUpperCase()}`, 'pick-place':'RUN ONE', salad:'RUN SALAD', return:'RETURN'}[kind];
    const text = window.prompt(`실제 로봇이 움직입니다. 현재→safe_wait를 포함한 전체 경로와 주변을 확인하세요.\n즉시 정지는 물리 E-STOP입니다.\n계속하려면 ${phrase} 입력`);
    if (text !== phrase) { showToast('실제 이동을 취소했습니다.'); return; }
    payload.confirmation = text;
  }
  runCommand(kind === 'salad' ? '/api/run' : kind === 'home' ? '/api/home' : `/api/test/${kind}`, payload);
}
$("runBtn").addEventListener("click", () => motion('salad'));
$("stopBtn").addEventListener("click", () => runCommand("/api/stop"));
$("homeBtn").addEventListener("click", () => motion('home'));
document.querySelectorAll('[data-test]').forEach(button => button.addEventListener('click', () => motion(button.dataset.test)));
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
Promise.all([loadStatus(), loadDetections(), loadLogs()]).catch((error) => showToast(`서버 연결 실패: ${error.message}`, true));
connectWebSocket();
