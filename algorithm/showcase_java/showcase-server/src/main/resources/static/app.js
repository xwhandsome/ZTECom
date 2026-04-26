const SESSION_ID = "demo";
const HEALTH_MODE = "health_assistant";
const TOOL_MODE = "tool_short";

const demoScripts = [
  { label: "Demo1 创建提醒", text: "明早7点提醒奶奶吃降压药" },
  { label: "Demo2 修改提醒", text: "改成7点半" },
  { label: "Demo3 多轮补槽", text: "提醒奶奶吃降压药" },
  { label: "Demo4 查询环境", text: "卧室温度怎么样" },
  { label: "Demo5 环境联动", text: "如果卧室低于20度，晚上9点后自动开空调到24度" },
  { label: "Demo6 知识问答", text: "这个药饭前还是饭后吃" },
  { label: "Demo7 通知确认", text: "通知我儿子我今晚不舒服" },
  { label: "Demo8 会话续接", text: "查一下现在有哪些提醒" }
];

const state = {
  page: "dashboard",
  health: null,
  session: null,
  lastResponse: null,
  pendingAction: null,
  assistantMessages: [],
  floatMessages: []
};

document.addEventListener("DOMContentLoaded", () => {
  bindNavigation();
  bindHealthChat();
  bindFloatingChat();
  bindActions();
  renderDemoButtons();
  refreshAll();
  window.setInterval(refreshHealth, 6000);
});

function bindNavigation() {
  document.querySelectorAll("[data-page]").forEach((button) => {
    button.addEventListener("click", () => switchPage(button.dataset.page));
  });
  document.querySelectorAll("[data-page-link]").forEach((button) => {
    button.addEventListener("click", () => switchPage(button.dataset.pageLink));
  });
}

function bindActions() {
  byId("refreshButton").addEventListener("click", refreshAll);
  byId("resetButton").addEventListener("click", async () => {
    const result = await postJson("/showcase/api/reset", { session_id: SESSION_ID });
    if (isProxyProblem(result)) {
      appendAssistantMessage("system", result.message);
      state.health = result;
    } else {
      state.session = result.state;
      state.lastResponse = null;
      state.pendingAction = null;
      state.assistantMessages = [];
      state.floatMessages = [];
      appendAssistantMessage("system", "演示状态已重置。");
    }
    await refreshAll();
  });
}

function bindHealthChat() {
  byId("chatForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    await sendHealthText();
  });
  byId("confirmYes").addEventListener("click", () => confirmPending(true, HEALTH_MODE, "assistant"));
  byId("confirmNo").addEventListener("click", () => confirmPending(false, HEALTH_MODE, "assistant"));
}

function bindFloatingChat() {
  byId("floatOpen").addEventListener("click", () => byId("floatChat").classList.remove("hidden"));
  byId("floatClose").addEventListener("click", () => byId("floatChat").classList.add("hidden"));
  byId("floatForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    await sendFloatText();
  });
  byId("floatConfirmYes").addEventListener("click", () => confirmPending(true, TOOL_MODE, "float"));
  byId("floatConfirmNo").addEventListener("click", () => confirmPending(false, TOOL_MODE, "float"));
}

function renderDemoButtons() {
  const wrap = byId("demoList");
  clear(wrap);
  demoScripts.forEach((script) => {
    const button = document.createElement("button");
    button.className = "demo-button";
    button.type = "button";
    button.textContent = script.label;
    button.title = script.text;
    button.addEventListener("click", () => {
      switchPage("assistant");
      const input = byId("chatInput");
      input.value = script.text;
      input.focus();
    });
    wrap.appendChild(button);
  });
}

async function refreshAll() {
  await refreshHealth();
  await refreshState();
  renderAll();
}

async function refreshHealth() {
  state.health = await getJson("/showcase/api/health");
  renderHealth();
}

async function refreshState() {
  const result = await getJson(`/showcase/api/state/${encodeURIComponent(SESSION_ID)}`);
  if (!isProxyProblem(result)) {
    state.session = result;
    state.pendingAction = isConfirmAction(result.pending_action) ? result.pending_action : null;
  }
  renderAll();
}

async function sendHealthText() {
  const input = byId("chatInput");
  const text = input.value.trim();
  if (!text) {
    return;
  }
  input.value = "";
  appendAssistantMessage("user", text);

  const response = await postJson("/showcase/api/chat", {
    session_id: SESSION_ID,
    user_text: text,
    mode: HEALTH_MODE
  });
  if (isProxyProblem(response)) {
    appendAssistantMessage("system", response.message);
    state.health = response;
    renderHealth();
    return;
  }

  applyAgentResponse(response);
  appendAssistantMessage("assistant", response.assistant_text || "已收到。");
  await refreshState();
  renderAll();
}

async function sendFloatText() {
  const input = byId("floatInput");
  const text = input.value.trim();
  if (!text) {
    return;
  }
  input.value = "";
  appendFloatMessage("user", text);

  const response = await postJson("/showcase/api/chat", {
    session_id: SESSION_ID,
    user_text: text,
    mode: TOOL_MODE
  });
  if (isProxyProblem(response)) {
    appendFloatMessage("system", response.message);
    state.health = response;
    renderHealth();
    return;
  }

  applyAgentResponse(response);
  appendFloatMessage("assistant", response.assistant_text || "已处理。");
  await refreshState();
  renderAll();
}

async function confirmPending(approved, mode, target) {
  if (!state.pendingAction || !state.pendingAction.action_id) {
    appendTargetMessage(target, "system", "当前没有需要确认的操作。");
    return;
  }

  const response = await postJson("/showcase/api/confirm", {
    session_id: SESSION_ID,
    action_id: state.pendingAction.action_id,
    approved,
    mode
  });

  if (isProxyProblem(response)) {
    appendTargetMessage(target, "system", response.message);
    return;
  }

  applyAgentResponse(response);
  state.pendingAction = null;
  appendTargetMessage(target, "assistant", response.assistant_text || "操作已处理。");
  await refreshState();
  renderAll();
}

function applyAgentResponse(response) {
  state.lastResponse = response;
  state.pendingAction = response.requires_confirmation && isConfirmAction(response.pending_action) ? response.pending_action : null;
}

function switchPage(page) {
  state.page = page;
  document.querySelectorAll(".nav-item").forEach((item) => {
    item.classList.toggle("active", item.dataset.page === page);
  });
  document.querySelectorAll(".page").forEach((panel) => {
    panel.classList.toggle("active", panel.id === `page-${page}`);
  });

  const titles = {
    dashboard: ["控制中心", "家庭状态、提醒、设备和工具调用"],
    assistant: ["健康助手", "RAG 问答、Agent 工具调用和本地知识引用"],
    tasks: ["代办列表", "提醒、规则、通知记录和工具事件"]
  };
  const [title, subtitle] = titles[page] || titles.dashboard;
  setText("pageTitle", title);
  setText("pageSubtitle", subtitle);
}

function renderAll() {
  renderHealth();
  renderDashboard();
  renderAssistant();
  renderTasks();
  renderConfirm();
}

function renderHealth() {
  const health = state.health || {};
  const dot = byId("pythonDot");
  const online = health.status === "ok";
  dot.classList.toggle("online", online);
  dot.classList.toggle("offline", isProxyProblem(health));
  setText("pythonStatus", online ? "Python 在线" : (isProxyProblem(health) ? "Python 异常" : "检测中"));
  setText("llmStatus", health.llm ? health.llm.message : "-");
  setText("kbChunks", health.kb_chunks ?? "-");
  setText("sessionLabel", SESSION_ID);
}

function renderDashboard() {
  const session = state.session || {};
  const reminders = session.reminders || [];
  const rules = session.env_rules || [];
  const events = session.recent_tool_events || [];

  setText("metricReminders", String(reminders.length));
  setText("metricRules", String(rules.length));
  setText("metricLatency", state.lastResponse ? `${state.lastResponse.latency_ms} ms` : "-");
  setText("metricIntent", state.lastResponse ? state.lastResponse.intent : (session.last_intent || "-"));

  renderDevices(session.device_state || {});
  renderSensors(session.sensors || {});
  renderReminders(reminders);
  renderToolTimeline(events);
}

function renderDevices(devices) {
  const grid = byId("deviceGrid");
  clear(grid);
  const values = Object.values(devices);
  if (!values.length) {
    grid.appendChild(emptyNode("暂无设备状态"));
    return;
  }
  values.forEach((device) => {
    const item = document.createElement("div");
    item.className = "device-item";
    const title = document.createElement("strong");
    title.textContent = `${device.room || "-"} ${device.device || "-"}`;
    const status = document.createElement("span");
    status.className = `badge ${device.status === "on" ? "ok" : "warn"}`;
    status.textContent = device.status || "-";
    const detail = document.createElement("div");
    detail.className = "muted";
    detail.textContent = device.target_temp == null ? "目标温度 -" : `目标温度 ${device.target_temp} 度`;
    item.append(title, status, detail);
    grid.appendChild(item);
  });
}

function renderSensors(sensors) {
  const body = byId("sensorRows");
  clear(body);
  const entries = Object.entries(sensors);
  if (!entries.length) {
    body.appendChild(emptyRow("暂无传感器状态", 4));
    return;
  }
  entries.forEach(([room, sensor]) => {
    body.appendChild(row([
      room,
      sensor.temperature == null ? "-" : `${sensor.temperature} 度`,
      sensor.humidity == null ? "-" : `${sensor.humidity}%`,
      sensor.motion || "-"
    ]));
  });
}

function renderReminders(reminders) {
  const body = byId("reminderRows");
  clear(body);
  if (!reminders.length) {
    body.appendChild(emptyRow("暂无用药提醒", 5));
    return;
  }
  reminders.forEach((item) => {
    body.appendChild(row([
      item.id,
      item.person,
      item.medicine,
      item.time_text || item.time,
      item.enabled ? "启用" : "停用"
    ]));
  });
}

function renderToolTimeline(events) {
  const wrap = byId("toolTimeline");
  clear(wrap);
  if (!events.length) {
    wrap.appendChild(emptyNode("暂无工具调用"));
    return;
  }
  events.slice(-8).reverse().forEach((event) => {
    const item = document.createElement("div");
    item.className = "timeline-item";
    const name = document.createElement("strong");
    name.textContent = `${event.tool_name} · ${event.success ? "成功" : "失败"}`;
    const detail = document.createElement("div");
    detail.className = "muted";
    detail.textContent = event.ts || "";
    item.append(name, detail);
    wrap.appendChild(item);
  });
}

function renderAssistant() {
  const response = state.lastResponse || {};
  setText("analysisIntent", response.intent || "-");
  setText("analysisLatency", response.latency_ms == null ? "-" : `${response.latency_ms} ms`);
  setText("analysisLlm", response.llm_used ? "已调用" : "未调用");
  byId("analysisSlots").textContent = pretty(response.slots || {});
  byId("analysisPlan").textContent = pretty(response.plan_steps || []);
  byId("analysisTools").textContent = pretty(response.tool_events || []);
  renderKnowledgeRefs(response.knowledge_refs || []);
  renderMessageList(byId("chatLog"), state.assistantMessages);
  renderMessageList(byId("floatLog"), state.floatMessages);
}

function renderKnowledgeRefs(refs) {
  const wrap = byId("knowledgeRefs");
  clear(wrap);
  if (!refs.length) {
    wrap.appendChild(emptyNode("本轮没有知识库引用"));
    return;
  }
  refs.forEach((ref) => {
    const item = document.createElement("div");
    item.className = "ref-item";
    const title = document.createElement("strong");
    title.textContent = ref.chunk_id ? `${ref.title || ref.doc_id || "知识片段"} · ${ref.chunk_id}` : (ref.title || ref.doc_id || "知识片段");
    const text = document.createElement("div");
    text.className = "muted";
    text.textContent = ref.snippet || "";
    item.append(title, text);
    wrap.appendChild(item);
  });
}

function renderTasks() {
  const body = byId("taskRows");
  clear(body);
  const session = state.session || {};
  const rows = [];

  (session.reminders || []).forEach((item) => {
    rows.push(["用药提醒", `${item.person} ${item.time_text || item.time} 吃${item.medicine}`, item.enabled ? "启用" : "停用", item.updated_at || item.created_at || "-", "删除"]);
  });
  (session.env_rules || []).forEach((rule) => {
    const target = rule.target_temp == null ? "" : `到${rule.target_temp}度`;
    rows.push(["环境规则", `${rule.room} 温度 ${rule.comparator}${rule.threshold}，${rule.action}${rule.device}${target}`, rule.enabled ? "启用" : "停用", "-", "删除"]);
  });
  if (session.pending_action) {
    rows.push(["待确认", session.pending_action.intent || "pending", "等待处理", session.pending_action.action_id || "-", "确认"]);
  }
  (session.recent_tool_events || []).slice(-8).reverse().forEach((event) => {
    rows.push(["工具事件", event.tool_name, event.success ? "成功" : "失败", event.ts || "-", "查看"]);
  });

  if (!rows.length) {
    body.appendChild(emptyRow("暂无任务记录", 5));
    return;
  }
  rows.forEach((values) => {
    const tr = row(values);
    tr.lastChild.className = "disabled-action";
    tr.lastChild.textContent = `${values[4]}（v2）`;
    body.appendChild(tr);
  });
}

function renderConfirm() {
  const visible = Boolean(state.pendingAction && state.pendingAction.action_id);
  byId("confirmBar").classList.toggle("hidden", !visible);
  byId("floatConfirm").classList.toggle("hidden", !visible);
  if (visible) {
    setText("confirmText", `待确认：${state.pendingAction.intent || "操作"} · ${state.pendingAction.action_id}`);
  }
}

function appendAssistantMessage(role, text) {
  state.assistantMessages.push({ role, text });
  state.assistantMessages = state.assistantMessages.slice(-30);
  renderMessageList(byId("chatLog"), state.assistantMessages);
}

function appendFloatMessage(role, text) {
  state.floatMessages.push({ role, text });
  state.floatMessages = state.floatMessages.slice(-30);
  renderMessageList(byId("floatLog"), state.floatMessages);
}

function appendTargetMessage(target, role, text) {
  if (target === "float") {
    appendFloatMessage(role, text);
  } else {
    appendAssistantMessage(role, text);
  }
}

function renderMessageList(container, messages) {
  clear(container);
  if (!messages.length) {
    container.appendChild(emptyNode("等待输入。"));
    return;
  }
  messages.forEach((msg) => {
    const item = document.createElement("div");
    item.className = `message ${msg.role}`;
    item.textContent = msg.text;
    container.appendChild(item);
  });
  container.scrollTop = container.scrollHeight;
}

async function getJson(url) {
  try {
    const response = await fetch(url);
    return await response.json();
  } catch (error) {
    return { status: "python_offline", message: "Java 代理或 Python 服务不可用" };
  }
}

async function postJson(url, body) {
  try {
    const response = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body)
    });
    return await response.json();
  } catch (error) {
    return { status: "python_offline", message: "Java 代理或 Python 服务不可用" };
  }
}

function isProxyProblem(result) {
  return result && (result.status === "python_offline" || result.status === "python_bad_response");
}

function isConfirmAction(action) {
  return Boolean(action && action.kind === "tool_approval" && action.action_id);
}

function row(values) {
  const tr = document.createElement("tr");
  values.forEach((value) => {
    const td = document.createElement("td");
    td.textContent = value == null ? "-" : String(value);
    tr.appendChild(td);
  });
  return tr;
}

function emptyRow(text, colspan) {
  const tr = document.createElement("tr");
  const td = document.createElement("td");
  td.colSpan = colspan;
  td.className = "muted";
  td.textContent = text;
  tr.appendChild(td);
  return tr;
}

function emptyNode(text) {
  const node = document.createElement("div");
  node.className = "muted";
  node.textContent = text;
  return node;
}

function pretty(value) {
  return JSON.stringify(value, null, 2);
}

function setText(id, value) {
  byId(id).textContent = value == null ? "-" : String(value);
}

function byId(id) {
  return document.getElementById(id);
}

function clear(node) {
  while (node.firstChild) {
    node.removeChild(node.firstChild);
  }
}
